import shutil
import sys
from pathlib import Path

import torch

from asr import resolve_model_source
from config import ASR_MODEL, SPREADSHEET_ID, TASK_SHEET_RANGE
from google_io import build_google_services, get_secret, read_values
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
        _, sheets = build_google_services()
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

    cookies = get_secret("YOUTUBE_COOKIES_B64", required=False)
    if not cookies:
        print("❌ YOUTUBE_COOKIES_B64: 尚未設定")
        return 6
    ok("YOUTUBE_COOKIES_B64", "已設定（內容不顯示）")

    first_url = None
    for row in rows:
        if len(row) > 4 and row[4]:
            first_url = row[4]
            break

    if not first_url:
        print("⚠️ 控制中心沒有 YouTube URL。")
        return 0

    try:
        meta = extract_metadata(
            first_url,
            Path("/kaggle/working/translate-system-doctor"),
        )
        ok("YouTube Cookies", meta.get("title", ""))
        ok("講師偵測", meta.get("lecturer", ""))
    except Exception as exc:
        fail("YouTube Cookies", exc)
        return 4

    print("\n🎉 Doctor 全部通過，可以開始 YouTube→ASR。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
