import os
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path


DENO_DIR = Path("/kaggle/working/deno-bin")
DENO_BIN = DENO_DIR / "deno"
DENO_MARKER = Path("/kaggle/working/deno_path.txt")


def main():
    if DENO_BIN.exists():
        print(f"[YOUTUBE-RUNTIME] Deno 已存在：{DENO_BIN}", flush=True)
    else:
        DENO_DIR.mkdir(parents=True, exist_ok=True)
        archive = DENO_DIR / "deno.zip"
        url = "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip"
        print("[YOUTUBE-RUNTIME] 下載 Deno（yt-dlp EJS challenge runtime）...", flush=True)
        urllib.request.urlretrieve(url, archive)
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(DENO_DIR)
        try:
            archive.unlink()
        except Exception:
            pass
        DENO_BIN.chmod(0o755)

    result = subprocess.run(
        [str(DENO_BIN), "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    first = (result.stdout or result.stderr or "").splitlines()[0]
    print(f"[YOUTUBE-RUNTIME] {first}", flush=True)

    DENO_MARKER.write_text(str(DENO_BIN) + "\n", encoding="utf-8")
    print(f"[YOUTUBE-RUNTIME] marker={DENO_MARKER}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
