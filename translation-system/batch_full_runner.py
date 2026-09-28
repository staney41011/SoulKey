import argparse
import json
import os
import shutil
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

from config import COL, SPREADSHEET_ID, TASK_SHEET_RANGE
from google_io import (
    build_google_services,
    download_drive_file,
    find_file,
    get_secret,
    read_values,
    update_cells,
    upload_or_replace_file,
)
from lesson_paths import digits, resolve_lesson_folders
from status_io import new_run_id, mark_done, mark_error, mark_running


LANGS = ["en", "th", "es", "id", "vi", "sd", "ta"]
TARGET_LANGS = ["th", "es", "id", "vi", "sd", "ta"]


def run(cmd, cwd=None):
    cmd = [str(x) for x in cmd]
    if cmd and Path(cmd[0]).name.startswith("python") and "-u" not in cmd[1:2]:
        cmd.insert(1, "-u")
    print("$", " ".join(cmd), flush=True)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def pad_row(row, length=20):
    return list(row) + [""] * max(0, length - len(row))


def find_task(sheets, task_id):
    for index, raw in enumerate(
        read_values(sheets, SPREADSHEET_ID, TASK_SHEET_RANGE),
        start=2,
    ):
        row = pad_row(raw, 20)
        if str(row[COL["task_id"]] or "").strip() != task_id:
            continue
        return {
            "sheet_row": index,
            "task_id": task_id,
            "period": digits(row[COL["period"]]),
            "lesson": str(row[COL["lesson"]] or "").strip(),
        }
    return None


def format_srt_time(seconds):
    ms = max(0, int(round(float(seconds) * 1000)))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, milli = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{milli:03d}"


