import argparse
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path


REQUIRED_BRIDGE_PROTOCOL = 9


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
    # Apps Script can occasionally cold-start or take longer than 30 seconds.
    # A transient Bridge timeout must not fail an otherwise valid Kaggle job
    # before YouTube/ASR has even started.
    waits = [0, 5, 15, 30]
    last_exc = None

    for attempt, wait_seconds in enumerate(waits, start=1):
        if wait_seconds:
            print(
                f"[BRIDGE] runtime retry {attempt}/{len(waits)} "
                f"after {wait_seconds}s",
                flush=True,
            )
            time.sleep(wait_seconds)

        query = urllib.parse.urlencode({
            "action": "worker_runtime",
            "nonce": nonce,
            "_t": str(int(time.time())),
        })
        url = bridge_url + ("&" if "?" in bridge_url else "?") + query

        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            # HTTPError and URLError messages can contain the full request
            # URL, including the bearer runtime nonce in its query string.
            # Keep the class only; never log the exception or the URL.
            last_exc = type(exc).__name__
            print(
                f"[BRIDGE] runtime request {attempt}/{len(waits)} failed: "
                f"{last_exc}",
                flush=True,
            )
            continue

        if not payload.get("ok"):
            # Print only a short, server-defined reason code. The raw Bridge
            # response could include credentials and must never hit CI logs.
            code = str(payload.get("error") or "runtime_rejected")
            if code not in {"invalid_or_expired_nonce", "unauthorized",
                            "server_not_configured", "runtime_rejected"}:
                code = "runtime_rejected"
            raise RuntimeError("SoulKey runtime credential request failed: " + code)

        protocol = int(payload.get("bridge_protocol") or 0)
        if protocol < REQUIRED_BRIDGE_PROTOCOL:
            raise RuntimeError(
                "Apps Script Bridge 版本過舊：live="
                + str(protocol)
                + "，required="
                + str(REQUIRED_BRIDGE_PROTOCOL)
                + "。請重新部署 bridge/apps-script/Code.gs 後再執行。"
            )

        if attempt > 1:
            print("[BRIDGE] runtime credential retry succeeded", flush=True)
        return payload

    raise RuntimeError(
        "SoulKey runtime credential request exhausted retries: "
        + (last_exc or "unknown_error")
    )


def seed_english_review_cache(bridge_url: str, nonce: str, task_id: str):
    """Fast-publish English/Chinese layout after a CC or AI English stage.

    A cache failure must never mark the successfully uploaded Drive transcript
    as failed. It can be seeded again on the next review opening.
    """
    data = urllib.parse.urlencode({
        "action": "worker_english_cache_seed",
        "nonce": nonce,
        "task_id": task_id,
    }).encode("utf-8")
    try:
        request = urllib.request.Request(bridge_url, data=data, method="POST")
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.loads(response.read().decode("utf-8"))
        if result.get("ok"):
            print("[EN-ALIGN] 1:1 Chinese Final / English review cache published", flush=True)
        else:
            print("[EN-ALIGN] cache deferred: " +
                  str(result.get("error") or result.get("message") or "unknown"),
                  flush=True)
    except Exception as exc:
        print("[EN-ALIGN] cache deferred: " +
              f"{type(exc).__name__}: {exc}", flush=True)


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


