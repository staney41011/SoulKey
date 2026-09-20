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
    GLOSSARY_FULL_RANGE,
    SPREADSHEET_ID,
    TASK_SHEET_RANGE,
    TIMEZONE,
    TRANSLATION_MODEL,
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
from translation_engine import (
    LANGUAGE_NAMES,
    load_segments_json,
    modernize_to_vernacular,
    translate_segments,
)


LANG_COLUMN = {
    "en": "J",
    "th": "K",
    "es": "L",
    "id": "M",
    "vi": "N",
}


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
        "en": str(row[COL["en"]] or "").strip(),
        "th": str(row[COL["th"]] or "").strip(),
        "es": str(row[COL["es"]] or "").strip(),
        "id": str(row[COL["id"]] or "").strip(),
        "vi": str(row[COL["vi"]] or "").strip(),
    }


def update_note(sheets, row, note):
    update_cells(
        sheets,
        SPREADSHEET_ID,
        {
            f"任務佇列!S{row}": now_text(),
            f"任務佇列!T{row}": note[:450],
        },
    )


def update_lang_status(sheets, row, lang, status, note=""):
    updates = {
        f"任務佇列!{LANG_COLUMN[lang]}{row}": status,
        f"任務佇列!S{row}": now_text(),
    }
    if note:
        updates[f"任務佇列!T{row}"] = note[:450]
    update_cells(sheets, SPREADSHEET_ID, updates)


def get_glossary_rows(sheets):
    return read_values(sheets, SPREADSHEET_ID, GLOSSARY_FULL_RANGE)


