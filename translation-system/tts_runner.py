import argparse
import json
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from config import (
    COL,
    SPREADSHEET_ID,
    TASK_SHEET_RANGE,
    TIMEZONE,
    TTS_MODELS,
)
from google_io import (
    build_google_services,
    download_drive_file,
    find_file,
    read_values,
    update_cells,
    upload_or_replace_file,
)
from runner import resolve_lesson_folders
from translation_engine import LANGUAGE_NAMES
from tts_engine import synthesize_language
from status_io import new_run_id, mark_running, mark_done, mark_needs_review, mark_error


def now_text():
    return datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")


def pad_row(row, length=20):
    return list(row) + [""] * max(0, length - len(row))


def digits(value):
    match = re.search(r"(\d+)", str(value or ""))
    return int(match.group(1)) if match else None


def row_to_task(raw, sheet_row):
    row = pad_row(raw, 20)
    return {
        "sheet_row": sheet_row,
        "task_id": str(row[COL["task_id"]] or "").strip(),
        "period": digits(row[COL["period"]]),
        "lesson": str(row[COL["lesson"]] or "").strip(),
        "en": str(row[COL["en"]] or "").strip(),
        "th": str(row[COL["th"]] or "").strip(),
        "es": str(row[COL["es"]] or "").strip(),
        "id": str(row[COL["id"]] or "").strip(),
        "vi": str(row[COL["vi"]] or "").strip(),
        "audio": str(row[COL["audio"]] or "").strip(),
    }


def update_audio_status(sheets, row, status, note):
    update_cells(
        sheets,
        SPREADSHEET_ID,
        {
            f"任務佇列!P{row}": status,
            f"任務佇列!S{row}": now_text(),
            f"任務佇列!T{row}": note[:450],
        },
    )


