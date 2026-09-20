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
    parser.add_argument("--all-langs", action="store_true")
    parser.add_argument("--max-tasks", type=int, default=1)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if not args.lang and not args.all_langs:
        parser.error("請指定 --lang en/th/es/id/vi 或 --all-langs")

    langs = list(LANGUAGE_NAMES) if args.all_langs else [args.lang]

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
            for lang in langs:
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
                result = synthesize_language(
                    segments=segments,
                    lang=lang,
                    model_id=TTS_MODELS[lang],
                    output_dir=workdir / f"tts-{lang}",
                )
                upload_tts_outputs(drive, folders["audio"], result)
                completed.append(lang)
                print(
                    f"[DONE] {lang}: {result['segment_count']} segments / "
                    f"{result['duration']:.1f}s"
                )

            if args.all_langs and len(completed) == len(LANGUAGE_NAMES):
                status = "完成"
            else:
                status = "部分完成：" + ",".join(completed)

            update_audio_status(
                sheets,
                task["sheet_row"],
                status,
                (
                    f"TTS完成：{','.join(completed)}；"
                    "已輸出 WAV/MP3/segments.zip；尚未做影片時間軸伸縮對齊"
                ),
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
            processed += 1

    print("")
    print("TTS 本次處理完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
