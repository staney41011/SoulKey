import argparse
import re
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from asr import transcribe_audio
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
    extract_drive_id,
    read_values,
    require_child_folder,
    update_cells,
    upload_or_replace_file,
)
from source_io import find_drive_source, prepare_drive_audio
from youtube_io import download_audio, extract_metadata, save_metadata_json


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
        "source_video": require_child_folder(drive, lesson_folder, "00_原始影片"),
        "source": require_child_folder(drive, lesson_folder, "00_來源資訊"),
        "transcript": require_child_folder(drive, lesson_folder, "01_中文逐字稿"),
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
            "period": task["period"],
            "lesson": task["lesson"],
            "youtube_url": task.get("youtube_url") or "",
            "saved_at": now_text(),
        }
    )
    path = workdir / "source_info.json"
    save_metadata_json(payload, path)
    upload_or_replace_file(drive, source_folder_id, path, "source_info.json")


def get_audio_source(drive, task, folders, workdir):
    drive_source = find_drive_source(drive, folders["source_video"])
    if drive_source:
        print(f"[SOURCE] 使用 Google Drive：{drive_source['name']}")
        audio_path, source_meta = prepare_drive_audio(
            drive,
            drive_source,
            workdir,
        )
        return audio_path, source_meta

    youtube_url = task.get("youtube_url") or ""
    if youtube_url:
        print("[SOURCE] Drive 沒有原始影片，嘗試 YouTube 備援。")
        audio_path, source_meta = download_audio(youtube_url, workdir)
        source_meta["source_type"] = "youtube"
        return audio_path, source_meta

    raise RuntimeError(
        "找不到來源：請把影片放進此堂課的 00_原始影片，"
        "或在控制中心提供 YouTube URL。"
    )


def process_asr(drive, sheets, task, sheet_row, metadata, glossary, workdir):
    folders = resolve_lesson_folders(
        drive,
        sheets,
        int(task["period"]),
        task["lesson"],
    )

    update_task_row(
        sheets,
        sheet_row,
        asr="處理中",
        updated_at=now_text(),
        note="尋找 Drive 原始影片並進行 ASR",
    )

    audio_path, source_meta = get_audio_source(
        drive,
        task,
        folders,
        workdir,
    )

    metadata = dict(metadata or {})
    metadata["source"] = source_meta
    upload_metadata(drive, folders["source"], metadata, task, workdir)

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
    )
    upload_or_replace_file(
        drive,
        folders["transcript"],
        result["srt"],
        "zh-TW.srt",
    )
    upload_or_replace_file(
        drive,
        folders["transcript"],
        result["json"],
        "segments.json",
    )

    duration = result.get("duration")
    duration_text = f"{duration:.0f}s" if isinstance(duration, (int, float)) else "未知"
    source_type = source_meta.get("source_type", "unknown")
    update_task_row(
        sheets,
        sheet_row,
        asr="完成",
        updated_at=now_text(),
        note=(
            f"ASR完成；來源={source_type}；"
            f"{result['segment_count']}段；音訊長度={duration_text}"
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
        "asr": str(row[COL["asr"]] or "").strip(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage",
        choices=["metadata", "asr", "all"],
        default="all",
        help="metadata=只抓YouTube資訊；asr/all=Drive優先逐字稿",
    )
    parser.add_argument("--period", type=int, default=None)
    parser.add_argument("--max-tasks", type=int, default=4)
    parser.add_argument("--force-metadata", action="store_true")
    parser.add_argument("--force-asr", action="store_true")
    args = parser.parse_args()

    print("=" * 72)
    print("打開心靈的鎖匙｜全球翻譯系統 Runner v1.1")
    print(f"Sheet: {SPREADSHEET_ID}")
    print(f"Stage: {args.stage}")
    print("來源策略：Google Drive 優先；YouTube 僅備援")
    print("=" * 72)

    drive, sheets = build_google_services()
    glossary = get_glossary_terms(sheets)

    raw_rows = read_values(sheets, SPREADSHEET_ID, TASK_SHEET_RANGE)
    tasks = []
    for index, raw in enumerate(raw_rows, start=2):
        task = row_to_task(raw, index)
        if not task["task_id"] or task["period"] is None or not task["lesson"]:
            continue
        if args.period is not None and task["period"] != args.period:
            continue
        tasks.append(task)

    if not tasks:
        print("沒有可處理的任務。")
        return 0

    processed = 0
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

        metadata = {}
        try:
            needs_metadata = (
                args.force_metadata
                or not task["title"]
                or not task["lecturer"]
            )

            if args.stage == "metadata":
                if not task["youtube_url"]:
                    print("[META] 沒有 YouTube URL，略過。")
                elif needs_metadata:
                    metadata = process_metadata(
                        sheets,
                        task,
                        sheet_row,
                        workdir,
                    )
                    print(f"[META] 課程：{task['title']}")
                    print(f"[META] 講師：{task['lecturer']}")
                else:
                    print("[META] 已有課程名稱與講師。")
                processed += 1
                continue

            if needs_metadata and task["youtube_url"]:
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
                        f"[META] YouTube metadata 取得失敗，"
                        f"但不阻擋 ASR：{type(exc).__name__}: {exc}"
                    )

            if task["asr"] == "完成" and not args.force_asr:
                print("[ASR] 已完成，略過。使用 --force-asr 可重跑。")
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
            processed += 1

    print("\nRunner 本次處理完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
