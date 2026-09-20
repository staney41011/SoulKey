import base64
import os
import subprocess
import sys
from pathlib import Path

from google_io import get_secret

URL = "https://youtu.be/MKP_YSp96nI"
WORKDIR = Path("/kaggle/working/translate-system-youtube-debug")
COOKIE_PATH = WORKDIR / "youtube_cookies.txt"
MARKER = Path("/kaggle/working/wpc_browser_path.txt")


def main():
    WORKDIR.mkdir(parents=True, exist_ok=True)

    cookies_b64 = get_secret("YOUTUBE_COOKIES_B64", required=True)
    try:
        COOKIE_PATH.write_bytes(base64.b64decode(cookies_b64))
    except Exception as exc:
        print(f"❌ Cookies Base64 解碼失敗：{exc}")
        return 2

    if MARKER.exists():
        browser = MARKER.read_text(encoding="utf-8").strip()
    else:
        browser = "/usr/bin/chromium-browser"

    print("=" * 76)
    print("YouTube / WPC Diagnostic")
    print("=" * 76)
    print(f"Python: {sys.version.split()[0]}")
    print(f"Browser: {browser}")
    print(f"Browser exists: {Path(browser).exists()}")
    print("Cookies: 已載入（內容不顯示）")
    print(f"URL: {URL}")
    print("")
    print("接下來只列出 formats，不下載影片。")
    print("請特別看這幾行：")
    print("  [youtube] [pot] PO Token Providers: ...")
    print("  Fetching PO Token / PO Token...")
    print("  Available formats")
    print("=" * 76)

    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "-v",
        "--no-playlist",
        "--socket-timeout",
        "20",
        "--retries",
        "1",
        "--extractor-retries",
        "1",
        "--cookies",
        str(COOKIE_PATH),
        "--extractor-args",
        "youtube:player_client=mweb;fetch_pot=always",
        "--extractor-args",
        f"youtubepot-wpc:browser_path={browser}",
        "--list-formats",
        URL,
    ]

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(WORKDIR),
            timeout=120,
        )
        print("")
        print("=" * 76)
        print(f"yt-dlp exit code: {proc.returncode}")
        if proc.returncode == 0:
            print("✅ WPC/mweb 診斷指令完成。")
        else:
            print("⚠️ yt-dlp 有錯誤；上方 verbose log 就是下一步判斷依據。")
        return proc.returncode
    except subprocess.TimeoutExpired:
        print("")
        print("❌ 120 秒 timeout：WPC/Chromium 在 Kaggle 卡住。")
        return 124
    finally:
        try:
            COOKIE_PATH.unlink(missing_ok=True)
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