def run_verified_tts_job(cmd, retry_waits=(10,30),
                         refresh_credentials=None):
    """Fail closed: selected-language Drive MP3 verification is mandatory.

    tts_runner.py --strict-delivery:
      0: every selected language has a verified approved MP3;
      2: at least one language missing (resume just the missing languages);
      3: every language has audio, but >=1 is preview-only pending timing QA.
    Completed voices are skipped from their Drive manifests on subsequent runs.
    """
    for attempt in range(len(retry_waits)+1):
        try:
            if refresh_credentials is not None:
                refresh_credentials()
            run(cmd)
            print("[FINISH:AUDIO-VERIFIED] all selected Drive MP3 files present",
                  flush=True)
            return "done"
        except subprocess.CalledProcessError as exc:
            if exc.returncode==3:
                print("[FINISH:AUDIO-REVIEW] full natural MP3 available; "
                      "one or more languages need timing review",flush=True)
                return "needs_review"
            if attempt==len(retry_waits):
                raise RuntimeError(
                    "One or more selected MP3 files are still missing after "
                    f"{attempt+1} delivery attempts; check per-language "
                    "tts:<lang> status and Drive files"
                ) from exc
            wait_seconds=retry_waits[attempt]
            print("[FINISH:AUDIO-RETRY] incomplete audio delivery, "
                  f"attempt {attempt+2}/{len(retry_waits)+1}; "
                  f"resuming only missing files after {wait_seconds}s",
                  flush=True)
            time.sleep(wait_seconds)
    raise AssertionError("unreachable")


def refresh_worker_drive_credentials(bridge_url,nonce):
    # Google access tokens can expire during translation or 10-language TTS.
    # Each attempt gets a fresh Drive credential; never persist the token.
    fresh=fetch_runtime(bridge_url,nonce)
    token=str(fresh.get("google_access_token") or "").strip()
    if not token:
        raise RuntimeError("Bridge runtime failed to refresh Drive access token")
    os.environ["GOOGLE_ACCESS_TOKEN"]=token
    print("[FINISH:DRIVE] refreshed short-lived Google token",flush=True)