def write_result_set(output_dir, stem, payload, finalized_by):
    output_dir.mkdir(parents=True, exist_ok=True)
    segments = payload.get("segments") or []
    if not segments:
        raise RuntimeError(f"{stem}: source has no segments")

    extra = {k: v for k, v in payload.items() if k != "segments"}
    extra.update({
        "finalized_by": finalized_by,
        "finalized_at": datetime.now().isoformat(timespec="seconds"),
        "segments": segments,
    })

    json_path = output_dir / f"{stem}.json"
    txt_path = output_dir / f"{stem}.txt"
    srt_path = output_dir / f"{stem}.srt"

    json_path.write_text(
        json.dumps(extra, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    txt_path.write_text(
        "\n".join(str(x.get("text") or "").strip() for x in segments) + "\n",
        encoding="utf-8",
    )

    blocks = []
    for order, seg in enumerate(segments, start=1):
        blocks.append(
            f"{order}\n"
            f"{format_srt_time(seg.get('start', 0))} --> "
            f"{format_srt_time(seg.get('end', 0))}\n"
            f"{str(seg.get('text') or '').strip()}"
        )
    srt_path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    return json_path, txt_path, srt_path


def promote_final(
    drive,
    source_folder,
    source_name,
    target_folder,
    target_stem,
    workdir,
    finalized_by,
):
    item = find_file(drive, source_folder, source_name)
    if not item:
        raise RuntimeError(f"找不到自動定稿來源：{source_name}")

    src = workdir / source_name
    download_drive_file(drive, item["id"], src)
    payload = json.loads(src.read_text(encoding="utf-8"))

    outputs = write_result_set(
        workdir / "auto-final",
        target_stem,
        payload,
        finalized_by,
    )
    for path in outputs:
        upload_or_replace_file(
            drive,
            target_folder,
            path,
            Path(path).name,
        )
    print(
        f"[AUTO-FINAL] {source_name} -> {target_stem}.* "
        f"({finalized_by})",
        flush=True,
    )


def publish_subtitles(drive, folders, workdir):
    sources = [
        (folders["transcript"], "zh-TW.final.srt"),
        (folders["translation"], "zh-TW.vernacular.final.srt"),
        (folders["translation"], "en.final.srt"),
    ] + [
        (folders["translation"], f"{lang}.srt")
        for lang in TARGET_LANGS
    ]

    copied = []
    outdir = workdir / "subtitles"
    outdir.mkdir(parents=True, exist_ok=True)

    for folder_id, name in sources:
        item = find_file(drive, folder_id, name)
        if not item:
            print(f"[SUBTITLE] skip missing {name}", flush=True)
            continue
        path = outdir / name
        download_drive_file(drive, item["id"], path)
        upload_or_replace_file(drive, folders["subtitle"], path, name)
        copied.append(name)

    manifest = outdir / "subtitle_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "files": copied,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    upload_or_replace_file(
        drive,
        folders["subtitle"],
        manifest,
        manifest.name,
    )
    print(f"[SUBTITLE] published {len(copied)} files", flush=True)


def prepare_asr_model():
    root = Path("/kaggle/input")
    matches = []
    if root.exists():
        try:
            matches = list(root.rglob("taiwan-breeze-asr-26/model.bin"))
        except Exception as exc:
            print(f"[ASR-PREFLIGHT] scan failed: {exc}", flush=True)

    if matches:
        model_dir = matches[0].parent
        os.environ["ASR_MODEL_PATH"] = str(model_dir)
        print(f"[ASR] 使用永久 Taiwan-Breeze：{model_dir}", flush=True)
        return

    run([
        sys.executable,
        Path(__file__).resolve().parent / "prepare_model.py",
    ])
    model_dir = Path("/kaggle/working/persistent-model/taiwan-breeze-asr-26")
    if not (model_dir / "model.bin").exists():
        raise RuntimeError("Taiwan-Breeze prepare_model 後仍找不到 model.bin")
    os.environ["ASR_MODEL_PATH"] = str(model_dir)


def prepare_youtube_runtime(system_dir):
    for script in [
        "setup_js_runtime.py",
        "prepare_youtube_js.py",
        "setup_youtube_runtime.py",
        "setup_wpc_provider.py",
    ]:
        run([sys.executable, system_dir / script])


def ensure_required_secrets():
    # The normal production path receives a short-lived Google token from the
    # Studio Bridge. Legacy OAuth client secrets are only a fallback for manual
    # Kaggle runs.
    if str(os.environ.get("GOOGLE_ACCESS_TOKEN") or "").strip():
        print("[AUTH] Google OAuth: Studio Bridge token OK", flush=True)
    else:
        for name in [
            "GOOGLE_CLIENT_ID",
            "GOOGLE_CLIENT_SECRET",
            "GOOGLE_REFRESH_TOKEN",
        ]:
            value = get_secret(name, required=False)
            if not value:
                raise RuntimeError(f"Kaggle 缺少必要 Secret: {name}")
            print(f"[SECRET] {name}: OK", flush=True)

    for name in ["YOUTUBE_COOKIES_B64", "GEMINI_API_KEY"]:
        value = str(os.environ.get(name) or "").strip()
        if not value:
            value = get_secret(name, required=False)
            if value:
                os.environ[name] = value
        if not value:
            raise RuntimeError(f"Kaggle 缺少必要 Secret: {name}")
        print(f"[SECRET] {name}: OK", flush=True)


def process_task(task_id, system_dir):
    drive, sheets = build_google_services()
    task = find_task(sheets, task_id)
    if not task:
        raise RuntimeError(f"找不到任務：{task_id}")
    if task["period"] is None or not task["lesson"]:
        raise RuntimeError(f"{task_id} 缺少期數或堂次")

    folders = resolve_lesson_folders(
        drive,
        sheets,
        int(task["period"]),
        task["lesson"],
    )
    workdir = Path("/kaggle/working/soulkey-full-batch") / task_id
    workdir.mkdir(parents=True, exist_ok=True)

    run_id = new_run_id(task_id, "full-batch")
    mark_running(
        task_id,
        "full-batch",
        sheets=sheets,
        run_id=run_id,
        message="255期批次全流程執行中",
        progress=1,
    )

    try:
        # 1. Taiwan-Breeze is the primary ASR.
        # If YouTube refuses the audio download even after the PO-token/client
        # fallbacks, continue with Gemini direct YouTube understanding rather
        # than aborting the entire lesson.
        transcript_source = "taiwan-breeze"
        try:
            run([
                sys.executable, system_dir / "runner.py",
                "--task-id", task_id,
                "--stage", "asr",
                "--max-tasks", "1",
                "--force-asr",
            ])
        except subprocess.CalledProcessError as exc:
            transcript_source = "gemini-youtube-fallback"
            print(
                f"[ASR-FALLBACK] Taiwan-Breeze source acquisition failed for "
                f"{task_id}: {exc}. Falling back to Gemini YouTube transcript.",
                flush=True,
            )
            run([
                sys.executable,
                system_dir / "gemini_source_runner.py",
                "--task-id", task_id,
                "--force",
            ])

        # 2. Gemini semantic Chinese polish.
        run([
            sys.executable, system_dir / "gemini_text_production_runner.py",
            "--task-id", task_id,
            "--stage", "polish",
        ])

        # User explicitly requested the full 255 batch to run end-to-end.
        # Promote the AI-reviewed draft with transparent provenance rather than
        # pretending it was manually finalized.
        promote_final(
            drive,
            folders["transcript"],
            "zh-TW.polished.json",
            folders["transcript"],
            "zh-TW.final",
            workdir,
            "batch_auto_user_requested",
        )

        # 3. Vernacular Traditional Chinese, then transparent auto-final.
        run([
            sys.executable, system_dir / "gemini_text_production_runner.py",
            "--task-id", task_id,
            "--stage", "vernacular",
        ])
        promote_final(
            drive,
            folders["translation"],
            "zh-TW.vernacular.json",
            folders["translation"],
            "zh-TW.vernacular.final",
            workdir,
            "batch_auto_user_requested",
        )

        # 4. English draft, then transparent auto-final.
        run([
            sys.executable, system_dir / "gemini_text_production_runner.py",
            "--task-id", task_id,
            "--stage", "en",
        ])
        promote_final(
            drive,
            folders["translation"],
            "en.json",
            folders["translation"],
            "en.final",
            workdir,
            "batch_auto_user_requested",
        )

        # 5. Gemini 3.1 six-language translation + semantic QA + repair.
        run([
            sys.executable, system_dir / "gemini_multi_production_runner.py",
            "--task-id", task_id,
            "--langs", ",".join(TARGET_LANGS),
        ])

        # 6. Meta MMS seven-language TTS on Kaggle GPU.
        run([
            sys.executable, system_dir / "tts_runner.py",
            "--task-id", task_id,
            "--langs", ",".join(LANGS),
            "--max-tasks", "1",
            "--force",
        ])

        # 7. Put all final SRTs into the dedicated subtitle folder.
        publish_subtitles(drive, folders, workdir)

        update_cells(
            sheets,
            SPREADSHEET_ID,
            {
                f"任務佇列!Q{task['sheet_row']}": "未製作",
                f"任務佇列!R{task['sheet_row']}": "100",
                f"任務佇列!S{task['sheet_row']}": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                f"任務佇列!T{task['sheet_row']}": (
                    "255期批次全流程完成：來源=" + transcript_source + "；"
                    "Gemini校稿/英文/六語QA、Meta MMS七語TTS、字幕輸出；"
                    "Final為使用者要求的批次自動定稿"
                ),
            },
        )
        mark_done(
            task_id,
            "full-batch",
            sheets=sheets,
            run_id=run_id,
            message=(
                "批次全流程完成；source=" + transcript_source +
                "；Final=batch_auto_user_requested"
            ),
        )
        print(f"[FULL-BATCH DONE] {task_id}", flush=True)
        return True

    except Exception as exc:
        mark_error(
            task_id,
            "full-batch",
            sheets=sheets,
            run_id=run_id,
            exc=exc,
        )
        print(
            f"[FULL-BATCH ERROR] {task_id}: {type(exc).__name__}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--task-ids",
        default="P255-L01,P255-L02",
        help="逗號分隔 task ids",
    )
    args = parser.parse_args()

    task_ids = [
        x.strip()
        for x in args.task_ids.split(",")
        if x.strip()
    ]
    if not task_ids:
        raise RuntimeError("沒有 task id")

    system_dir = Path(__file__).resolve().parent
    os.environ["SOULKEY_REQUIRE_GPU"] = "1"
    os.environ.setdefault("CUDA_DEVICE_ORDER", "PCI_BUS_ID")

    print("=" * 72)
    print("SoulKey｜255期兩堂課批次全流程")
    print("ASR=Taiwan-Breeze | AI=Gemini | TTS=Meta MMS")
    print("Final provenance=batch_auto_user_requested")
    print("=" * 72)

    ensure_required_secrets()
    prepare_youtube_runtime(system_dir)
    prepare_asr_model()

    failed = []
    for task_id in task_ids:
        ok = process_task(task_id, system_dir)
        if not ok:
            failed.append(task_id)

    if failed:
        raise RuntimeError("批次未完全成功：" + ",".join(failed))

    print("[BATCH DONE] " + ",".join(task_ids), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
