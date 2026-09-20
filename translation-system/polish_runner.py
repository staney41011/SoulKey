import argparse
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from config import COL, SPREADSHEET_ID, TASK_SHEET_RANGE, TIMEZONE, POLISH_MODEL
from google_io import (
    build_google_services,
    download_drive_file,
    find_file,
    read_values,
    update_cells,
    upload_or_replace_file,
)
from polish import polish_segments
from runner import get_glossary_terms, resolve_lesson_folders
from status_io import new_run_id, mark_running, mark_done, mark_error


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
        "asr": str(row[COL["asr"]] or "").strip(),
        "zh_review": str(row[COL["zh_review"]] or "").strip(),
    }


def update_status(sheets, row, status, note):
    update_cells(
        sheets,
        SPREADSHEET_ID,
        {
            f"任務佇列!I{row}": status,
            f"任務佇列!S{row}": now_text(),
            f"任務佇列!T{row}": note[:450],
        },
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", type=int, default=None)
    parser.add_argument("--task-id", default=None)
    parser.add_argument("--max-tasks", type=int, default=1)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    print("=" * 72)
    print("打開心靈的鎖匙｜AI 中文校稿")
    print(f"Model: {POLISH_MODEL}")
    print("=" * 72)

    drive, sheets = build_google_services()
    glossary = get_glossary_terms(sheets)
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

        run_id = new_run_id(task["task_id"], "polish")

        if task["zh_review"] == "完成" and not args.force:
            print("[POLISH] 已完成；如要重跑請加 --force")
            mark_done(
                task["task_id"],
                "polish",
                sheets=sheets,
                run_id=run_id,
                message="AI 中文校稿先前已完成，本次略過",
            )
            processed += 1
            continue

        mark_running(
            task["task_id"],
            "polish",
            sheets=sheets,
            run_id=run_id,
            message="AI 中文校稿執行中",
            progress=0,
        )

        try:
            if task["asr"] != "完成":
                raise RuntimeError("ASR 尚未完成，不能進行 AI 校稿。")

            update_status(
                sheets,
                task["sheet_row"],
                "處理中",
                "AI 中文校稿中：專有名詞、同音錯字、標點與斷句",
            )

            folders = resolve_lesson_folders(
                drive,
                sheets,
                task["period"],
                task["lesson"],
            )
            source = find_file(drive, folders["transcript"], "segments.json")
            if not source:
                raise RuntimeError("Google Drive 找不到 segments.json")

            workdir = Path("/kaggle/working/translate-system-polish") / task["task_id"]
            workdir.mkdir(parents=True, exist_ok=True)
            segments_path = workdir / "segments.json"
            download_drive_file(drive, source["id"], segments_path)

            result = polish_segments(
                segments_json_path=segments_path,
                output_dir=workdir / "output",
                model_name=POLISH_MODEL,
                glossary_terms=glossary,
            )

            upload_or_replace_file(
                drive, folders["transcript"], result["txt"], "zh-TW.polished.txt"
            )
            upload_or_replace_file(
                drive, folders["transcript"], result["srt"], "zh-TW.polished.srt"
            )
            upload_or_replace_file(
                drive, folders["transcript"], result["readable"], "zh-TW.readable.txt"
            )
            upload_or_replace_file(
                drive, folders["transcript"], result["report"], "polish_report.json"
            )

            update_status(
                sheets,
                task["sheet_row"],
                "完成",
                (
                    f"AI校稿完成；{result['segment_count']}段；"
                    f"修改{result['changed_count']}段；"
                    f"待確認{result['uncertain_count']}處"
                ),
            )
            done_message = (
                f"AI校稿完成：修改 {result['changed_count']} 段；"
                f"待人工確認 {result['uncertain_count']} 處"
            )
            print(
                f"[DONE] AI校稿完成：修改 {result['changed_count']} 段，"
                f"待確認 {result['uncertain_count']} 處"
            )
            mark_done(
                task["task_id"],
                "polish",
                sheets=sheets,
                run_id=run_id,
                message=done_message,
            )
            processed += 1

        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            print(f"[ERROR] {message}", file=sys.stderr)
            traceback.print_exc()
            update_status(sheets, task["sheet_row"], "錯誤", message)
            processed += 1

    print("")
    print("AI 中文校稿本次處理完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
