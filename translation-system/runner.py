import argparse
import re
import shutil
import subprocess
import wave
import sys
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from asr import transcribe_audio
from drive_naming import formal_drive_name
from config import (
    ASR_MODEL,
    COL,
    GLOSSARY_RANGE,
    PERIOD_SHEET_RANGE,
    SPREADSHEET_ID,
    TASK_SHEET_RANGE,
    TIMEZONE,
)
from google_io import (
    build_google_services,
    download_drive_file,
    extract_drive_id,
    find_file,
    read_values,
    require_child_folder,
    update_cells,
    upload_or_replace_file,
)
from youtube_io import download_audio, extract_metadata, save_metadata_json
from status_io import new_run_id, mark_running, mark_done, mark_error


def now_text():
    return datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")


def pad_row(row, length=20):
    return list(row) + [""] * max(0, length - len(row))


def digits(value):
    match = re.search(r"(\d+)", str(value or ""))
    return int(match.group(1)) if match else None


def get_period_folder_id(sheets, period: int):
    rows = read_values(sheets, SPREADSHEET_ID, PERIOD_SHEET_RANGE)
    for raw in rows:
        row = pad_row(raw, 8)
        code_num = digits(row[0])
        name_num = digits(row[1])
        if period in {code_num, name_num}:
            folder_id = extract_drive_id(row[5])
            if folder_id:
                return folder_id
    raise RuntimeError(f"期數設定找不到第 {period} 期的資料夾URL。")


def get_glossary_terms(sheets):
    rows = read_values(sheets, SPREADSHEET_ID, GLOSSARY_RANGE)
    return [str(row[0]).strip() for row in rows if row and str(row[0]).strip()]


def resolve_lesson_folders(drive, sheets, period: int, lesson_label: str):
    period_folder = get_period_folder_id(sheets, period)
    course_folder = require_child_folder(drive, period_folder, "01_課程")

    lesson_number = digits(lesson_label)
    if lesson_number is None:
        raise RuntimeError(f"無法辨識堂次：{lesson_label}")

    lesson_folder_name = f"{lesson_number:02d}_第{lesson_number}堂"
    lesson_folder = require_child_folder(drive, course_folder, lesson_folder_name)

    return {
        "lesson": lesson_folder,
        "source": require_child_folder(drive, lesson_folder, "00_來源資訊"),
        "transcript": require_child_folder(drive, lesson_folder, "01_中文逐字稿"),
        "translation": require_child_folder(drive, lesson_folder, "02_翻譯稿"),
        "subtitle": require_child_folder(drive, lesson_folder, "03_字幕"),
        "audio": require_child_folder(drive, lesson_folder, "04_音檔"),
        "video": require_child_folder(drive, lesson_folder, "05_完成影片"),
        "log": require_child_folder(drive, lesson_folder, "99_處理紀錄"),
    }


def update_task_row(sheets, sheet_row: int, **kwargs):
    col_letter = {
        "title": "D",
        "lecturer": "F",
        "asr": "H",
        "updated_at": "S",
        "note": "T",
    }
    updates = {}
    for key, value in kwargs.items():
        if key in col_letter:
            updates[f"任務佇列!{col_letter[key]}{sheet_row}"] = value
    update_cells(sheets, SPREADSHEET_ID, updates)


def process_metadata(sheets, task, sheet_row, workdir):
    metadata = extract_metadata(task["youtube_url"], workdir)

    title = metadata.get("title") or task.get("title") or ""
    lecturer = metadata.get("lecturer") or task.get("lecturer") or ""
    source = metadata.get("lecturer_source") or ""

    update_task_row(
        sheets,
        sheet_row,
        title=title,
        lecturer=lecturer,
        updated_at=now_text(),
        note=f"YouTube metadata完成；講師來源={source}",
    )

    task["title"] = title
    task["lecturer"] = lecturer
    return metadata


