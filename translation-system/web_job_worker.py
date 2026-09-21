import argparse
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path


MACHINE_STAGES = {
    "zh",
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
    cmd = list(map(str, cmd))
    if cmd and Path(cmd[0]).name.startswith("python") and "-u" not in cmd[1:2]:
        cmd.insert(1, "-u")
    print("$", " ".join(cmd), flush=True)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def prepare_asr_runtime():
    root = Path("/kaggle/input")
    matches = []
    if root.exists():
        try:
            matches = list(root.rglob("taiwan-breeze-asr-26/model.bin"))
        except Exception as exc:
            print(f"[ASR-PREFLIGHT] 掃描 /kaggle/input 失敗：{type(exc).__name__}: {exc}", flush=True)

    if matches:
        model_dir = matches[0].parent
        os.environ["ASR_MODEL_PATH"] = str(model_dir)
        print(f"[ASR-PREFLIGHT] 使用永久 ASR 模型：{model_dir}", flush=True)
        return str(model_dir)

    print("[ASR-PREFLIGHT] /kaggle/input 找不到永久 ASR 模型。", flush=True)
    try:
        top = sorted(str(p) for p in root.glob("*"))[:40] if root.exists() else []
        print("[ASR-PREFLIGHT] input roots:", top, flush=True)
    except Exception:
        pass

    # 明確準備到 working，避免 WhisperModel 在載入期間隱式下載造成難以診斷的 Kernel ERROR。
    run([sys.executable, str(Path("/kaggle/working/SoulKey/translation-system/prepare_model.py"))])
    model_dir = Path("/kaggle/working/persistent-model/taiwan-breeze-asr-26")
    if not (model_dir / "model.bin").exists():
        raise RuntimeError("ASR 模型準備完成後仍找不到 model.bin")
    os.environ["ASR_MODEL_PATH"] = str(model_dir)
    print(f"[ASR-PREFLIGHT] 使用本次下載 ASR 模型：{model_dir}", flush=True)
    return str(model_dir)


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
            print("[RUNTIME] YouTube Cookies：Apps Script 已提供", flush=True)
        else:
            print("[RUNTIME] YouTube Cookies：未設定", flush=True)
            if args.stage in {"zh", "metadata", "asr"}:
                raise RuntimeError(
                    "YouTube Cookies 尚未設定在 Apps Script Script Properties；"
                    "Kaggle API 觸發不會可靠保留 Notebook Secret。"
                )

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

        if args.stage in {"zh", "metadata", "asr"}:
            run([sys.executable, str(system_dir / "setup_wpc_provider.py")])

        if args.stage in {"zh", "metadata"}:
            prepare_asr_runtime()
            run([
                sys.executable, str(system_dir / "runner.py"),
                "--task-id", args.task_id,
                "--stage", "metadata",
                "--max-tasks", "1",
                "--force-metadata",
            ])
            run([
                sys.executable, str(system_dir / "runner.py"),
                "--task-id", args.task_id,
                "--stage", "asr",
                "--max-tasks", "1",
                "--force-asr",
            ])
            run([
                sys.executable, str(system_dir / "polish_runner.py"),
                "--task-id", args.task_id,
                "--max-tasks", "1",
                "--force",
            ])
            if args.stage == "zh":
                report(
                    args.bridge_url,
                    args.runtime_nonce,
                    "needs_review",
                    "中文逐字稿與 AI 中文校稿完成，待人工中文定稿",
                )
            cmd = None
        elif args.stage == "asr":
            prepare_asr_runtime()
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

        if cmd:
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