def run_checkpointed_multi(cmd, retry_waits=(15,40), refresh_credentials=None):
    """Resume checkpointed translation, refreshing Google credentials on retry."""
    for attempt in range(len(retry_waits)+1):
        try:
            if attempt and refresh_credentials:
                refresh_credentials()
            run(cmd)
            return
        except subprocess.CalledProcessError:
            if attempt==len(retry_waits):
                raise
            delay=retry_waits[attempt]
            print(f"[FINISH:MULTI-RETRY] pass {attempt+2}/"
                  f"{len(retry_waits)+1} after {delay}s; "
                  "resume source-matched Gemini checkpoint",flush=True)
            time.sleep(delay)


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
    if stage == "gemma4":
        # Gemma4 uses Transformers/PyTorch only; the Gemini-light requirements
        # intentionally do not install CTranslate2.
        ctranslate2 = None
    else:
        import ctranslate2

    torch_ok = bool(torch.cuda.is_available())
    torch_count = int(torch.cuda.device_count()) if torch_ok else 0
    torch_names = [
        torch.cuda.get_device_name(i)
        for i in range(torch_count)
    ] if torch_ok else []

    try:
        ct2_count = int(ctranslate2.get_cuda_device_count()) if ctranslate2 else 0
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
        "zh", "metadata", "polish", "vernacular", "en", "multi", "tts", "finish", "batch", "gemma4"
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

    # Kaggle loads the repo at /kaggle/working; GitHub Actions checks it out locally.
    repo = Path(os.environ.get("SOULKEY_REPO_DIR") or "/kaggle/working/SoulKey")
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
                "zh", "polish", "vernacular", "en", "multi", "tts", "batch"
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
            (args.stage == "en" and args.lang == "cc-refresh")
            or (args.stage == "tts" and args.task_id in {"P259-L01","P259-L02","P259-L03","P259-L04"})
            or (args.stage == "multi" and args.task_id in {"P259-L01","P259-L02","P259-L03","P259-L04"})
            or (args.stage == "finish" and args.task_id in {"P259-L01","P259-L02","P259-L03","P259-L04"})
        ):
            raise RuntimeError(
                "Apps Script 尚未設定 GEMINI_API_KEY；"
                "請在 Script Properties 新增後重新部署 Web App。"
            )

        nvidia_api_key = str(runtime.get("nvidia_api_key") or "").strip()
        if nvidia_api_key:
            os.environ["NVIDIA_API_KEY"] = nvidia_api_key
            print(
                "[RUNTIME] NVIDIA API Key：Apps Script 已提供；"
                "僅用於翻譯 QA 第二意見/備援。",
                flush=True,
            )
        else:
            print(
                "[RUNTIME] NVIDIA API Key：未設定；"
                "維持 Gemini-only 翻譯 QA，不影響主流程。",
                flush=True,
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
            f"SoulKey Worker 開始執行 {args.stage}",
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
                (args.stage in gemini_only_stages or args.stage == "tts")
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

        def run_polish_with_local_fallback():
            try:
                run([
                    sys.executable,
                    str(system_dir / "gemini_text_production_runner.py"),
                    "--task-id", args.task_id,
                    "--stage", "polish",
                ])
                return "Gemini"
            except subprocess.CalledProcessError as exc:
                print(
                    "[POLISH] Gemini 校稿失敗；"
                    "改用 Kaggle 本地 Qwen3-4B 校稿，不等待 API 額度。"
                    f" 原因={type(exc).__name__}: {exc}",
                    flush=True,
                )
                run([
                    sys.executable,
                    str(system_dir / "polish_runner.py"),
                    "--task-id", args.task_id,
                    "--max-tasks", "1",
                    "--force",
                ])
                return "Qwen3-4B local"

        def verify_asr_source_revision():
            """Require audio provenance before reusing an existing transcript."""
            from config import SPREADSHEET_ID, TASK_SHEET_RANGE
            from google_io import build_google_services, read_values
            from lesson_paths import resolve_lesson_folders
            from source_revision import verify_existing_asr
            from youtube_io import download_audio

            drive, sheets = build_google_services()
            rows = read_values(sheets, SPREADSHEET_ID, TASK_SHEET_RANGE)
            matching = [row for row in rows if row and str(row[0]).strip() == args.task_id]
            if not matching:
                raise RuntimeError("Control sheet task missing: " + args.task_id)
            row = matching[0]
            url = str(row[4] if len(row) > 4 else "").strip()
            if not url:
                raise RuntimeError("Control sheet task has no YouTube URL")

            folders = resolve_lesson_folders(drive, sheets, int(row[1]), str(row[2]))
            prepared = [False]

            def comparison_download(source_url, destination):
                if not prepared[0]:
                    prepare_youtube_runtime()
                    prepared[0] = True
                return download_audio(source_url, destination)

            reusable, reason = verify_existing_asr(
                drive, folders, url,
                Path("/kaggle/working/soulkey-source-verify") / args.task_id,
                comparison_download,
            )
            print("[SOURCE-REVISION] " + args.task_id +
                  " reusable=" + str(reusable) + " reason=" + reason, flush=True)
            if not reusable:
                raise RuntimeError("Source changed or cannot be verified: " + reason)

        def verify_zh_review_outputs(require_polish=True):
            """Treat success as real only if Drive has nonempty ASR and polish JSON.

            Earlier workers could announce needs_review after runners silently
            skipped a task absent from the sheet, leaving four blank editors.
            """
            from tempfile import TemporaryDirectory
            if str(system_dir) not in sys.path:
                sys.path.insert(0, str(system_dir))
            from config import SPREADSHEET_ID, TASK_SHEET_RANGE
            from google_io import (
                build_google_services, read_values, find_file, download_drive_file,
            )
            from lesson_paths import resolve_lesson_folders
            drive, sheets = build_google_services()
            raw_rows = read_values(sheets, SPREADSHEET_ID, TASK_SHEET_RANGE)
            matches = [
                row for row in raw_rows
                if row and str(row[0]).strip() == args.task_id
            ]
            if not matches:
                raise RuntimeError(
                    f"中文定稿前置驗收失敗：中央控制表不存在任務 {args.task_id}"
                )
            row = matches[0]
            if len(row) < 5 or not str(row[4]).strip():
                raise RuntimeError(
                    f"中文定稿前置驗收失敗：{args.task_id} 缺少 YouTube 網址"
                )
            folders = resolve_lesson_folders(
                drive, sheets, int(row[1]), str(row[2])
            )
            with TemporaryDirectory(prefix="soulkey-zh-review-qa-") as temp:
                counts = {}
                files_to_check = (
                    ("segments.json", "polish_report.json")
                    if require_polish else ("segments.json",)
                )
                for filename in files_to_check:
                    item = find_file(drive, folders["transcript"], filename)
                    if not item:
                        raise RuntimeError(
                            f"{args.task_id} 尚未產生 01_中文逐字稿/{filename}；"
                            "禁止回報人工定稿已就緒"
                        )
                    local = Path(temp) / filename
                    download_drive_file(drive, item["id"], local)
                    data = json.loads(local.read_text(encoding="utf-8"))
                    segments = data.get("segments") or []
                    nonempty = [
                        row for row in segments
                        if str(row.get("text") or "").strip()
                    ]
                    if not nonempty:
                        raise RuntimeError(
                            f"{args.task_id}/{filename} 不含有效逐字稿；"
                            "禁止回報人工定稿已就緒"
                        )
                    counts[filename] = len(nonempty)
                print(
                    f"[ZH-REVIEW VERIFIED] {args.task_id} "
                    f"ASR={counts['segments.json']} "
                    + (f"polished={counts['polish_report.json']}" if require_polish else "polish=pending"),
                    flush=True,
                )

        # P259 has SHA-verified central English Finals, but some legacy Drive
        # en.final.json files were never synchronized by the new Cloud Bridge.
        # Restore only missing files from exact central revisions before multi.
        central_p259 = args.task_id in {
            "P259-L01", "P259-L02", "P259-L03", "P259-L04"
        }
        if args.stage in {"en","multi","tts","finish"} and args.lang not in {"central4","cc-refresh"}:
            from central_final_sync import sync_finals
            sync_finals(args.task_id,
                        ["zh"] if args.stage=="en" else ["zh","en"],
                        Path("/kaggle/working/central-final-sync")/args.task_id)

        # A human may have finalized a pre-reupload transcript before the
        # new URL was checked. Guard every downstream consumer as well:
        # no translations or TTS from unverified source timestamps.
        if args.stage in {"polish", "vernacular", "en", "multi", "tts", "finish"} and not (
            (args.stage == "en" and args.lang == "cc-refresh")
            or (args.stage == "tts" and central_p259)
            or (args.stage == "multi" and central_p259)
            or (args.stage == "finish" and central_p259)
        ):
            try:
                verify_asr_source_revision()
            except RuntimeError as exc:
                raise RuntimeError(
                    "目前影片來源與中文逐字稿尚未驗證為相同；"
                    "請先重新執行中文定稿（zh）以比對音訊，"
                    "必要時重做 ASR。原人工定稿不會刪除。"
                ) from exc

        if args.stage == "cc" or (
            args.stage == "en" and args.lang == "cc-refresh"
        ):
            prepare_youtube_runtime()

        if args.stage == "cc" and args.lang == "multi-audio":
            langs = ",".join(
                x.strip() for x in args.langs.split(",") if x.strip()
            ) or "all"
            cmd = [
                sys.executable,
                str(system_dir / "youtube_multiaudio_runner.py"),
                "--task-id", args.task_id,
                "--langs", langs,
            ]

        elif args.stage == "zh":
            # URL updates keep the same task ID and Drive folder. Old ASR can
            # only be reused after validating actual source provenance.
            try:
                verify_zh_review_outputs(require_polish=False)
                verify_asr_source_revision()
                print(
                    "[ASR] Drive 既有 segments.json 驗收通過；"
                    "這次僅重新執行 AI 中文校稿，不重跑 ASR。",
                    flush=True,
                )
            except RuntimeError as missing_asr:
                print(f"[ASR] 既有逐字稿缺失：{missing_asr}", flush=True)
                try:
                    run_taiwan_breeze_asr()
                except Exception as exc:
                    print(
                        f"[ASR] Taiwan-Breeze 主流程失敗："
                        f"{type(exc).__name__}: {exc}",
                        flush=True,
                    )
                    run_gemini_source_fallback()

            polish_engine = run_polish_with_local_fallback()
            verify_zh_review_outputs()
            report(
                args.bridge_url,
                args.runtime_nonce,
                "needs_review",
                "Taiwan-Breeze逐字稿 + " + polish_engine +
                " 校稿完成，待人工中文定稿",
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
            run_polish_with_local_fallback()
            cmd = None

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
            print("[CC] 使用 English review refresh 模式", flush=True)
            cmd = [
                sys.executable, str(system_dir / "cc_runner.py"),
                "--task-id", args.task_id,
                "--refresh-english-review",
            ]

        elif args.stage == "en":
            cmd = [
                sys.executable,
                str(system_dir / "gemini_text_production_runner.py"),
                "--task-id", args.task_id,
                "--stage", "en",
            ]

        elif args.stage == "multi" and central_p259:
            # P259 migration: all approved English Finals -> Kaggle local Gemma4.
            # The *existing* Apps Script worker_runtime has already provided
            # short-lived GOOGLE_ACCESS_TOKEN + refreshable nonce above.
            # No Kaggle Secrets or Gemini API keys are needed for this route.
            if args.lang == "central4" and args.task_id != "P259-L01":
                raise RuntimeError("central4_requires_P259-L01_dispatch_anchor")
            require_gpu_runtime("gemma4")
            print("[P259-GEMMA4-BRIDGE] authorized OAuth runtime, local GPU translation",flush=True)
            run([sys.executable, "-m", "pip", "install", "-q", "-U",
                 "huggingface_hub", "edge-tts==7.3.1"])
            translation_cmd = [
                sys.executable, "-u",
                str(system_dir / "p259_gemma4_kaggle.py"),
                "--period", "259", "--max-new-languages", "60",
            ]
            if args.lang != "central4":
                translation_cmd.extend(["--task-id",args.task_id])
                translation_cmd.extend(["--langs",args.langs])
            incomplete_qa=False
            try:
                run(translation_cmd)
            except subprocess.CalledProcessError as exc:
                if exc.returncode != 2:
                    raise
                incomplete_qa=True
                print("[P259-GEMMA4] Some languages need review; preserving passed languages",flush=True)
            # Continue to audio only from verified, current-revision sources.
            audio_cmd=[
                sys.executable, "-u",
                str(system_dir / "central_tts_recovery.py"),
                "--period", "259", "--max-languages", "64",
            ]
            if args.lang != "central4":
                audio_cmd.extend(["--task-id",args.task_id])
                audio_cmd.extend(["--langs",args.langs])
            run(audio_cmd)
            report(args.bridge_url,args.runtime_nonce,"needs_review" if incomplete_qa else "done",
                   "第259期 Gemma4 本地翻譯與核可來源 Edge TTS 已執行；"
                   + ("部分語言仍需 QA 複核；" if incomplete_qa else "")
                   + "以中央 Sheet 和 Drive 的正式檔案為準")
            cmd=None

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

        elif args.stage == "tts" and central_p259:
            # Emergency restoration: use the old Natural TTS/Drive engine, but
            # read the existing SHA-verified central English Final and Gemini QA.
            # Avoid Gemini translation calls and legacy Drive Final preflights;
            # many current P259 English Finals are still in the central Sheet.
            if args.lang == "central4" and args.task_id != "P259-L01":
                raise RuntimeError("central4_requires_P259-L01_dispatch_anchor")
            print("[P259-RESCUE] Authentic old Kaggle+Apps Script Bridge; "
                  "recover all four lessons, source-verified languages only", flush=True)
            run([sys.executable, "-m", "pip", "install", "-q",
                 "edge-tts==7.3.1"])
            central_audio=[sys.executable, "-u",
                 str(system_dir / "central_tts_recovery.py"),
                 "--period", "259", "--max-languages", "64"]
            if args.lang != "central4":
                if not args.langs.strip():raise RuntimeError("TTS 沒有指定任何語言")
                central_audio.extend(["--task-id",args.task_id,"--langs",args.langs])
            run(central_audio)
            report(args.bridge_url, args.runtime_nonce, "needs_review",
                   "已核對中央英文定稿及各語言 QA，恢復可用音檔；"
                   "仍需檢查每語言 tts:<lang> 和 Drive MP3，未完成語言繼續等待翻譯")
            cmd = None

        elif args.stage == "tts":
            requested_audio_langs = [
                x.strip() for x in args.langs.split(",") if x.strip()
            ]
            langs = ",".join(requested_audio_langs)
            if not langs:
                raise RuntimeError("TTS 沒有指定任何語言")

            # Dependency repair:
            # Every non-English TTS must be based on translations generated
            # from the CURRENT en.final.json. The multi runner invalidates its
            # checkpoint automatically when the English Final fingerprint
            # changes, so this preflight is cheap when current and performs a
            # full retranslation when stale.
            translate_langs = [
                lang for lang in requested_audio_langs if lang != "en"
            ]
            if translate_langs:
                if not gemini_api_key:
                    raise RuntimeError(
                        "非英文 TTS 需要先驗證/更新 multi，"
                        "但 Apps Script 沒有提供 GEMINI_API_KEY"
                    )
                print(
                    "[TTS:DEPENDENCY] 先同步目前 English Final → "
                    + ",".join(translate_langs),
                    flush=True,
                )
                run_checkpointed_multi([
                    sys.executable,
                    str(system_dir / "gemini_multi_production_runner.py"),
                    "--task-id", args.task_id,
                    "--langs", ",".join(translate_langs),
                ], refresh_credentials=lambda:refresh_worker_drive_credentials(
                    args.bridge_url, args.runtime_nonce
                ))

            print(
                "[TTS] Natural TTS v2 使用 CPU + Internet；不申請 GPU。",
                flush=True,
            )

            cmd = [
                sys.executable,
                str(system_dir / "tts_runner.py"),
                "--task-id", args.task_id,
                "--langs", langs,
                "--max-tasks", "1",
                "--smart-fit-pilot",
                "--strict-delivery",
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

            # Batch can reach the audio stage inside this same worker.
            # Prepare YouTube auto-dub discovery before batch execution.
            try:
                prepare_youtube_runtime()
            except Exception as youtube_runtime_exc:
                print(
                    "[YouTube] Batch 音軌 runtime 準備失敗；"
                    "後續仍可使用本地 TTS fallback。原因="
                    f"{type(youtube_runtime_exc).__name__}: "
                    f"{youtube_runtime_exc}",
                    flush=True,
                )

            # The full batch is checkpoint-safe. If one top-level pass exits
            # non-zero (Gemini/TTS/Drive transient issue), restart the batch
            # inside the SAME Kaggle kernel so completed stages are skipped and
            # the user does not need to press Run again.
            batch_cmd = [
                sys.executable,
                str(system_dir / "batch_full_runner.py"),
                "--task-ids", task_ids,
            ]
            batch_retry_waits = [30, 120]
            for batch_attempt in range(1, len(batch_retry_waits) + 2):
                try:
                    print(
                        f"[BATCH AUTO-RESUME] pass {batch_attempt}/"
                        f"{len(batch_retry_waits) + 1}",
                        flush=True,
                    )
                    run(batch_cmd)
                    break
                except subprocess.CalledProcessError:
                    if batch_attempt > len(batch_retry_waits):
                        raise
                    wait_seconds = batch_retry_waits[batch_attempt - 1]
                    print(
                        "[BATCH AUTO-RESUME] batch returned non-zero; "
                        f"wait {wait_seconds}s then resume from checkpoints.",
                        flush=True,
                    )
                    time.sleep(wait_seconds)

            report(
                args.bridge_url,
                args.runtime_nonce,
                "done",
                "批次全流程完成：" + task_ids,
            )
            cmd = None

        elif args.stage == "finish" and central_p259:
            # The quick editor's final button uses the same central Finals,
            # local GPU translation and original CPU Natural TTS as Studio.
            if args.langs.strip():
                require_gpu_runtime("gemma4")
                run([sys.executable,"-m","pip","install","-q","huggingface_hub"])
                run([sys.executable,"-u",str(system_dir/"p259_gemma4_kaggle.py"),
                     "--task-id",args.task_id,"--langs",args.langs])
            if args.lang.strip():
                run([sys.executable,"-m","pip","install","-q","edge-tts==7.3.1"])
                run([sys.executable,"-u",str(system_dir/"central_tts_recovery.py"),
                     "--task-id",args.task_id,"--langs",args.lang,
                     "--max-languages","16"])
            report(args.bridge_url,args.runtime_nonce,"needs_review",
                   "已依勾選執行中央文稿翻譯與音檔；請逐語確認 QA、Drive 文稿及 MP3")
            cmd=None

        elif args.stage == "finish":
            translate_langs = ",".join(
                x.strip() for x in args.langs.split(",") if x.strip()
            )
            audio_langs = ",".join(
                x.strip() for x in args.lang.split(",") if x.strip()
            )

            if translate_langs:
                run_checkpointed_multi([
                    sys.executable,
                    str(system_dir / "gemini_multi_production_runner.py"),
                    "--task-id", args.task_id,
                    "--langs", translate_langs,
                ])

            audio_result="done"
            if audio_langs:
                print(
                    "[FINISH:TTS] Natural TTS v2 使用 CPU + Internet；"
                    "逐語言驗證 Drive MP3；若失敗自動補跑。",
                    flush=True,
                )
                audio_result=run_verified_tts_job([
                    sys.executable,
                    str(system_dir / "tts_runner.py"),
                    "--task-id", args.task_id,
                    "--langs", audio_langs,
                    "--max-tasks", "1",
                    "--smart-fit-pilot",
                    "--strict-delivery",
                ],refresh_credentials=lambda:refresh_worker_drive_credentials(
                    args.bridge_url,args.runtime_nonce
                ))

            if not translate_langs and not audio_langs:
                print("[FINISH] 沒有額外翻譯或音檔；中英 Final 已完成。", flush=True)

            report(
                args.bridge_url,
                args.runtime_nonce,
                "needs_review" if audio_result=="needs_review" else "done",
                ("部分語言超過原片時長；已保留智慧精簡審核報告，未發布超時 MP3"
                 if audio_result=="needs_review"
                 else "所有勾選語言智慧配音 MP3 已通過時長與 Drive 驗證")
                + "；Gemini翻譯=" + (translate_langs or "無")
                + "；音檔=" + (audio_langs or "無"),
            )
            cmd = None

        if cmd and args.stage=="tts":
            audio_result=run_verified_tts_job(
                cmd,refresh_credentials=lambda:refresh_worker_drive_credentials(
                    args.bridge_url,args.runtime_nonce
                )
            )
            report(
                args.bridge_url,args.runtime_nonce,
                "needs_review" if audio_result=="needs_review" else "done",
                "部分語言未達原片時長要求，未交付超時 MP3；保留精簡報告"
                if audio_result=="needs_review"
                else "所有指定語言智慧配音 MP3 已完成時長與 Drive 驗證",
            )
            cmd=None
        if cmd and args.stage=="multi":
            run_checkpointed_multi(
                cmd,
                refresh_credentials=lambda:refresh_worker_drive_credentials(
                    args.bridge_url, args.runtime_nonce
                ),
            )
            cmd=None
        if cmd:
            run(cmd)
        if args.stage in {"en", "cc"}:
            seed_english_review_cache(
                args.bridge_url, args.runtime_nonce, args.task_id
            )
        print("[WEB-WORKER] 正式 Stage 執行完成。")

    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        print("[WEB-WORKER ERROR]", message, file=sys.stderr)
        report(args.bridge_url, args.runtime_nonce, "error", message)
        raise

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
