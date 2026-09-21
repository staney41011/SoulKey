import os
import shutil
import stat
import urllib.request
import zipfile
from pathlib import Path

DENO_DIR = Path("/kaggle/working/deno-bin")
DENO_BIN = DENO_DIR / "deno"
DENO_MARKER = Path("/kaggle/working/deno_path.txt")


def main():
    existing = shutil.which("deno")
    if existing:
        DENO_MARKER.write_text(existing + "\n", encoding="utf-8")
        print(f"[YouTube-JS] 使用既有 Deno：{existing}", flush=True)
        return 0

    if DENO_BIN.exists():
        DENO_MARKER.write_text(str(DENO_BIN) + "\n", encoding="utf-8")
        print(f"[YouTube-JS] 使用已下載 Deno：{DENO_BIN}", flush=True)
        return 0

    DENO_DIR.mkdir(parents=True, exist_ok=True)
    archive = DENO_DIR / "deno.zip"
    url = "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip"

    print("[YouTube-JS] 下載輕量 Deno runtime（不安裝 Chromium/WPC）...", flush=True)
    urllib.request.urlretrieve(url, archive)

    with zipfile.ZipFile(archive, "r") as zf:
        zf.extract("deno", DENO_DIR)

    mode = DENO_BIN.stat().st_mode
    DENO_BIN.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    DENO_MARKER.write_text(str(DENO_BIN) + "\n", encoding="utf-8")

    version = os.popen(f'"{DENO_BIN}" --version').read().splitlines()
    print(f"[YouTube-JS] Deno ready：{version[0] if version else DENO_BIN}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
