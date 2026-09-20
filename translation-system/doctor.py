import shutil
import sys
from pathlib import Path

import torch

from asr import resolve_model_source
from config import ASR_MODEL, SPREADSHEET_ID, TASK_SHEET_RANGE
from google_io import build_google_services, read_values
from runner import resolve_lesson_folders, row_to_task
from source_io import find_drive_source
from youtube_io import extract_metadata


def ok(label, value="OK"):
    print(f"✅ {label}: {value}")


def fail(label, exc):
    print(f"❌ {label}: {type(exc).__name__}: {exc}")


def main():
    print("=" * 72)
    print("打開心靈的鎖匙｜Translation System Doctor")
    print("=" * 72)

    ok("Python", sys.version.split()[0])
    ok("CUDA", torch.cuda.is_available())
    if torch.cuda.is_available():
        ok("GPU", torch.cuda.get_device_name(0))

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("找不到 ffmpeg")
    ok("FFmpeg", ffmpeg)

    try:
        model_source = resolve_model_source(ASR_MODEL)
        model_path = Path(model_source)
        if model_path.exists():
            ok("永久 ASR 模型", model_source)
        else:
            print("⚠️ 永久 ASR 模型尚未掛載。")
    except Exception as exc:
        fail("ASR 模型檢查", exc)
        return 5

    try:
        drive, sheets = build_google_services()
        ok("Google OAuth")
    except Exception as exc:
        fail("Google OAuth", exc)
        return 2

    try:
        rows = read_values(sheets, SPREADSHEET_ID, TASK_SHEET_RANGE)
        ok("控制中心", f"讀到 {len(rows)} 列")
    except Exception as exc:
        fail("控制中心", exc)
        return 3

    first_task = None
    for index, raw in enumerate(rows, start=2):
        task = row_to_task(raw, index)
        if task["task_id"] and task["period"] is not None and task["lesson"]:
            first_task = task
            break

    if first_task:
        try:
            folders = resolve_lesson_folders(
                drive,
                sheets,
                first_task["period"],
                first_task["lesson"],
            )
            source = find_drive_source(drive, folders["source_video"])
            if source:
                ok("Drive 原始影片", source["name"])
            else:
                print(
                    "⚠️ 第1堂的 00_原始影片 目前是空的；"
                    "上傳影片後即可直接跑 ASR。"
                )
        except Exception as exc:
            fail("Drive 來源資料夾", exc)
            return 6

    first_url = None
    for row in rows:
        if len(row) > 4 and row[4]:
            first_url = row[4]
            break

    if first_url:
        try:
            meta = extract_metadata(
                first_url,
                Path("/kaggle/working/translate-system-doctor"),
            )
            ok("YouTube（選配）", meta.get("title", ""))
        except Exception as exc:
            print(
                "⚠️ YouTube 目前無法從 Kaggle 存取，"
                "但 Drive→ASR 不受影響。"
            )
            print(f"   {type(exc).__name__}: {exc}")

    print("\n🎉 核心系統可用。Drive 原始影片是主要處理來源。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
