import shutil
import urllib.request
import zipfile
from pathlib import Path

DENO_MARKER = Path("/kaggle/working/deno_path.txt")
DENO_DIR = Path("/kaggle/working/deno-bin")
DENO_BIN = DENO_DIR / "deno"
DENO_URL = "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip"


def usable(path):
    try:
        import subprocess
        r = subprocess.run(
            [str(path), "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=20,
        )
        if r.returncode == 0:
            first = (r.stdout or "").splitlines()[0] if r.stdout else "deno"
            print(f"[JS] Deno ready: {path} / {first}", flush=True)
            return True
    except Exception:
        pass
    return False


def main():
    system = shutil.which("deno")
    if system and usable(system):
        DENO_MARKER.write_text(str(system) + "\n", encoding="utf-8")
        return 0

    if DENO_BIN.exists() and usable(DENO_BIN):
        DENO_MARKER.write_text(str(DENO_BIN) + "\n", encoding="utf-8")
        return 0

    print("[JS] 下載輕量 Deno runtime；不安裝 Chromium。", flush=True)
    DENO_DIR.mkdir(parents=True, exist_ok=True)
    archive = DENO_DIR / "deno.zip"
    urllib.request.urlretrieve(DENO_URL, archive)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(DENO_DIR)
    DENO_BIN.chmod(0o755)
    try:
        archive.unlink()
    except OSError:
        pass

    if not usable(DENO_BIN):
        raise RuntimeError("Deno 安裝完成但無法執行")

    DENO_MARKER.write_text(str(DENO_BIN) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
