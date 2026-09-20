import re
import shutil
import subprocess
from pathlib import Path

REPO_URL = "https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git"
VERSION = "2.0.0"
DEST = Path("/kaggle/working/bgutil-ytdlp-pot-provider")
SERVER = DEST / "server"
GENERATE = SERVER / "build" / "generate_once.js"


def run(cmd, cwd=None):
    print("$", " ".join(map(str, cmd)))
    subprocess.run(list(map(str, cmd)), cwd=cwd, check=True)


def node_major():
    node = shutil.which("node")
    if not node:
        raise RuntimeError("找不到 Node.js。PO Token Provider 需要 Node.js >= 22。")
    out = subprocess.check_output([node, "--version"], text=True).strip()
    match = re.search(r"v?(\d+)", out)
    if not match:
        raise RuntimeError(f"無法判斷 Node.js 版本：{out}")
    major = int(match.group(1))
    print(f"Node.js: {out}")
    return major


def main():
    major = node_major()
    if major < 22:
        raise RuntimeError(
            f"目前 Node.js {major}，bgutil 2.0.0 需要 Node.js >= 22。"
        )

    if DEST.exists():
        shutil.rmtree(DEST)

    run([
        "git", "clone",
        "--depth", "1",
        "--branch", VERSION,
        REPO_URL,
        DEST,
    ])

    run(["npm", "ci"], cwd=SERVER)
    run(["npx", "tsc"], cwd=SERVER)

    if not GENERATE.exists():
        raise RuntimeError(f"編譯完成但找不到：{GENERATE}")

    print("\n✅ PO Token Provider 準備完成")
    print(f"Provider: {DEST}")
    print(f"Script: {GENERATE}")
    print("\n之後 yt-dlp 會自動用 mweb + bgutil PO Token。")


if __name__ == "__main__":
    main()
