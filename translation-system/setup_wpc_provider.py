import os
import shutil
import subprocess
from pathlib import Path

BROWSER_MARKER = Path("/kaggle/working/wpc_browser_path.txt")


def run(cmd, check=True):
    print("$", " ".join(map(str, cmd)))
    return subprocess.run(list(map(str, cmd)), check=check)


def find_browser():
    candidates = [
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(Path(candidate))
    return None


def install_browser():
    browser = find_browser()
    if browser:
        return browser

    print("找不到 Chrome/Chromium，嘗試用 apt 安裝 Chromium。")
    run(["apt-get", "update"])
    result = run(
        ["apt-get", "install", "-y", "chromium"],
        check=False,
    )
    if result.returncode != 0:
        result = run(
            ["apt-get", "install", "-y", "chromium-browser"],
            check=False,
        )

    browser = find_browser()
    if not browser:
        raise RuntimeError(
            "Chromium 自動安裝失敗。請回傳這一格輸出，我們再切換 Chrome for Testing。"
        )
    return browser


def main():
    # bgutil 先移除，避免多個 provider 同時競爭。
    run([
        "python", "-m", "pip", "uninstall", "-y",
        "bgutil-ytdlp-pot-provider",
    ], check=False)

    run([
        "python", "-m", "pip", "install", "-U",
        "yt-dlp", "yt-dlp-getpot-wpc",
    ])

    browser = install_browser()
    BROWSER_MARKER.write_text(browser + "\n", encoding="utf-8")

    print("\n✅ WPC PO Token Provider 準備完成")
    print(f"Browser: {browser}")
    print(f"Marker: {BROWSER_MARKER}")
    print("這個方案不需要 YouTube cookies。")


if __name__ == "__main__":
    main()