def upload_metadata(drive, source_folder_id, metadata, task, workdir):
    payload = dict(metadata or {})
    payload.update(
        {
            "task_id": task["task_id"],
            "course_uid": task.get("course_uid") or "",
            "period": task["period"],
            "lesson": task["lesson"],
            "youtube_url": task.get("youtube_url") or "",
            "saved_at": now_text(),
        }
    )
    path = workdir / "source_info.json"
    save_metadata_json(payload, path)
    upload_or_replace_file(
        drive,
        source_folder_id,
        path,
        "source_info.json",
        display_name=formal_drive_name(task, "source_info.json"),
    )


def process_asr(drive, sheets, task, sheet_row, metadata, glossary, workdir):
    folders = resolve_lesson_folders(
        drive,
        sheets,
        int(task["period"]),
        task["lesson"],
    )

    youtube_url = task.get("youtube_url") or ""
    if not youtube_url:
        raise RuntimeError("此任務沒有 YouTube URL。")

    update_task_row(
        sheets,
        sheet_row,
        asr="處理中",
        updated_at=now_text(),
        note="使用 YouTube Cookies 下載音訊並進行 ASR",
    )

    # A trusted audio file already uploaded into this lesson's source folder
    # bypasses Kaggle's YouTube egress bot check without accessing browser
    # cookies. This is optional: ordinary lessons retain YouTube-first.
    audio_path = None
    download_meta = {}
    for extension in ("webm", "m4a", "mp3", "wav"):
        canonical = "source_audio." + extension
        item = find_file(drive, folders["source"], canonical)
        if not item:
            continue
        workdir.mkdir(parents=True, exist_ok=True)
        source_file = workdir / canonical
        print(f"[SOURCE] Google Drive 預存音訊：{canonical}", flush=True)
        download_drive_file(drive, item["id"], source_file)
        normalized = workdir / "audio_16k_mono.wav"
        subprocess.run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(source_file), "-ac", "1", "-ar", "16000",
            str(normalized),
        ], check=True)
        with wave.open(str(normalized), "rb") as reader:
            duration = reader.getnframes() / float(reader.getframerate())
        if duration < 60:
            raise RuntimeError(
                f"Drive 預存音訊太短（{duration:.1f} 秒），"
                "不能當作完整課程音軌。"
            )
        download_meta = {
            "source_type": "drive_cached_audio",
            "webpage_url": youtube_url,
            "title": task.get("title") or "",
            "lecturer": task.get("lecturer") or "",
            "duration": duration,
            "auto_cc_paths": {},
        }
        audio_path = normalized
        print(
            f"[SOURCE] 已驗證預存完整音訊 duration={duration:.0f}s，"
            "略過 YouTube 下載與過期 Cookies。",
            flush=True,
        )
        break

    if audio_path is None:
        print("[SOURCE] 使用 YouTube + Cookies 直接取得音訊")
        audio_path, download_meta = download_audio(youtube_url, workdir)

    metadata = dict(metadata or {})
    download_meta.setdefault("source_type", "youtube")

    title = str(download_meta.get("title") or task.get("title") or "").strip()
    lecturer = str(download_meta.get("lecturer") or task.get("lecturer") or "").strip()
    if title:
        task["title"] = title
    if lecturer:
        task["lecturer"] = lecturer

    update_task_row(
        sheets,
        sheet_row,
        title=task.get("title") or "",
        lecturer=task.get("lecturer") or "",
        updated_at=now_text(),
        note="已取得音訊（"+download_meta["source_type"]+"）；開始 ASR",
    )

    metadata.update({
        "id": download_meta.get("id"),
        "title": download_meta.get("title") or task.get("title") or "",
        "description": download_meta.get("description") or "",
        "channel": download_meta.get("channel") or "",
        "uploader": download_meta.get("uploader") or "",
        "upload_date": download_meta.get("upload_date") or "",
        "duration": download_meta.get("duration"),
        "webpage_url": download_meta.get("webpage_url") or youtube_url,
        "lecturer": download_meta.get("lecturer") or task.get("lecturer") or "",
        "lecturer_source": download_meta.get("lecturer_source") or "",
        "source": download_meta,
    })
    upload_metadata(drive, folders["source"], metadata, task, workdir)

    auto_cc_paths = dict(download_meta.get("auto_cc_paths") or {})
    english_cc_path = str(download_meta.get("english_cc_path") or "").strip()
    if english_cc_path and "en" not in auto_cc_paths:
        auto_cc_paths["en"] = english_cc_path

    # Compatibility contract: English review continues to read youtube.en.json.
    uploaded_cc_languages = []
    for lang, raw_path in auto_cc_paths.items():
        if str(lang).lower().startswith("zh"):
            print(
                f"[SOURCE] 略過 YouTube 中文 CC ({lang})；"
                "中文只使用原始音軌 Taiwan-Breeze ASR。"
            )
            continue

        cc_path = Path(str(raw_path))
        if not cc_path.exists():
            continue

        uploaded_any = False
        for suffix in ("json", "txt", "srt", "transcript.txt"):
            local_path = cc_path.with_suffix("." + suffix)
            if not local_path.exists():
                continue
            canonical_name = f"youtube.{lang}.{suffix}"
            upload_or_replace_file(
                drive,
                folders["source"],
                local_path,
                canonical_name,
                display_name=formal_drive_name(task, canonical_name),
            )
            uploaded_any = True

        if uploaded_any:
            uploaded_cc_languages.append(lang)

    if uploaded_cc_languages:
        print(
            "[SOURCE] YouTube auto CC 已寫入 00_來源資訊："
            + ",".join(uploaded_cc_languages)
        )
    else:
        print("[SOURCE] 本堂沒有可用的 YouTube auto CC；後續仍可只用中文 ASR。")

    result = transcribe_audio(
        audio_path=str(audio_path),
        output_dir=workdir / "asr_output",
        model_name=ASR_MODEL,
        glossary_terms=glossary,
    )

    upload_or_replace_file(
        drive,
        folders["transcript"],
        result["txt"],
        "zh-TW.txt",
        display_name=formal_drive_name(task, "zh-TW.txt"),
    )
    upload_or_replace_file(
        drive,
        folders["transcript"],
        result["transcript"],
        "zh-TW.transcript.txt",
        display_name=formal_drive_name(task, "zh-TW.transcript.txt"),
    )
    upload_or_replace_file(
        drive,
        folders["transcript"],
        result["srt"],
        "zh-TW.srt",
        display_name=formal_drive_name(task, "zh-TW.srt"),
    )
    upload_or_replace_file(
        drive,
        folders["transcript"],
        result["json"],
        "segments.json",
        display_name=formal_drive_name(task, "segments.json"),
    )

    duration = result.get("duration")
    duration_text = f"{duration:.0f}s" if isinstance(duration, (int, float)) else "未知"
    update_task_row(
        sheets,
        sheet_row,
        asr="完成",
        updated_at=now_text(),
        note=(
            f"ASR完成；來源={download_meta['source_type']}；"
            f"{result['segment_count']}段；音訊長度={duration_text}；"
            f"AutoCC={','.join(uploaded_cc_languages) if uploaded_cc_languages else '無'}"
        ),
    )