def select_chinese_source(drive, transcript_folder, workdir, allow_draft=False):
    """
    正式優先：zh-TW.final.json
    測試模式：可用 polish_report.json，但若仍有 uncertain 則明確標記 draft。
    """
    final_file = find_file(drive, transcript_folder, "zh-TW.final.json")
    if final_file:
        path = workdir / "zh-TW.final.json"
        download_drive_file(drive, final_file["id"], path)
        return path, "final", 0

    if not allow_draft:
        raise RuntimeError(
            "找不到 zh-TW.final.json。中文尚未人工定稿；"
            "若只是測試整條翻譯流程，可加 --allow-draft。"
        )

    report_file = find_file(drive, transcript_folder, "polish_report.json")
    if not report_file:
        raise RuntimeError("找不到 zh-TW.final.json 或 polish_report.json")

    path = workdir / "polish_report.json"
    download_drive_file(drive, report_file["id"], path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    uncertain_count = int(payload.get("uncertain_count") or 0)
    return path, "polished_draft", uncertain_count


def upload_result_set(drive, folder_id, result):
    for key in ("json", "txt", "srt"):
        path = result[key]
        upload_or_replace_file(drive, folder_id, path, Path(path).name)


def download_translation_json(drive, folder_id, lang, workdir):
    name = f"{lang}.json"
    item = find_file(drive, folder_id, name)
    if not item:
        raise RuntimeError(f"找不到 {name}。請先完成前一階段。")
    path = workdir / name
    download_drive_file(drive, item["id"], path)
    return path


def process_modernize(
    drive,
    sheets,
    task,
    folders,
    glossary_rows,
    workdir,
    allow_draft,
):
    source_path, source_type, source_uncertain = select_chinese_source(
        drive,
        folders["transcript"],
        workdir,
        allow_draft=allow_draft,
    )
    source_segments = load_segments_json(source_path)

    if source_type != "final":
        print(
            f"[WARNING] 使用 AI 校稿草稿做白話化；"
            f"來源仍有 {source_uncertain} 處待人工確認。"
        )

    result = modernize_to_vernacular(
        source_segments=source_segments,
        output_dir=workdir / "vernacular",
        model_name=TRANSLATION_MODEL,
        glossary_rows=glossary_rows,
    )
    upload_result_set(drive, folders["translation"], result)

    note = (
        f"白話文完成；來源={source_type}；"
        f"來源待確認={source_uncertain}；"
        f"白話文待確認={result['review_required_count']}"
    )
    update_note(sheets, task["sheet_row"], note)
    print(f"[DONE] {note}")
    return result


def process_translation(
    drive,
    sheets,
    task,
    folders,
    glossary_rows,
    workdir,
    lang,
    force=False,
):
    if not force and task.get(lang) == "完成":
        print(f"[TRANSLATE:{lang}] 已完成，略過。")
        return None

    update_lang_status(
        sheets,
        task["sheet_row"],
        lang,
        "處理中",
        f"{LANGUAGE_NAMES[lang]} 翻譯中",
    )

    if lang == "en":
        source_path = download_translation_json(
            drive,
            folders["translation"],
            "zh-TW.vernacular",
            workdir,
        )
        source_segments = load_segments_json(source_path)
        source_language = "Traditional Chinese vernacular"
    else:
        source_path = download_translation_json(
            drive,
            folders["translation"],
            "en",
            workdir,
        )
        source_segments = load_segments_json(source_path)
        source_language = "English pivot"

    result = translate_segments(
        source_segments=source_segments,
        source_language=source_language,
        target_code=lang,
        output_dir=workdir / f"translate-{lang}",
        model_name=TRANSLATION_MODEL,
        glossary_rows=glossary_rows,
    )
    upload_result_set(drive, folders["translation"], result)

    status = "待人工確認" if result["review_required_count"] else "完成"
    note = (
        f"{LANGUAGE_NAMES[lang]} 完成；"
        f"翻譯待確認={result['review_required_count']}；"
        f"來源={'白話中文' if lang == 'en' else 'English'}"
    )
    update_lang_status(
        sheets,
        task["sheet_row"],
        lang,
        status,
        note,
    )
    print(f"[DONE] {note}")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage",
        choices=["modernize", "translate", "translate-all", "all"],
        default="all",
    )
    parser.add_argument("--lang", choices=list(LANGUAGE_NAMES), default=None)
    parser.add_argument("--period", type=int, default=None)
    parser.add_argument("--task-id", default=None)
    parser.add_argument("--max-tasks", type=int, default=1)
    parser.add_argument(
        "--allow-draft",
        action="store_true",
        help="允許尚未人工 final 的 polish_report.json 作為測試來源",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.stage == "translate" and not args.lang:
        parser.error("--stage translate 必須指定 --lang")

    print("=" * 72)
    print("打開心靈的鎖匙｜白話中文 → English Pivot → 多語翻譯")
    print(f"Model: {TRANSLATION_MODEL}")
    print("=" * 72)

    drive, sheets = build_google_services()
    glossary_rows = get_glossary_rows(sheets)
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
            workdir = Path("/kaggle/working/translate-system-translation") / task["task_id"]
            workdir.mkdir(parents=True, exist_ok=True)

            if args.stage in {"modernize", "all"}:
                process_modernize(
                    drive,
                    sheets,
                    task,
                    folders,
                    glossary_rows,
                    workdir,
                    allow_draft=args.allow_draft,
                )

            if args.stage == "translate":
                if args.lang != "en":
                    # 強制確保 English pivot 存在。
                    en_file = find_file(drive, folders["translation"], "en.json")
                    if not en_file:
                        raise RuntimeError(
                            "其他語言必須從 English pivot 翻譯；"
                            "請先執行 --stage translate --lang en。"
                        )
                process_translation(
                    drive,
                    sheets,
                    task,
                    folders,
                    glossary_rows,
                    workdir,
                    args.lang,
                    force=args.force,
                )

            if args.stage in {"translate-all", "all"}:
                # translate-all 若沒有白話文，就拒絕；all 則已在上面產生。
                vernacular = find_file(
                    drive,
                    folders["translation"],
                    "zh-TW.vernacular.json",
                )
                if not vernacular:
                    raise RuntimeError(
                        "找不到 zh-TW.vernacular.json，"
                        "請先執行 --stage modernize。"
                    )

                for lang in ["en", "th", "es", "id", "vi"]:
                    if lang != "en":
                        en_file = find_file(
                            drive,
                            folders["translation"],
                            "en.json",
                        )
                        if not en_file:
                            raise RuntimeError(
                                "English pivot 尚未產生，不能進行其他語言。"
                            )
                    process_translation(
                        drive,
                        sheets,
                        task,
                        folders,
                        glossary_rows,
                        workdir,
                        lang,
                        force=args.force,
                    )

            processed += 1

        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            print(f"[ERROR] {message}", file=sys.stderr)
            traceback.print_exc()
            update_note(sheets, task["sheet_row"], message)
            processed += 1

    print("")
    print("翻譯流程本次處理完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
