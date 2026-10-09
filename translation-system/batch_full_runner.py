import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from config import COL, SPREADSHEET_ID, TASK_SHEET_RANGE
from drive_naming import formal_drive_name
from google_io import (
    build_google_services,
    download_drive_file,
    find_file,
    get_secret,
    read_values,
    update_cells,
    upload_or_replace_file,
)
from github_review_cache import publish_review_cache
from lesson_paths import digits, resolve_lesson_folders
from status_io import new_run_id, mark_done, mark_error, mark_running
from source_revision import verify_existing_asr


LANGS = ["en", "th", "es", "id", "vi", "hi", "ta", "ja", "ko"]
TARGET_LANGS = ["th", "es", "id", "vi", "hi", "ta", "ja", "ko"]


def run(cmd, cwd=None):
    cmd = [str(x) for x in cmd]
    if cmd and Path(cmd[0]).name.startswith("python") and "-u" not in cmd[1:2]:
        cmd.insert(1, "-u")
    print("$", " ".join(cmd), flush=True)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    subprocess.run(cmd, cwd=cwd, env=env, check=True)



TRANSIENT_GEMINI_MARKERS = (
    "HTTP 429",
    "HTTP 500",
    "HTTP 502",
    "HTTP 503",
    "HTTP 504",
    "service_unavailable",
    "high demand",
    "rate limit",
    "timeout",
    "temporarily unavailable",
)


def run_gemini_stage_with_backoff(cmd, label, waits=(30, 60, 120, 300, 600)):
    """Retry only transient Gemini/API failures, then continue the batch."""
    cmd = [str(x) for x in cmd]
    if cmd and Path(cmd[0]).name.startswith("python") and "-u" not in cmd[1:2]:
        cmd.insert(1, "-u")

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    for attempt in range(1, len(waits) + 2):
        print(
            f"[AUTO-RESUME] {label} attempt {attempt}/{len(waits)+1}",
            flush=True,
        )
        result = subprocess.run(
            cmd,
            env=env,
            text=True,
            capture_output=True,
        )
        if result.stdout:
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n", flush=True)
        if result.stderr:
            print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr, flush=True)

        if result.returncode == 0:
            if attempt > 1:
                print(
                    f"[AUTO-RESUME] {label} recovered on attempt {attempt}",
                    flush=True,
                )
            return

        combined = (result.stdout or "") + "\n" + (result.stderr or "")
        transient = any(
            marker.lower() in combined.lower()
            for marker in TRANSIENT_GEMINI_MARKERS
        )
        if not transient or attempt > len(waits):
            raise subprocess.CalledProcessError(
                result.returncode,
                cmd,
                output=result.stdout,
                stderr=result.stderr,
            )

        wait_seconds = waits[attempt - 1]
        print(
            f"[AUTO-RESUME] {label} transient failure; "
            f"waiting {wait_seconds}s before retry.",
            flush=True,
        )
        time.sleep(wait_seconds)


def drive_has_file(drive, folder_id, name):
    return bool(find_file(drive, folder_id, name))


def drive_has_youtube_primary_audio(drive, folder_id, lang, workdir):
    manifest_item = find_file(
        drive,
        folder_id,
        "youtube-audio-manifest.json",
    )
    if not manifest_item:
        return False

    check_dir = workdir / "youtube-audio-check"
    check_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = check_dir / "youtube-audio-manifest.json"
    try:
        download_drive_file(drive, manifest_item["id"], manifest_path)
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return False

    selected = payload.get("selected_as_primary_audio") or {}
    item = selected.get(lang)
    if isinstance(item, dict):
        canonical = str(item.get("canonical_name") or "").strip()
        if canonical and find_file(drive, folder_id, canonical):
            return True

    wanted = str(lang or "").lower().split("-", 1)[0]
    for uploaded in payload.get("uploaded") or []:
        audio_lang = str(uploaded.get("language") or "").lower()
        if audio_lang.split("-", 1)[0] != wanted:
            continue
        canonical = str(
            uploaded.get("canonical_name") or uploaded.get("file") or ""
        ).strip()
        if canonical and find_file(drive, folder_id, canonical):
            return True

    return False


