import argparse
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path


REQUIRED_BRIDGE_PROTOCOL = 4


MACHINE_STAGES = {
    "zh",
    "metadata",
    "asr",
    "polish",
    "vernacular",
    "en",
    "multi",
    "tts",
    "finish",
    "cc",
    "batch",
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

    protocol = int(payload.get("bridge_protocol") or 0)
    if protocol < REQUIRED_BRIDGE_PROTOCOL:
        raise RuntimeError(
            "Apps Script Bridge 版本過舊：live="
            + str(protocol)
            + "，required="
            + str(REQUIRED_BRIDGE_PROTOCOL)
            + "。請重新部署 bridge/apps-script/Code.gs 後再執行。"
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


def require_gpu_runtime(stage: str):
    """Formal Kaggle jobs must use a real CUDA GPU; never silently fall back to CPU."""
    os.environ["SOULKEY_REQUIRE_GPU"] = "1"
    os.environ.setdefault("CUDA_DEVICE_ORDER", "PCI_BUS_ID")

    print("[GPU] 正式工作要求真實 CUDA GPU；開始硬體檢查。", flush=True)

    smi = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total",
            "--format=csv,noheader",
        ],
        text=True,
        capture_output=True,
    )
    if smi.returncode == 0:
        gpu_lines = [x.strip() for x in smi.stdout.splitlines() if x.strip()]
        print(f"[GPU] nvidia-smi: {gpu_lines}", flush=True)
    else:
        gpu_lines = []
        print(f"[GPU] nvidia-smi 不可用：{smi.stderr.strip()}", flush=True)

    import torch
    import ctranslate2

    torch_ok = bool(torch.cuda.is_available())
    torch_count = int(torch.cuda.device_count()) if torch_ok else 0
    torch_names = [
        torch.cuda.get_device_name(i)
        for i in range(torch_count)
    ] if torch_ok else []

    try:
        ct2_count = int(ctranslate2.get_cuda_device_count())
    except Exception as exc:
        print(
            f"[GPU] CTranslate2 CUDA 偵測失敗：{type(exc).__name__}: {exc}",
            flush=True,
        )
        ct2_count = 0

    print(
        f"[GPU] torch={torch.__version__}; "
        f"torch.cuda.is_available={torch_ok}; "
        f"torch_devices={torch_names}; "
        f"ctranslate2_cuda_devices={ct2_count}",
        flush=True,
    )

    needs_ct2 = stage in {"zh", "metadata", "asr", "batch"}
    needs_torch = stage in {
        "zh", "metadata", "polish", "vernacular", "en", "multi", "tts", "finish", "batch"
    }

    failures = []
    if not gpu_lines:
        failures.append("nvidia-smi 看不到 GPU")
    if needs_ct2 and ct2_count < 1:
        failures.append("CTranslate2 看不到 CUDA GPU")
    if needs_torch and not torch_ok:
        failures.append("PyTorch 看不到 CUDA GPU")

    if failures:
        raise RuntimeError(
            "GPU_REQUIRED_BUT_UNAVAILABLE: "
            + "；".join(failures)
            + "。本次工作直接停止，避免用 CPU 浪費 1~2 小時。"
        )

    print("[GPU] GPU 驗證通過，後續禁止 CPU fallback。", flush=True)


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
        os.environ["SOULKEY_BRIDGE_URL"] = args.bridge_url
        os.environ["SOULKEY_RUNTIME_NONCE"] = args.runtime_nonce

        gemini_api_key = str(runtime.get("gemini_api_key") or "").strip()
        needs_gemini = (
            args.stage in {
                "zh", "polish", "vernacular", "en", "multi", "batch"
            }
            or (
                args.stage == "finish"
                and bool(args.langs.strip())
            )
        )
        if gemini_api_key:
            os.environ["GEMINI_API_KEY"] = gemini_api_key
            print("[RUNTIME] Gemini API Key：Apps Script 已提供", flush=True)
        elif needs_gemini and not (
            args.stage == "en" and args.lang == "cc-refresh"
        ):
            raise RuntimeError(
                "Apps Script 尚未設定 GEMINI_API_KEY；"
                "請在 Script Properties 新增後重新部署 Web App。"
            )

        cookies = str(runtime.get("youtube_cookies_b64") or "").strip()
        if cookies:
            os.environ["YOUTUBE_COOKIES_B64"] = cookies
            print("[RUNTIME] YouTube Cookies：Apps Script 已提供", flush=True)
        else:
            print(
                "[RUNTIME] YouTube Cookies：未設定；"
                "使用 guest PO token / anonymous clients，必要時再走 Gemini source fallback。",
                flush=True,
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
            print("[BOOT] SoulKey 已由 Kaggle bootstrap 同步，略過第二次 git pull。", flush=True)

        gemini_only_stages = {
            "polish", "vernacular", "en", "multi"
        }
        finish_needs_audio = (
            args.stage == "finish"
            and bool(args.lang.strip())
        )
        requirements_file = (
            system_dir / "requirements-gemini.txt"
            if (
                args.stage in gemini_only_stages
                and not (args.stage == "en" and args.lang == "cc-refresh")
            )
            or (
                args.stage == "finish"
                and not finish_needs_audio
            )
            else system_dir / "requirements.txt"
        )
        run([
            sys.executable, "-m", "pip", "install",
            "--disable-pip-version-check", "-q",
            "-r", str(requirements_file),
        ])

        def prepare_youtube_runtime():
            print(
                "[YouTube] 準備 Deno + EJS + bgutil Subs POT + WPC runtime。",
                flush=True,
            )
            run([sys.executable, str(system_dir / "setup_js_runtime.py")])
            run([sys.executable, str(system_dir / "prepare_youtube_js.py")])
            run([sys.executable, str(system_dir / "setup_youtube_runtime.py")])
            run([sys.executable, str(system_dir / "setup_wpc_provider.py")])

        def run_taiwan_breeze_asr():
            print(
                "[ASR] Taiwan-Breeze 為正式主 ASR；"
                "使用本地 Kaggle GPU 產生繁中逐字稿。",
                flush=True,
            )
            require_gpu_runtime("asr")
            prepare_youtube_runtime()
            prepare_asr_runtime()
            run([
                sys.executable, str(system_dir / "runner.py"),
                "--task-id", args.task_id,
                "--stage", "asr",
                "--max-tasks", "1",
                "--force-asr",
            ])

        def run_gemini_source_fallback():
            if not gemini_api_key:
                raise RuntimeError(
                    "Taiwan-Breeze ASR 失敗，且沒有 GEMINI_API_KEY 可作來源備援。"
                )
            print(
                "[ASR] Taiwan-Breeze 失敗；"
                "改用 Gemini YouTube understanding 作來源備援。",
                flush=True,
            )
            run([
                sys.executable, str(system_dir / "gemini_source_runner.py"),
                "--task-id", args.task_id,
                "--force",
            ])

        if args.stage == "cc" or (
            args.stage == "en" and args.lang == "cc-refresh"
        ):
            prepare_youtube_runtime()

        if args.stage == "zh":
            try:
                run_taiwan_breeze_asr()
            except Exception as exc:
                print(
                    f"[ASR] Taiwan-Breeze 主流程失敗："
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )
                run_gemini_source_fallback()

            run([
                sys.executable,
                str(system_dir / "gemini_text_production_runner.py"),
                "--task-id", args.task_id,
                "--stage", "polish",
            ])
            report(
                args.bridge_url,
                args.runtime_nonce,
                "needs_review",
                "Taiwan-Breeze逐字稿 + Gemini校稿完成，待人工中文定稿",
            )
            cmd = None

        elif args.stage == "metadata":
            cmd = [
                sys.executable, str(system_dir / "runner.py"),
                "--task-id", args.task_id,
                "--stage", "metadata",
                "--max-tasks", "1",
                "--force-metadata",
            ]

        elif args.stage == "asr":
            try:
                run_taiwan_breeze_asr()
            except subprocess.CalledProcessError:
                run_gemini_source_fallback()
            cmd = None

        elif args.stage == "polish":
            cmd = [
                sys.executable,
                str(system_dir / "gemini_text_production_runner.py"),
                "--task-id", args.task_id,
                "--stage", "polish",
            ]

        elif args.stage == "vernacular":
            cmd = [
                sys.executable,
                str(system_dir / "gemini_text_production_runner.py"),
                "--task-id", args.task_id,
                "--stage", "vernacular",
            ]

        elif args.stage == "cc":
            cmd = [
                sys.executable, str(system_dir / "cc_runner.py"),
                "--task-id", args.task_id,
            ]

        elif args.stage == "en" and args.lang == "cc-refresh":
            print("[CC] 使用相容模式：stage=en / lang=cc-refresh", flush=True)
            cmd = [
                sys.executable, str(system_dir / "cc_runner.py"),
                "--task-id", args.task_id,
            ]

        elif args.stage == "en":
            cmd = [
                sys.executable,
                str(system_dir / "gemini_text_production_runner.py"),
                "--task-id", args.task_id,
                "--stage", "en",
            ]

        elif args.stage == "multi":
            translate_langs = ",".join(
                x.strip() for x in args.langs.split(",") if x.strip()
            )
            if not translate_langs:
                raise RuntimeError("各國語言翻譯沒有指定任何 AI 語言")
            cmd = [
                sys.executable,
                str(system_dir / "gemini_multi_production_runner.py"),
                "--task-id", args.task_id,
                "--langs", translate_langs,
            ]

        elif args.stage == "tts":
            langs = ",".join(
                x.strip() for x in args.langs.split(",") if x.strip()
            )
            if not langs:
                raise RuntimeError("TTS 沒有指定任何語言")
            require_gpu_runtime("tts")
            cmd = [
                sys.executable,
                str(system_dir / "tts_runner.py"),
                "--task-id", args.task_id,
                "--langs", langs,
                "--max-tasks", "1",
            ]

        elif args.stage == "batch":
            task_ids = ",".join(
                x.strip() for x in args.langs.split(",") if x.strip()
            )
            if not task_ids:
                task_ids = args.task_id
            print(
                "[BATCH] 使用 Studio Bridge runtime 執行：" + task_ids,
                flush=True,
            )
            require_gpu_runtime("batch")
            run([
                sys.executable,
                str(system_dir / "batch_full_runner.py"),
                "--task-ids", task_ids,
            ])
            report(
                args.bridge_url,
                args.runtime_nonce,
                "done",
                "批次全流程完成：" + task_ids,
            )
            cmd = None

        elif args.stage == "finish":
            translate_langs = ",".join(
                x.strip() for x in args.langs.split(",") if x.strip()
            )
            audio_langs = ",".join(
                x.strip() for x in args.lang.split(",") if x.strip()
            )

            if translate_langs:
                run([
                    sys.executable,
                    str(system_dir / "gemini_multi_production_runner.py"),
                    "--task-id", args.task_id,
                    "--langs", translate_langs,
                ])

            if audio_langs:
                require_gpu_runtime("tts")
                run([
                    sys.executable,
                    str(system_dir / "tts_runner.py"),
                    "--task-id", args.task_id,
                    "--langs", audio_langs,
                    "--max-tasks", "1",
                ])

            if not translate_langs and not audio_langs:
                print("[FINISH] 沒有額外翻譯或音檔；中英 Final 已完成。", flush=True)

            report(
                args.bridge_url,
                args.runtime_nonce,
                "done",
                "完成快速上線流程；Gemini翻譯="
                + (translate_langs or "無")
                + "；音檔="
                + (audio_langs or "無"),
            )
            cmd = None

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
