import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

BROWSER_MARKER = Path("/kaggle/working/wpc_browser_path.txt")
DENO_MARKER = Path("/kaggle/working/deno_path.txt")
DENO_DIR = Path("/kaggle/working/deno-bin")
DENO_BIN = DENO_DIR / "deno"


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
    result = run(["apt-get", "install", "-y", "chromium"], check=False)
    if result.returncode != 0:
        run(["apt-get", "install", "-y", "chromium-browser"], check=False)

    browser = find_browser()
    if not browser:
        raise RuntimeError("Chromium 自動安裝失敗。")
    return browser


def install_deno():
    if DENO_BIN.exists():
        return str(DENO_BIN)

    DENO_DIR.mkdir(parents=True, exist_ok=True)
    archive = DENO_DIR / "deno.zip"
    url = "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip"

    print("下載 Deno（yt-dlp 官方建議的 JS runtime）...")
    urllib.request.urlretrieve(url, archive)
    with zipfile.ZipFile(archive, "r") as zf:
        zf.extractall(DENO_DIR)
    archive.unlink(missing_ok=True)
    DENO_BIN.chmod(0o755)

    result = subprocess.run(
        [str(DENO_BIN), "--version"],
        text=True,
        capture_output=True,
        check=True,
    )
    print(result.stdout.strip())
    return str(DENO_BIN)


def patch_installed_wpc():
    import yt_dlp_plugins.extractor.getpot_wpc as wpc

    path = Path(wpc.__file__)
    text = path.read_text(encoding="utf-8")

    old = """return nodriver.core.config.Config(
            headless=False,
            browser_executable_path=browser_executable_path,
            browser_args=browser_args
        )"""

    new = """return nodriver.core.config.Config(
            headless=True,
            browser_executable_path=browser_executable_path,
            browser_args=browser_args,
            sandbox=False,
        )"""

    if new in text:
        print("✅ WPC Kaggle patch 已存在")
        return

    if old not in text:
        print("⚠️ WPC 原始碼版本不同，略過檔案 patch；youtube_io 仍有 runtime patch。")
        return

    path.write_text(text.replace(old, new), encoding="utf-8")
    print(f"✅ WPC 已修正為 headless + no-sandbox：{path}")


def main():
    run([
        sys.executable, "-m", "pip", "uninstall", "-y",
        "bgutil-ytdlp-pot-provider",
    ], check=False)

    run([
        sys.executable, "-m", "pip", "install", "-U",
        "yt-dlp[default]", "yt-dlp-getpot-wpc",
    ])

    browser = install_browser()
    BROWSER_MARKER.write_text(browser + "\n", encoding="utf-8")

    deno = install_deno()
    DENO_MARKER.write_text(deno + "\n", encoding="utf-8")

    patch_installed_wpc()

    print("\n✅ YouTube Runtime 準備完成")
    print(f"Browser: {browser}")
    print("Browser mode: headless + no-sandbox")
    print(f"Deno: {deno}")
    print(f"Browser marker: {BROWSER_MARKER}")
    print(f"Deno marker: {DENO_MARKER}")


if __name__ == "__main__":
    main()