def segments_fingerprint(segments):
    canonical = [
        {
            "id": int(x.get("id", i)),
            "start": float(x.get("start", 0) or 0),
            "end": float(x.get("end", 0) or 0),
            "text": str(x.get("text") or ""),
        }
        for i, x in enumerate(segments or [])
    ]
    raw = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def drive_json_matches_source(
    drive,
    output_folder,
    output_name,
    source_folder,
    source_name,
    workdir,
):
    output_item = find_file(drive, output_folder, output_name)
    source_item = find_file(drive, source_folder, source_name)
    if not output_item or not source_item:
        return False

    check_dir = workdir / "source-check"
    check_dir.mkdir(parents=True, exist_ok=True)
    safe_output = output_name.replace("/", "_")
    safe_source = source_name.replace("/", "_")
    output_path = check_dir / ("out-" + safe_output)
    source_path = check_dir / ("src-" + safe_source)
    download_drive_file(drive, output_item["id"], output_path)
    download_drive_file(drive, source_item["id"], source_path)

    output_payload = json.loads(output_path.read_text(encoding="utf-8"))
    source_payload = json.loads(source_path.read_text(encoding="utf-8"))
    current_sha = segments_fingerprint(source_payload.get("segments") or [])
    recorded_sha = str(output_payload.get("source_sha256") or "").strip()

    if not recorded_sha:
        # A legacy output without provenance cannot be proven to belong to the
        # current upstream source. Never "bless" it by stamping today's hash:
        # that can silently attach stale text to a new source revision.
        print(
            f"[SOURCE-CHECK] {output_name} has no source_sha256; "
            "force one-time regeneration from the current source.",
            flush=True,
        )
        return False

    matched = recorded_sha == current_sha
    if not matched:
        print(
            f"[SOURCE-CHECK] {output_name} stale: "
            f"recorded={recorded_sha[:12]} current={current_sha[:12]}",
            flush=True,
        )
    return matched


def plain_time(seconds):
    total = max(0, int(float(seconds or 0)))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def ensure_review_cache(drive, folders, task_id, workdir):
    """Rebuild/publish the deterministic Studio Chinese review cache.

    The batch can legitimately resume past polish when zh-TW.polished.json
    already exists. Publishing the review cache must therefore be a separate
    checkpoint, not an accidental side effect of re-running Gemini polish.
    """
    raw_item = find_file(drive, folders["transcript"], "segments.json")
    polished_item = find_file(drive, folders["transcript"], "zh-TW.polished.json")
    if not raw_item or not polished_item:
        print(
            f"[REVIEW-CACHE] {task_id} source files incomplete; skip publish.",
            flush=True,
        )
        return False

    cache_dir = workdir / "review-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    raw_path = cache_dir / "segments.json"
    polished_path = cache_dir / "zh-TW.polished.json"
    download_drive_file(drive, raw_item["id"], raw_path)
    download_drive_file(drive, polished_item["id"], polished_path)

    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    polished = json.loads(polished_path.read_text(encoding="utf-8"))
    raw_segments = raw.get("segments") or []
    polished_by_id = {
        int(row.get("id", idx)): row
        for idx, row in enumerate(polished.get("segments") or [])
    }

    review_segments = []
    for idx, src in enumerate(raw_segments):
        sid = int(src.get("id", idx))
        polished_row = polished_by_id.get(sid)
        if polished_row is None:
            raise RuntimeError(
                f"{task_id} review cache missing polished segment id={sid}"
            )
        raw_text = str(src.get("text") or "")
        text = str(polished_row.get("text") or "")
        start = float(src.get("start") or 0)
        end = float(src.get("end") or start)
        review_segments.append({
            "id": sid,
            "start": start,
            "end": end,
            "time": plain_time(start),
            "raw": raw_text,
            "text": text,
            "flags": ["changed"] if text != raw_text else [],
            "source_en": "",
            "en_text": "",
            "en_confirmed": False,
        })

    payload = {
        "version": 5,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_segments": len(review_segments),
        "segments": review_segments,
    }
    cache_path = cache_dir / "zh-TW.review-cache.json"
    cache_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    result = publish_review_cache(task_id, cache_path)
    if isinstance(result, dict) and result.get("ok") is False:
        print(
            f"[REVIEW-CACHE] {task_id} publish deferred/failed: "
            f"{result.get('error') or result.get('message')}",
            flush=True,
        )
        return False

    print(
        f"[REVIEW-CACHE] {task_id} published {len(review_segments)} segments.",
        flush=True,
    )
    return True


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
            "youtube_url": str(row[COL["youtube_url"]] or "").strip(),
            "title": str(row[COL["title"]] or "").strip(),
            "lecturer": str(row[COL["lecturer"]] or "").strip(),
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
    task,
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
        canonical_name = Path(path).name
        upload_or_replace_file(
            drive,
            target_folder,
            path,
            canonical_name,
            display_name=formal_drive_name(task, canonical_name),
        )
    print(
        f"[AUTO-FINAL] {source_name} -> {target_stem}.* "
        f"({finalized_by})",
        flush=True,
    )