def row_to_task(raw, sheet_row):
    row = pad_row(raw, 20)
    period = digits(row[COL["period"]])
    return {
        "sheet_row": sheet_row,
        "task_id": str(row[COL["task_id"]] or "").strip(),
        "period": period,
        "lesson": str(row[COL["lesson"]] or "").strip(),
        "title": str(row[COL["title"]] or "").strip(),
        "youtube_url": str(row[COL["youtube_url"]] or "").strip(),
        "lecturer": str(row[COL["lecturer"]] or "").strip(),
        "course_uid": str(row[COL["course_uid"]] or "").strip(),
        "schedule_status": str(row[COL["schedule_status"]] or "").strip(),
        "original_period": digits(row[COL["original_period"]]),
        "original_lesson": str(row[COL["original_lesson"]] or "").strip(),
        "asr": str(row[COL["asr"]] or "").strip(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage",
        choices=["metadata", "asr", "all"],
        default="all",
        help="metadata=只抓YouTube資訊；asr/all=YouTube Cookies→ASR",
    )
    parser.add_argument("--period", type=int, default=None)
    parser.add_argument("--task-id", default=None)
    parser.add_argument("--max-tasks", type=int, default=4)
    parser.add_argument("--force-metadata", action="store_true")
    parser.add_argument("--force-asr", action="store_true")
    args = parser.parse_args()

    print("=" * 72)
    print("打開心靈的鎖匙｜全球翻譯系統 Runner v1.2")
    print(f"Sheet: {SPREADSHEET_ID}")
    print(f"Stage: {args.stage}")
    print("來源策略：YouTube + Kaggle Secret Cookies")
    print("=" * 72)

    drive, sheets = build_google_services()
    glossary = get_glossary_terms(sheets)

    raw_rows = read_values(sheets, SPREADSHEET_ID, TASK_SHEET_RANGE)
    tasks = []
    for index, raw in enumerate(raw_rows, start=2):
        task = row_to_task(raw, index)
        if not task["task_id"] or task["period"] is None or not task["lesson"]:
            continue
        if not task["youtube_url"]:
            continue
        if args.period is not None and task["period"] != args.period:
            continue
        if args.task_id and task["task_id"] != args.task_id:
            continue
        tasks.append(task)

    if not tasks:
        message = ("找不到任務：" + str(args.task_id)) if args.task_id else "沒有可處理的任務。"
        print("[ERROR] " + message, file=sys.stderr)
        if args.task_id:
            raise RuntimeError(message)
        return 0

    processed = 0
    failed = 0
    for task in tasks:
        if processed >= args.max_tasks:
            break

        sheet_row = task["sheet_row"]
        workdir = Path("/kaggle/working/translate-system") / task["task_id"]
        workdir.mkdir(parents=True, exist_ok=True)

        print("\n" + "-" * 72)
        print(
            f"[TASK] {task['task_id']} / "
            f"第{task['period']}期 / {task['lesson']}"
        )
        print(f"[URL] {task['youtube_url']}")

        metadata = {}
        status_stage = "metadata" if args.stage == "metadata" else "asr"
        run_id = new_run_id(task["task_id"], status_stage)
        mark_running(
            task["task_id"],
            status_stage,
            sheets=sheets,
            run_id=run_id,
            message=(
                "讀取 YouTube Metadata"
                if status_stage == "metadata"
                else "下載音訊並執行 ASR"
            ),
            progress=0,
        )
        try:
            needs_metadata = (
                args.stage == "metadata"
                and (
                    args.force_metadata
                    or not task["title"]
                    or not task["lecturer"]
                )
            )

            if needs_metadata:
                try:
                    metadata = process_metadata(
                        sheets,
                        task,
                        sheet_row,
                        workdir,
                    )
                    print(f"[META] 課程：{task['title']}")
                    print(f"[META] 講師：{task['lecturer']}")
                except Exception as exc:
                    print(
                        f"[META] metadata 取得失敗："
                        f"{type(exc).__name__}: {exc}"
                    )

            if args.stage == "metadata":
                mark_done(
                    task["task_id"],
                    "metadata",
                    sheets=sheets,
                    run_id=run_id,
                    message="YouTube Metadata 完成",
                )
                processed += 1
                continue

            if task["asr"] == "完成" and not args.force_asr:
                print("[ASR] 已完成，略過。使用 --force-asr 可重跑。")
                mark_done(
                    task["task_id"],
                    "asr",
                    sheets=sheets,
                    run_id=run_id,
                    message="ASR 先前已完成，本次略過",
                )
                processed += 1
                continue

            process_asr(
                drive,
                sheets,
                task,
                sheet_row,
                metadata,
                glossary,
                workdir,
            )
            print("[DONE] ASR 結果已寫回 Google Drive。")
            mark_done(
                task["task_id"],
                "asr",
                sheets=sheets,
                run_id=run_id,
                message="ASR 結果已寫回 Google Drive",
            )
            processed += 1

            try:
                shutil.rmtree(workdir)
            except Exception:
                pass

        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            print(f"[ERROR] {message}", file=sys.stderr)
            traceback.print_exc()

            update_task_row(
                sheets,
                sheet_row,
                asr="錯誤",
                updated_at=now_text(),
                note=message[:450],
            )
            mark_error(
                task["task_id"],
                status_stage,
                sheets=sheets,
                run_id=run_id,
                exc=exc,
            )
            processed += 1
            failed += 1

    print("\nRunner 本次處理完成。")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
