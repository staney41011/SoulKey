import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

DENO_MARKER = Path("/kaggle/working/deno_path.txt")
DENO_DIR = Path("/kaggle/working/deno-bin")
DENO_BIN = DENO_DIR / "deno"


def _usable_deno(path):
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        result = subprocess.run(
            [str(p), "--version"],
            text=True,
            capture_output=True,
            check=True,
            timeout=15,
        )
        first = (result.stdout or "").splitlines()[0] if result.stdout else ""
        print(f"[YOUTUBE-JS] 使用 Deno：{p} / {first}", flush=True)
        return str(p)
    except Exception:
        return None


def main():
    # Prefer any Deno already available in the Kaggle image.
    existing = _usable_deno(shutil.which("deno"))
    if existing:
        DENO_MARKER.write_text(existing + "\n", encoding="utf-8")
        return 0

    # Reuse this session's downloaded Deno when present.
    existing = _usable_deno(DENO_BIN)
    if existing:
        DENO_MARKER.write_text(existing + "\n", encoding="utf-8")
        return 0

    DENO_DIR.mkdir(parents=True, exist_ok=True)
    archive = DENO_DIR / "deno.zip"
    url = (
        "https://github.com/denoland/deno/releases/latest/download/"
        "deno-x86_64-unknown-linux-gnu.zip"
    )

    print("[YOUTUBE-JS] 下載 Deno；不安裝 Chromium/WPC。", flush=True)
    urllib.request.urlretrieve(url, archive)
    with zipfile.ZipFile(archive, "r") as zf:
        zf.extractall(DENO_DIR)
    archive.unlink(missing_ok=True)
    DENO_BIN.chmod(0o755)

    deno = _usable_deno(DENO_BIN)
    if not deno:
        raise RuntimeError("Deno 安裝完成但無法執行")

    DENO_MARKER.write_text(deno + "\n", encoding="utf-8")
    print(f"[YOUTUBE-JS] Deno marker：{DENO_MARKER}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