def publish_subtitles(drive, folders, workdir, task):
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
        upload_or_replace_file(
            drive,
            folders["subtitle"],
            path,
            name,
            display_name=formal_drive_name(task, name),
        )
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
        display_name=formal_drive_name(task, manifest.name),
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

    # Gemini is required for polish/translation. YouTube cookies are only
    # an optional acquisition fallback: bgutil guest PO tokens work without
    # them, and checkpoint resumes may not touch YouTube at all.
    gemini = str(os.environ.get("GEMINI_API_KEY") or "").strip()
    if not gemini:
        gemini = get_secret("GEMINI_API_KEY", required=False)
        if gemini:
            os.environ["GEMINI_API_KEY"] = gemini
    if not gemini:
        raise RuntimeError("Kaggle 缺少必要 Secret: GEMINI_API_KEY")
    print("[SECRET] GEMINI_API_KEY: OK", flush=True)

    cookies = str(os.environ.get("YOUTUBE_COOKIES_B64") or "").strip()
    if not cookies:
        cookies = get_secret("YOUTUBE_COOKIES_B64", required=False)
        if cookies:
            os.environ["YOUTUBE_COOKIES_B64"] = cookies
    print(
        "[SECRET] YOUTUBE_COOKIES_B64: "
        + ("OK" if cookies else "未設定（guest PO token / checkpoint 模式可繼續）"),
        flush=True,
    )


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
        reusable_asr = False
        if drive_has_file(drive, folders["transcript"], "segments.json"):
            from youtube_io import download_audio
            youtube_prepared = [False]

            def fetch_for_comparison(url, destination):
                if not youtube_prepared[0]:
                    prepare_youtube_runtime(system_dir)
                    youtube_prepared[0] = True
                return download_audio(url, destination)

            reusable_asr, reason = verify_existing_asr(
                drive, folders, task["youtube_url"],
                workdir / "source-revision",
                fetch_for_comparison,
            )
            print(
                f"[SOURCE-REVISION] {task_id} reusable={reusable_asr} "
                f"reason={reason}", flush=True,
            )
        if reusable_asr:
            print(
                f"[RESUME] {task_id} audio provenance verified; skip ASR.",
                flush=True,
            )
        else:
            try:
                # Heavy YouTube/ASR setup is lazy. A checkpoint resume that
                # already has segments.json must not fail because Deno, cookies,
                # model download, or CUDA ASR setup is temporarily unavailable.
                prepare_youtube_runtime(system_dir)
                prepare_asr_model()
                run([
                    sys.executable, system_dir / "runner.py",
                    "--task-id", task_id,
                    "--stage", "asr",
                    "--max-tasks", "1",
                    "--force-asr",
                ])
            except Exception as exc:
                transcript_source = "gemini-youtube-fallback"
                print(
                    f"[ASR-FALLBACK] Taiwan-Breeze source acquisition/preflight failed for "
                    f"{task_id}: {type(exc).__name__}: {exc}. "
                    "Falling back to Gemini YouTube transcript.",
                    flush=True,
                )
                run_gemini_stage_with_backoff(
                    [
                        sys.executable,
                        system_dir / "gemini_source_runner.py",
                        "--task-id", task_id,
                        "--force",
                    ],
                    f"{task_id} Gemini source fallback",
                )

        # 2. Gemini semantic Chinese polish.
        polish_current = drive_json_matches_source(
            drive,
            folders["transcript"],
            "zh-TW.polished.json",
            folders["transcript"],
            "segments.json",
            workdir,
        )
        polish_changed = not polish_current
        if polish_current:
            print(
                f"[RESUME] {task_id} polish source revision matches; skip.",
                flush=True,
            )
        else:
            run_gemini_stage_with_backoff(
                [
                    sys.executable,
                    system_dir / "gemini_text_production_runner.py",
                    "--task-id", task_id,
                    "--stage", "polish",
                ],
                f"{task_id} polish",
            )

        # Review cache is its own checkpoint. Resuming past polish must not
        # strand Studio on a missing GitHub cache.
        ensure_review_cache(drive, folders, task_id, workdir)

        # User explicitly requested the full 255 batch to run end-to-end.
        # Promote the AI-reviewed draft with transparent provenance rather than
        # pretending it was manually finalized.
        if (
            not polish_changed
            and drive_has_file(drive, folders["transcript"], "zh-TW.final.json")
        ):
            print(
                f"[RESUME] {task_id} zh-TW.final.json already matches current polish; skip promotion.",
                flush=True,
            )
        else:
            promote_final(
                drive,
                folders["transcript"],
                "zh-TW.polished.json",
                folders["transcript"],
                "zh-TW.final",
                workdir,
                "batch_auto_user_requested",
                task,
            )

        # Keep Studio's public workflow contract aligned with the files that
        # actually exist. This does not claim human review: the message makes
        # the batch/auto-final provenance explicit.
        mark_done(
            task_id,
            "zh",
            sheets=sheets,
            run_id=new_run_id(task_id, "zh-batch-final"),
            message="中文 Final 已確認存在；批次來源/自動定稿，不代表人工審閱",
        )

        # 3. Vernacular Traditional Chinese, then transparent auto-final.
        vernacular_current = drive_json_matches_source(
            drive,
            folders["translation"],
            "zh-TW.vernacular.json",
            folders["transcript"],
            "zh-TW.final.json",
            workdir,
        )
        vernacular_changed = not vernacular_current
        if vernacular_current:
            print(
                f"[RESUME] {task_id} vernacular source revision matches; skip.",
                flush=True,
            )
        else:
            run_gemini_stage_with_backoff(
                [
                    sys.executable, system_dir / "gemini_text_production_runner.py",
                    "--task-id", task_id,
                    "--stage", "vernacular",
                ],
                f"{task_id} vernacular",
            )

        if (
            not vernacular_changed
            and drive_has_file(
                drive,
                folders["translation"],
                "zh-TW.vernacular.final.json",
            )
        ):
            print(
                f"[RESUME] {task_id} vernacular final matches current source; skip promotion.",
                flush=True,
            )
        else:
            promote_final(
                drive,
                folders["translation"],
                "zh-TW.vernacular.json",
                folders["translation"],
                "zh-TW.vernacular.final",
                workdir,
                "batch_auto_user_requested",
                task,
            )

        # 4. English draft, then transparent auto-final.
        english_current = drive_json_matches_source(
            drive,
            folders["translation"],
            "en.json",
            folders["translation"],
            "zh-TW.vernacular.final.json",
            workdir,
        )
        english_changed = not english_current
        if english_current:
            print(
                f"[RESUME] {task_id} English source revision matches; skip.",
                flush=True,
            )
        else:
            run_gemini_stage_with_backoff(
                [
                    sys.executable, system_dir / "gemini_text_production_runner.py",
                    "--task-id", task_id,
                    "--stage", "en",
                ],
                f"{task_id} English",
            )

        if (
            not english_changed
            and drive_has_file(drive, folders["translation"], "en.final.json")
        ):
            print(
                f"[RESUME] {task_id} en.final.json already matches current English draft; skip promotion.",
                flush=True,
            )
        else:
            promote_final(
                drive,
                folders["translation"],
                "en.json",
                folders["translation"],
                "en.final",
                workdir,
                "batch_auto_user_requested",
                task,
            )

        mark_done(
            task_id,
            "en-review",
            sheets=sheets,
            run_id=new_run_id(task_id, "en-batch-final"),
            message="English Final 已確認存在；批次來源/自動定稿，不代表人工審閱",
        )

        # 5. Gemini multilingual translation + semantic QA + repair.
        # Always enter the checkpoint-aware runner. Merely seeing th/es/... JSON
        # files is not proof they were produced from the current English Final.
        # The runner validates the English-source fingerprint and normally exits
        # quickly from its persistent checkpoint when nothing changed.
        run_gemini_stage_with_backoff(
            [
                sys.executable,
                system_dir / "gemini_multi_production_runner.py",
                "--task-id", task_id,
                "--langs", ",".join(TARGET_LANGS),
            ],
            f"{task_id} multilingual translation",
        )

        # 6. Audio stage: SoulKey Natural TTS v2 from approved Final translations.
        # YouTube auto-dub is benchmark-only and never satisfies formal audio.
        run([
            sys.executable, system_dir / "tts_runner.py",
            "--task-id", task_id,
            "--langs", ",".join(LANGS),
            "--max-tasks", "1",
        ])

        # Audio is complete when either:
        # 1) YouTube supplied a multilingual / auto-dubbed MP3 selected as the
        #    primary source, OR
        # 2) local TTS supplied the normal WAV + MP3 pair.
        missing_audio = []
        for lang in LANGS:
            has_tts = (
                drive_has_file(drive, folders["audio"], f"{lang}.wav")
                and drive_has_file(drive, folders["audio"], f"{lang}.mp3")
            )
            if not has_tts:
                missing_audio.append(lang)
        if missing_audio:
            raise RuntimeError(
                "多語音檔尚未完成：" + ",".join(missing_audio)
            )

        # 7. Put all final SRTs into the dedicated subtitle folder.
        publish_subtitles(drive, folders, workdir, task)

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