def load_translation_from_drive(drive, folder_id, lang, workdir):
    name = f"{lang}.json"
    item = find_file(drive, folder_id, name)
    if not item:
        raise RuntimeError(f"找不到翻譯檔 {name}")
    path = workdir / name
    download_drive_file(drive, item["id"], path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    segments = payload.get("segments") or []
    if not segments:
        raise RuntimeError(f"{name} 沒有 segments")
    return segments


def upload_tts_outputs(drive, audio_folder, result):
    for key in ("mp3", "wav", "manifest", "segments_zip"):
        path = result[key]
        upload_or_replace_file(drive, audio_folder, path, Path(path).name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", default=None)
    parser.add_argument("--period", type=int, default=None)
    parser.add_argument("--lang", choices=list(LANGUAGE_NAMES), default=None)
    parser.add_argument(
        "--langs",
        default=None,
        help="逗號分隔多語言，例如 en,es；只處理指定語言",
    )
    parser.add_argument("--all-langs", action="store_true")
    parser.add_argument("--max-tasks", type=int, default=1)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if sum(bool(x) for x in [args.lang, args.langs, args.all_langs]) != 1:
        parser.error("請擇一指定 --lang、--langs en,es 或 --all-langs")

    if args.all_langs:
        langs = list(LANGUAGE_NAMES)
    elif args.langs:
        langs = [x.strip() for x in args.langs.split(",") if x.strip()]
        invalid = [x for x in langs if x not in LANGUAGE_NAMES]
        if invalid:
            parser.error("不支援的語言代碼：" + ",".join(invalid))
        # 去重但保留順序
        langs = list(dict.fromkeys(langs))
    else:
        langs = [args.lang]

    print("=" * 72)
    print("打開心靈的鎖匙｜多語 TTS")
    print("引擎：Meta MMS-TTS / VITS")
    print("=" * 72)

    drive, sheets = build_google_services()
    rows = read_values(sheets, SPREADSHEET_ID, TASK_SHEET_RANGE)

    tasks = []
    for index, raw in enumerate(rows, start=2):
        task = row_to_task(raw, index)
        if not task["task_id"] or task["period"] is None or not task["lesson"]:
            continue
        if args.period is not None and task["period"] != args.period:
            continue
        if args.task_id and task["task_id"] != args.task_id:
            continue
        tasks.append(task)

    if not tasks:
        print("沒有符合條件的任務。")
        return 0

    processed = 0
    for task in tasks:
        if processed >= args.max_tasks:
            break

        print("")
        print("-" * 72)
        print(f"[TASK] {task['task_id']} / 第{task['period']}期 / {task['lesson']}")

        status_stage = "tts"
        run_id = new_run_id(task["task_id"], status_stage)
        mark_running(
            task["task_id"],
            status_stage,
            sheets=sheets,
            run_id=run_id,
            message="音檔生成中：" + ",".join(langs),
            progress=0,
        )

        try:
            folders = resolve_lesson_folders(
                drive,
                sheets,
                task["period"],
                task["lesson"],
            )
            workdir = Path("/kaggle/working/translate-system-tts") / task["task_id"]
            workdir.mkdir(parents=True, exist_ok=True)

            update_audio_status(
                sheets,
                task["sheet_row"],
                "處理中",
                "多語音檔生成中",
            )

            completed = []
            over_duration = []
            for lang in langs:
                lang_stage = f"tts:{lang}"
                lang_run_id = new_run_id(task["task_id"], lang_stage)
                mark_running(
                    task["task_id"],
                    lang_stage,
                    sheets=sheets,
                    run_id=lang_run_id,
                    message=f"{LANGUAGE_NAMES[lang]} 音檔生成中",
                    progress=0,
                )

                translation_status = task.get(lang, "")
                if translation_status not in {"完成", "待人工確認"}:
                    raise RuntimeError(
                        f"{LANGUAGE_NAMES[lang]} 翻譯尚未產生，不能做 TTS。"
                    )

                print(f"[TTS] {LANGUAGE_NAMES[lang]} ({lang})")
                segments = load_translation_from_drive(
                    drive,
                    folders["translation"],
                    lang,
                    workdir,
                )
                source_duration = max(
                    float(seg.get("end", 0) or 0)
                    for seg in segments
                )
                result = synthesize_language(
                    segments=segments,
                    lang=lang,
                    model_id=TTS_MODELS[lang],
                    output_dir=workdir / f"tts-{lang}",
                    target_duration=source_duration,
                )
                upload_tts_outputs(drive, folders["audio"], result)
                completed.append(lang)
                if not result["within_source_duration"]:
                    over_duration.append({
                        "lang": lang,
                        "over": result["over_by_seconds"],
                    })
                    lang_note = (
                        f"{LANGUAGE_NAMES[lang]} 音檔已產生；"
                        f"自然朗讀超過原片 {result['over_by_seconds']:.1f}s；"
                        "未調速、未截斷"
                    )
                    print(
                        f"[WARN] {lang}: 自然朗讀超過原片 "
                        f"{result['over_by_seconds']:.1f}s；未調速、未截斷。"
                    )
                    mark_needs_review(
                        task["task_id"],
                        lang_stage,
                        sheets=sheets,
                        run_id=lang_run_id,
                        message=lang_note,
                    )
                else:
                    lang_note = (
                        f"{LANGUAGE_NAMES[lang]} 音檔完成；"
                        f"speech={result['speech_duration']:.1f}s；"
                        f"target={result['target_duration']:.1f}s"
                    )
                    print(
                        f"[DONE] {lang}: speech={result['speech_duration']:.1f}s / "
                        f"target={result['target_duration']:.1f}s / "
                        f"尾端靜音={result['remaining_silence']:.1f}s"
                    )
                    mark_done(
                        task["task_id"],
                        lang_stage,
                        sheets=sheets,
                        run_id=lang_run_id,
                        message=lang_note,
                    )

            if over_duration:
                status = "待人工確認"
                over_text = ",".join(
                    f"{item['lang']}+{item['over']:.1f}s"
                    for item in over_duration
                )
                note = (
                    f"TTS已產生：{','.join(completed)}；"
                    f"超過原片總長：{over_text}；"
                    "未調速、未截斷，請先處理超時語言"
                )
            elif len(completed) == len(langs):
                status = "完成"
                note = (
                    f"TTS完成：{','.join(completed)}；"
                    "本次指定語言皆在原片總長內結束；較短音檔只在尾端補靜音"
                )
            else:
                status = "部分完成：" + ",".join(completed)
                note = (
                    f"TTS完成：{','.join(completed)}；"
                    "已輸出 WAV/MP3/segments.zip；不做逐段時間對齊或調速"
                )

            update_audio_status(
                sheets,
                task["sheet_row"],
                status,
                note,
            )

            if status == "完成":
                mark_done(
                    task["task_id"],
                    status_stage,
                    sheets=sheets,
                    run_id=run_id,
                    message=note,
                )
            else:
                mark_needs_review(
                    task["task_id"],
                    status_stage,
                    sheets=sheets,
                    run_id=run_id,
                    message=note,
                )

            processed += 1

        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            print(f"[ERROR] {message}", file=sys.stderr)
            traceback.print_exc()
            update_audio_status(
                sheets,
                task["sheet_row"],
                "錯誤",
                message,
            )
            mark_error(
                task["task_id"],
                status_stage,
                sheets=sheets,
                run_id=run_id,
                exc=exc,
            )
            processed += 1

    print("")
    print("TTS 本次處理完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
