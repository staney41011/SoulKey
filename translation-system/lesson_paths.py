import re

from config import PERIOD_SHEET_RANGE, SPREADSHEET_ID
from google_io import extract_drive_id, read_values, require_child_folder


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


def resolve_lesson_folders(drive, sheets, period: int, lesson_label: str):
    """Resolve the deterministic Drive folders for one lesson.

    This module intentionally has no ASR / CUDA imports so translation-only
    notebooks and workers can use it without ctranslate2/faster-whisper.
    """
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
