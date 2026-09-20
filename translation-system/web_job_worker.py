import argparse
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path


MACHINE_STAGES = {
    "metadata",
    "asr",
    "polish",
    "vernacular",
    "en",
    "multi",
    "tts",
}


def fetch_runtime(bridge_url: str, nonce: str):
    query = urllib.parse.urlencode({
        "action": "worker_runtime",
        "nonce": nonce,
        "_t": "1",
    })
    url = bridge_url + ("&" if "?" in bridge_url else "?") + query
    with urllib.request.urlopen(url, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if not payload.get("ok"):
        raise RuntimeError(
            "SoulKey runtime credential request failed: "
            + str(payload.get("message") or payload.get("error") or payload)
        )
    return payload


def report(bridge_url: str, nonce: str, status: str, message: str):
    data = urllib.parse.urlencode({
        "action": "worker_report",
        "nonce": nonce,
        "status": status,
        "message": message[:1200],
    }).encode("utf-8")
    try:
        urllib.request.urlopen(
            urllib.request.Request(bridge_url, data=data, method="POST"),
            timeout=20,
        ).read()
    except Exception as exc:
        print(f"[WEB-WORKER] 狀態回報失敗：{type(exc).__name__}: {exc}")


def run(cmd, cwd=None):
    print("$", " ".join(map(str, cmd)), flush=True)
    subprocess.run(list(map(str, cmd)), cwd=cwd, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--stage", required=True, choices=sorted(MACHINE_STAGES))
    parser.add_argument("--lang", default="")
    parser.add_argument("--langs", default="")
    parser.add_argument("--bridge-url", required=True)
    parser.add_argument("--runtime-nonce", required=True)
    args = parser.parse_args()

    repo = Path("/kaggle/working/SoulKey")
    system_dir = repo / "translation-system"

    try:
        runtime = fetch_runtime(args.bridge_url, args.runtime_nonce)

        google_token = str(runtime.get("google_access_token") or "").strip()
        if not google_token:
            raise RuntimeError("Bridge 沒有提供 Google access token")

        os.environ["GOOGLE_ACCESS_TOKEN"] = google_token

        cookies = str(runtime.get("youtube_cookies_b64") or "").strip()
        if cookies:
            os.environ["YOUTUBE_COOKIES_B64"] = cookies

        report(
            args.bridge_url,
            args.runtime_nonce,
            "running",
            f"Kaggle Web Worker 開始執行 {args.stage}",
        )

        if not repo.exists():
            run([
                "git", "clone", "--depth", "1",
                "https://github.com/staney41011/SoulKey.git",
                str(repo),
            ])
        else:
            run(["git", "-C", str(repo), "pull", "--ff-only"])

        run([
            sys.executable, "-m", "pip", "install",
            "--disable-pip-version-check", "-q",
            "-r", str(system_dir / "requirements.txt"),
        ])

        if args.stage in {"metadata", "asr"}:
            run([sys.executable, str(system_dir / "setup_wpc_provider.py")])

        if args.stage == "metadata":
            cmd = [
                sys.executable, str(system_dir / "runner.py"),
                "--task-id", args.task_id,
                "--stage", "metadata",
                "--max-tasks", "1",
                "--force-metadata",
            ]
        elif args.stage == "asr":
            cmd = [
                sys.executable, str(system_dir / "runner.py"),
                "--task-id", args.task_id,
                "--stage", "asr",
                "--max-tasks", "1",
                "--force-asr",
            ]
        elif args.stage == "polish":
            cmd = [
                sys.executable, str(system_dir / "polish_runner.py"),
                "--task-id", args.task_id,
                "--max-tasks", "1",
                "--force",
            ]
        elif args.stage == "vernacular":
            cmd = [
                sys.executable, str(system_dir / "translate_runner.py"),
                "--task-id", args.task_id,
                "--stage", "modernize",
                "--max-tasks", "1",
                "--force",
            ]
        elif args.stage == "en":
            cmd = [
                sys.executable, str(system_dir / "translate_runner.py"),
                "--task-id", args.task_id,
                "--stage", "translate",
                "--lang", "en",
                "--max-tasks", "1",
                "--force",
            ]
        elif args.stage == "multi":
            langs = ",".join(
                x.strip() for x in args.langs.split(",") if x.strip()
            )
            if not langs:
                raise RuntimeError("各國語言翻譯沒有指定任何 AI 語言")
            cmd = [
                sys.executable, str(system_dir / "translate_runner.py"),
                "--task-id", args.task_id,
                "--stage", "translate-targets",
                "--langs", langs,
                "--max-tasks", "1",
                "--force",
            ]
        elif args.stage == "tts":
            langs = ",".join(
                x.strip() for x in args.langs.split(",") if x.strip()
            )
            if not langs:
                raise RuntimeError("TTS 沒有指定任何語言")
            cmd = [
                sys.executable, str(system_dir / "tts_runner.py"),
                "--task-id", args.task_id,
                "--langs", langs,
                "--max-tasks", "1",
                "--force",
            ]
        else:
            raise RuntimeError("不支援的 stage")

        run(cmd)
        print("[WEB-WORKER] 正式 Stage 執行完成。")

    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        print("[WEB-WORKER ERROR]", message, file=sys.stderr)
        report(args.bridge_url, args.runtime_nonce, "error", message)
        raise

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
