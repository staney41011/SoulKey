import argparse
import os
import asyncio
import importlib.util
import hashlib
import json
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

# Windows production runners may inherit a CP950 console. Force UTF-8 so
# multilingual logs (including Hindi/Tamil and status symbols) can never
# abort the actual translation/TTS job.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from zoneinfo import ZoneInfo

from config import (
    COL,
    SPREADSHEET_ID,
    TASK_SHEET_RANGE,
    STATUS_SHEET_RANGE,
    TIMEZONE,
)
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
from lesson_paths import digits, resolve_lesson_folders

LANGUAGE_NAMES = {
    "en": "English",
    "th": "Thai",
    "es": "Spanish",
    "id": "Indonesian",
    "vi": "Vietnamese",
    "hi": "Hindi",
    "ta": "Tamil",
    "ja": "Japanese",
    "ko": "Korean",
    "km": "Khmer",
    "bn": "Bengali",
    "ne": "Nepali",
    "lo": "Lao",
    "my": "Burmese",
    "it": "Italian",
    "pt": "Portuguese (Brazil)",
}


class UpstreamTranslationNotReady(RuntimeError):
    """Target translation does not match the current English Final revision."""


from tts_fingerprint import segments_fingerprint
from natural_tts_config import (
    EDGE_TTS_VERSION,
    NATURAL_TTS_PROFILES,
    NATURAL_TTS_PROFILE_REVISION,
    DURATION_FIT_REVISION,
    MIN_NARRATION_TO_SOURCE_RATIO,
    MAX_SPEEDUP,
    MAX_SPEEDUP_BY_LANGUAGE,
)
from natural_tts_planner import build_speech_blocks
from natural_tts_edge import render_blocks, _ffprobe_duration
from smart_tts_fit import prepare_smart_narration
from natural_tts_assemble import assemble_preview, assemble_continuous_with_limit, wav_to_mp3, write_alignment_report
from status_io import new_run_id, mark_running, mark_done, mark_needs_review, mark_error


def now_text():
    return datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")


def pad_row(row, length=20):
    return list(row) + [""] * max(0, length - len(row))


def row_to_task(raw, sheet_row):
    row = pad_row(raw, 20)
    return {
        "sheet_row": sheet_row,
        "task_id": str(row[COL["task_id"]] or "").strip(),
        "period": digits(row[COL["period"]]),
        "lesson": str(row[COL["lesson"]] or "").strip(),
        "title": str(row[COL["title"]] or "").strip(),
        "lecturer": str(row[COL["lecturer"]] or "").strip(),
        "youtube_url": str(row[COL["youtube_url"]] or "").strip(),
        "en": str(row[COL["en"]] or "").strip(),
        "th": str(row[COL["th"]] or "").strip(),
        "es": str(row[COL["es"]] or "").strip(),
        "id": str(row[COL["id"]] or "").strip(),
        "vi": str(row[COL["vi"]] or "").strip(),
        "audio": str(row[COL["audio"]] or "").strip(),
    }


def latest_stage_status(sheets, task_id, stage):
    """Return the newest appended status row for one task/stage."""
    latest = None
    for raw in read_values(sheets, SPREADSHEET_ID, STATUS_SHEET_RANGE):
        row = list(raw) + [""] * max(0, 13 - len(raw))
        if (
            str(row[0] or "").strip() == str(task_id or "").strip()
            and str(row[1] or "").strip() == str(stage or "").strip()
        ):
            latest = {
                "status": str(row[2] or "").strip().lower(),
                "run_id": str(row[3] or "").strip(),
                "message": str(row[5] or "").strip(),
                "updated_at": str(row[8] or "").strip(),
            }
    return latest


def update_audio_status(sheets, row, status, note):
    update_cells(
        sheets,
        SPREADSHEET_ID,
        {
            f"任務佇列!P{row}": status,
            f"任務佇列!S{row}": now_text(),
            f"任務佇列!T{row}": note[:450],
        },
    )


def _english_overlap_key(token):
    import re
    return re.sub(
        r"^[^a-z0-9]+|[^a-z0-9]+$",
        "",
        str(token or "").lower(),
    )


def _trim_english_segment_overlap(previous_text, next_text):
    import re
    previous = re.sub(r"\s+", " ", str(previous_text or "")).strip().split()
    current = re.sub(r"\s+", " ", str(next_text or "")).strip().split()
    maximum = min(len(previous), len(current), 40)

    for size in range(maximum, 2, -1):
        left = [_english_overlap_key(x) for x in previous[-size:]]
        right = [_english_overlap_key(x) for x in current[:size]]
        if not all(left) or not all(right):
            continue
        if len(" ".join(left)) < 12:
            continue
        if left == right:
            return " ".join(current[size:]).strip()
    return " ".join(current).strip()


def _dedupe_english_segments_for_tts(segments):
    cleaned = []
    history = ""

    for index, source in enumerate(segments or []):
        item = dict(source)
        text = _trim_english_segment_overlap(
            history,
            item.get("text") or "",
        )
        if not text:
            continue
        item["text"] = text
        cleaned.append(item)
        history = (history + " " + text).strip()
        # Only a bounded suffix is needed for rolling-caption overlap checks.
        history = " ".join(history.split()[-120:])

    if len(cleaned) != len(segments or []):
        print(
            f"[TTS:en] rolling overlap cleanup: "
            f"{len(segments or [])} -> {len(cleaned)} segments",
            flush=True,
        )
    return cleaned


def load_translation_from_drive(drive, folder_id, lang, workdir):
    # TTS 永遠優先讀人工 Final；若該語言尚未建立 Final，
    # 才回退到既有 AI 翻譯稿。TTS 不負責重新翻譯。
    candidates = (
        ["en.final.json", "en.json"]
        if lang == "en"
        else [f"{lang}.final.json", f"{lang}.json"]
    )

    item = None
    selected_name = ""
    for name in candidates:
        item = find_file(drive, folder_id, name)
        if item:
            selected_name = name
            break

    if not item:
        raise RuntimeError(
            "找不到翻譯檔：" + " / ".join(candidates)
        )

    path = workdir / selected_name
    download_drive_file(drive, item["id"], path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    segments = payload.get("segments") or []
    if not segments:
        raise RuntimeError(f"{selected_name} 沒有 segments")

    if lang == "en":
        segments = _dedupe_english_segments_for_tts(segments)
        if not segments:
            raise RuntimeError(f"{selected_name} 去除重複後沒有可朗讀內容")

    print(
        f"[TTS:{lang}] 使用翻譯稿：{selected_name}",
        flush=True,
    )
    return segments, payload, selected_name


def load_english_final_fingerprint(drive, folder_id, workdir):
    item = find_file(drive, folder_id, "en.final.json")
    if not item:
        raise UpstreamTranslationNotReady(
            "找不到 en.final.json；非英文 TTS 必須等待 English Final"
        )

    path = Path(workdir) / "tts-current-en.final.json"
    download_drive_file(drive, item["id"], path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    segments = payload.get("segments") or []
    if not segments:
        raise UpstreamTranslationNotReady("en.final.json 沒有 segments")
    return segments_fingerprint(segments)


def validate_translation_revision(lang, payload, selected_name, en_source_sha256):
    if lang == "en":
        return

    declared_source = str(payload.get("source") or "").strip()
    declared_sha = str(
        payload.get("source_sha256")
        or payload.get("approved_source_sha256")
        or ""
    ).strip()

    if declared_source != "en.final.json":
        raise UpstreamTranslationNotReady(
            f"{selected_name} 不是由 en.final.json 產生；"
            "等待最新 multi 翻譯完成"
        )

    if not declared_sha:
        raise UpstreamTranslationNotReady(
            f"{selected_name} 缺少 source_sha256；"
            "屬於舊版翻譯輸出，必須重跑 multi"
        )

    if declared_sha != en_source_sha256:
        raise UpstreamTranslationNotReady(
            f"{selected_name} 的 English Final 版本已過期；"
            f"translation={declared_sha[:12]}，"
            f"current={en_source_sha256[:12]}；等待 multi 重跑"
        )


def _ensure_edge_tts_runtime():
    if importlib.util.find_spec("edge_tts") is not None:
        return
    print(
        f"[TTS] 安裝 edge-tts=={EDGE_TTS_VERSION}（CPU / Internet runtime）",
        flush=True,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-q",
            f"edge-tts=={EDGE_TTS_VERSION}",
        ],
        check=True,
    )



def load_source_duration_limit(drive, source_folder, workdir):
    """Prefer exact original-video duration from source_info.json."""
    item = find_file(drive, source_folder, "source_info.json")
    if not item:
        return None, "source_timestamp_fallback"

    path = Path(workdir) / "source_info.tts.json"
    try:
        download_drive_file(drive, item["id"], path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        duration = float(payload.get("duration") or 0)
        if duration > 0:
            return duration, "source_info.duration"
    except Exception as exc:
        print(
            f"[TTS] source_info.json duration 讀取失敗，改用 timestamp："
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
    return None, "source_timestamp_fallback"


def _load_tts_manifest(drive, audio_folder, lang, workdir):
    item = find_file(drive, audio_folder, f"{lang}.tts_manifest.json")
    if not item:
        return None
    path = workdir / f"{lang}.existing.tts_manifest.json"
    try:
        download_drive_file(drive, item["id"], path)
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _verified_drive_audio(drive, audio_folder, filename, expected_receipt=None):
    """Confirm nonempty audio and, for new manifests, EXACT uploaded bytes.

    Old manifests lacked checksums. Keep them readable and reusable, so
    introducing stronger verification never destroys an existing approved MP3
    when an upstream voice service is temporarily unavailable.
    """
    item=find_file(drive,audio_folder,filename)
    if not item or not item.get("id"):
        return False
    meta=drive.files().get(
        fileId=item["id"],fields="id,size,mimeType,md5Checksum",
        supportsAllDrives=True
    ).execute()
    actual_size=int(meta.get("size") or 0)
    if actual_size<=1024 or str(meta.get("mimeType") or "") not in {
        "audio/mpeg","audio/mp3","audio/x-wav","audio/wav","application/octet-stream"
    }:
        return False
    if expected_receipt is not None:
        if not isinstance(expected_receipt,dict):
            return False
        # Missing hash fields are not a successful verified upload.
        expected_md5=str(expected_receipt.get("md5") or "").strip().lower()
        expected_size=int(expected_receipt.get("size") or 0)
        if not expected_md5 or actual_size!=expected_size:
            return False
        if str(meta.get("md5Checksum") or "").strip().lower()!=expected_md5:
            return False
    return True


def local_audio_receipt(path):
    """Drive exposes MD5 for uploaded binary files; compare with local output."""
    path=Path(path)
    digest=hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b""):
            digest.update(chunk)
    return {"size":path.stat().st_size,"md5":digest.hexdigest()}



def verify_uploaded_natural_output(
    drive,audio_folder,lang,source_sha256,duration_limit,workdir
):
    """Re-read committed Drive manifest + MP3; report approved/review/missing."""
    manifest=_load_tts_manifest(drive,audio_folder,lang,workdir)
    profile=NATURAL_TTS_PROFILES[lang]
    if not isinstance(manifest,dict):
        return "missing"
    expected={
        "engine":"edge-natural-v2",
        "profile_revision":NATURAL_TTS_PROFILE_REVISION,
        "source_sha256":str(source_sha256),
        "voice":str(profile["voice"]),
        "rate":str(profile["rate"]),
        "pitch":str(profile["pitch"]),
        "assembly_policy":"continuous_total_duration",
    }
    if any(str(manifest.get(k) or "")!=value for k,value in expected.items()):
        return "missing"
    if abs(float(manifest.get("duration_limit_seconds") or 0)
           -float(duration_limit or 0))>0.5:
        return "missing"
    status=str(manifest.get("status") or "")
    receipts=manifest.get("audio_receipts")
    if receipts is not None and not isinstance(receipts,dict):
        return "missing"
    if status=="done":
        return ("done" if
            _verified_drive_audio(
                drive,audio_folder,f"{lang}.mp3",
                (receipts or {}).get("mp3") if receipts is not None else None
            ) and _verified_drive_audio(
                drive,audio_folder,f"{lang}.wav",
                (receipts or {}).get("wav") if receipts is not None else None
            ) else "missing")
    if status=="needs_review":
        return ("needs_review" if _verified_drive_audio(
            drive,audio_folder,f"{lang}.preview.mp3",
            (receipts or {}).get("preview_mp3")
                if receipts is not None else None
        ) else "missing")
    return "missing"


def existing_natural_output(
    drive,
    audio_folder,
    lang,
    source_sha256,
    duration_limit,
    workdir,
    *,
    request_duration_fit=False,
):
    manifest = _load_tts_manifest(
        drive,
        audio_folder,
        lang,
        workdir,
    )
    if not manifest:
        return False

    profile = NATURAL_TTS_PROFILES[lang]
    if str(manifest.get("engine") or "") != "edge-natural-v2":
        return False
    if str(manifest.get("profile_revision") or "") != NATURAL_TTS_PROFILE_REVISION:
        return False
    if str(manifest.get("source_sha256") or "") != str(source_sha256 or ""):
        return False
    if str(manifest.get("voice") or "") != str(profile.get("voice") or ""):
        return False
    if str(manifest.get("rate") or "") != str(profile.get("rate") or ""):
        return False
    if str(manifest.get("pitch") or "") != str(profile.get("pitch") or ""):
        return False
    if str(manifest.get("status") or "") != "done":
        return False
    if str(manifest.get("assembly_policy") or "") != "continuous_total_duration":
        return False
    # Only the explicitly requested P257-L04 short narrations should refit
    # existing audio. Once reprocessed, the manifest revision prevents loops.
    # Unrelated completed lessons are never silently rebuilt.
    if request_duration_fit and str(manifest.get("duration_fit_revision") or "") != DURATION_FIT_REVISION:
        timeline=manifest.get("timeline") or {}
        old_duration=float(timeline.get("final_duration") or 0)
        if 0 < old_duration < float(duration_limit) * MIN_NARRATION_TO_SOURCE_RATIO:
            return False
    old_limit = float(manifest.get("duration_limit_seconds") or 0)
    if abs(old_limit - float(duration_limit or 0)) > 0.5:
        return False

    return (verify_uploaded_natural_output(
        drive,audio_folder,lang,source_sha256,duration_limit,workdir
    )=="done")


def render_natural_language(
    segments,
    lang,
    output_dir,
    *,
    source_duration,
    duration_limit_basis,
    checkpoint_store=None,
    smart_fit_pilot=False,
):
    _ensure_edge_tts_runtime()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    blocks, overlap_report = build_speech_blocks(segments, lang)
    if not blocks:
        raise RuntimeError(f"{lang} 沒有可朗讀的 speech blocks")

    if checkpoint_store is not None:
        try:
            checkpoint_store.restore(output_dir)
        except Exception as cache_exc:
            print(
                f"[TTS-CACHE] Restore unavailable for {lang}: "
                f"{type(cache_exc).__name__}; continuing without remote cache",
                flush=True,
            )
            checkpoint_store = None

    block_results, wav_parts = asyncio.run(
        render_blocks(
            lang=lang,
            blocks=blocks,
            output_dir=output_dir,
            checkpoint_store=checkpoint_store,
        )
    )

    preview_wav = output_dir / f"{lang}.preview.wav"
    preview_mp3 = output_dir / f"{lang}.preview.mp3"
    smart = None
    if smart_fit_pilot:
        def _smart_gemini_client():
            from gemini_engine import GeminiClient, DEFAULT_TEXT_MODEL
            key = str(os.environ.get("GEMINI_API_KEY") or "").strip()
            if not key:
                key = get_secret("GEMINI_API_KEY", required=False)
            if not key:
                raise RuntimeError("Gemini key unavailable for smart TTS rewriting")
            return GeminiClient(api_key=key, text_model=DEFAULT_TEXT_MODEL)
        smart = prepare_smart_narration(
            language=lang, blocks=blocks, block_results=block_results,
            wav_parts=wav_parts, source_duration=source_duration,
            output_dir=output_dir, client_factory=_smart_gemini_client,
        )
        blocks = smart["blocks"]
        block_results = smart["block_results"]
        wav_parts = smart["wav_parts"]
        preview_wav = smart["preview_wav"]
        preview_info = smart["preview"]
        print(
            f"[SMART-FIT:{lang}] rounds={len(smart['report']['passes'])}; "
            f"rewritten={smart['report']['modified_blocks']}; "
            f"preview={preview_info['duration']:.2f}s; "
            f"limit={float(source_duration):.2f}s",
            flush=True,
        )
    else:
        preview_info = assemble_preview(wav_parts, preview_wav)

    source_duration = float(source_duration)
    timeline_wav = output_dir / f"{lang}.wav"
    timeline_mp3 = output_dir / f"{lang}.mp3"
    timeline_info = assemble_continuous_with_limit(
        preview_wav,
        timeline_wav,
        source_duration=source_duration,
        max_speedup=(1.0 if smart_fit_pilot else MAX_SPEEDUP_BY_LANGUAGE.get(lang, MAX_SPEEDUP)),
        min_duration_ratio=(0.0 if smart_fit_pilot else MIN_NARRATION_TO_SOURCE_RATIO),
        max_slowdown=(1.0 if smart_fit_pilot else 1.18),
    )
    # Smart fit never forces audio speed or stretches a short recording.
    # Even an apparently successful WAV must pass actual encoded MP3 timing.
    # Only ONE MP3 encoding is needed: the approved time-fitted recording,
    # or the full natural review recording when time fitting is not safe.
    if timeline_info["needs_review"]:
        wav_to_mp3(preview_wav, preview_mp3)
    else:
        wav_to_mp3(timeline_wav, timeline_mp3)
        if smart_fit_pilot:
            encoded_seconds = _ffprobe_duration(timeline_mp3)
            timeline_info["encoded_mp3_duration"] = round(encoded_seconds, 3)
            if encoded_seconds > source_duration:
                # No trimming spoken content. Keep the candidate as review.
                timeline_info["needs_review"] = True
                timeline_info["over_source"] = round(encoded_seconds - source_duration, 3)
                wav_to_mp3(preview_wav, preview_mp3)
                timeline_mp3.unlink(missing_ok=True)
                if smart is not None:
                    smart["report"]["within_source_limit_with_margin"] = False
                    smart["report"]["needs_review_reason"] = "encoded_mp3_exceeds_original"
    if smart is not None:
        smart["report"]["final_status"] = (
            "needs_review" if timeline_info["needs_review"] else "done"
        )
        smart["report_path"].write_text(
            json.dumps(smart["report"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    alignment_path = output_dir / f"{lang}.alignment_report.json"
    write_alignment_report(
        alignment_path,
        preview=preview_info,
        timeline=timeline_info,
    )

    profile = NATURAL_TTS_PROFILES[lang]
    source_sha256 = segments_fingerprint(segments)
    status = "needs_review" if timeline_info["needs_review"] else "done"
    manifest = {
        "version": 2,
        "engine": "edge-natural-v2",
        "edge_tts_version": EDGE_TTS_VERSION,
        "profile_revision": NATURAL_TTS_PROFILE_REVISION,
        "language": lang,
        "voice": profile["voice"],
        "rate": profile["rate"],
        "pitch": profile["pitch"],
        "source_sha256": source_sha256,
        "source_segment_count": len(segments),
        "block_count": len(blocks),
        "assembly_policy": "continuous_total_duration",
        "duration_fit_revision": DURATION_FIT_REVISION,
        "max_speedup": (1.0 if smart_fit_pilot else MAX_SPEEDUP_BY_LANGUAGE.get(lang, MAX_SPEEDUP)),
        "smart_fit_mode": ("a_b_pilot" if smart_fit_pilot else "legacy"),
        "smart_fit": (smart["report"] if smart is not None else None),
        "duration_limit_basis": duration_limit_basis,
        "duration_limit_seconds": round(source_duration, 3),
        "overlap_cleanup": overlap_report,
        "blocks": block_results,
        "preview": preview_info,
        "timeline": timeline_info,
        "status": status,
        "audio_receipts": (
            {"preview_mp3": local_audio_receipt(preview_mp3)}
            if status == "needs_review"
            else {
                "mp3": local_audio_receipt(timeline_mp3),
                "wav": local_audio_receipt(timeline_wav),
            }
        ),
    }
    manifest_path = output_dir / f"{lang}.tts_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "mp3": timeline_mp3,
        "wav": timeline_wav,
        "preview_mp3": preview_mp3,
        "manifest": manifest_path,
        "alignment_report": alignment_path,
        "status": status,
        "source_sha256": source_sha256,
        "block_count": len(blocks),
        "timeline": timeline_info,
        "preview": preview_info,
        **({
            "narration_script": smart["script_path"],
            "smart_fit_report": smart["report_path"],
        } if smart is not None else {}),
    }


def upload_natural_outputs(
    drive,
    audio_folder,
    result,
    task,
):
    # Publish AUDIO first, manifest last. Never commit a new manifest
    # pointing at a missing / stale MP3 if Drive errors partway through.
    # The manifest's audio_receipts let post-upload checks compare full
    # binary MD5 and file length against Google's Drive metadata.
    order = (
        ("preview_mp3", "alignment_report", "manifest")
        if result["status"]=="needs_review"
        else ("mp3", "wav", "alignment_report", "manifest")
    )
    if result.get("smart_fit_report") is not None:
        # The full original translation is not overwritten.
        order = ("narration_script", "smart_fit_report") + order
    for key in order:
        path=Path(result[key])
        canonical_name=path.name
        upload_or_replace_file(
            drive,audio_folder,path,canonical_name,
            display_name=formal_drive_name(task,canonical_name)
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", default=None)
    parser.add_argument("--period", type=int, default=None)
    parser.add_argument("--lang", choices=list(LANGUAGE_NAMES), default=None)
    parser.add_argument(
        "--langs",
        default=None,
        help="逗號分隔多語言，例如 en,es；只處理指定語言",
    )
    parser.add_argument("--all-langs", action="store_true")
    parser.add_argument("--max-tasks", type=int, default=1)
    parser.add_argument("--force", action="store_true")
    smart_mode = parser.add_mutually_exclusive_group()
    smart_mode.add_argument(
        "--smart-fit-pilot", action="store_true", dest="smart_fit_pilot",
        default=True,
        help="A+B semantic narration fitting (production default).",
    )
    smart_mode.add_argument(
        "--legacy-tts-timing", action="store_false", dest="smart_fit_pilot",
        help="Emergency compatibility override; not for normal production.",
    )
    parser.add_argument(
        "--strict-delivery", action="store_true",
        help="Return nonzero unless every requested language has a verified Drive MP3."
    )
    args = parser.parse_args()

    if sum(bool(x) for x in [args.lang, args.langs, args.all_langs]) != 1:
        parser.error("請擇一指定 --lang、--langs en,es 或 --all-langs")

    if args.all_langs:
        langs = list(LANGUAGE_NAMES)
    elif args.langs:
        langs = [x.strip() for x in args.langs.split(",") if x.strip()]
        invalid = [x for x in langs if x not in LANGUAGE_NAMES]
        if invalid:
            parser.error("不支援的語言代碼：" + ",".join(invalid))
        # 去重但保留順序
        langs = list(dict.fromkeys(langs))
    else:
        langs = [args.lang]

    print("=" * 72)
    print("打開心靈的鎖匙｜多語 TTS")
    print("引擎：SoulKey Natural TTS v2 / Edge Neural（Final 翻譯為唯一內容來源）")
    print("=" * 72)

    drive, sheets = build_google_services()
    rows = read_values(sheets, SPREADSHEET_ID, TASK_SHEET_RANGE)

    tasks = []
    for index, raw in enumerate(rows, start=2):
        task = row_to_task(raw, index)
        if not task["task_id"] or task["period"] is None or not task["lesson"]:
            continue
        if args.period is not None and task["period"] != args.period:
            continue
        if args.task_id and task["task_id"] != args.task_id:
            continue
        tasks.append(task)

    if not tasks:
        print("沒有符合條件的任務。")
        return 0

    processed = 0
    any_failed = False
    strict_missing = []
    strict_review = []
    for task in tasks:
        if processed >= args.max_tasks:
            break

        print("")
        print("-" * 72)
        print(f"[TASK] {task['task_id']} / 第{task['period']}期 / {task['lesson']}")

        status_stage = "tts"
        run_id = new_run_id(task["task_id"], status_stage)
        mark_running(
            task["task_id"],
            status_stage,
            sheets=sheets,
            run_id=run_id,
            message="音檔生成中：" + ",".join(langs),
            progress=0,
        )

        try:
            folders = resolve_lesson_folders(
                drive,
                sheets,
                task["period"],
                task["lesson"],
            )
            workdir = Path(os.environ.get("SOULKEY_TTS_WORKDIR", "/kaggle/working/translate-system-tts")) / task["task_id"]
            workdir.mkdir(parents=True, exist_ok=True)

            video_duration, duration_limit_basis = load_source_duration_limit(
                drive,
                folders["source"],
                workdir,
            )
            en_source_sha256 = None
            latest_multi = None
            if any(lang != "en" for lang in langs):
                latest_multi = latest_stage_status(
                    sheets,
                    task["task_id"],
                    "multi",
                )
                en_source_sha256 = load_english_final_fingerprint(
                    drive,
                    folders["translation"],
                    workdir,
                )

            update_audio_status(
                sheets,
                task["sheet_row"],
                "處理中",
                "多語音檔生成中",
            )

            completed = []
            failed = []
            blocked = []
            over_duration = []
            tts_completed = []
            voice_access_denials = 0

            for lang in langs:
                lang_stage = f"tts:{lang}"
                lang_run_id = new_run_id(task["task_id"], lang_stage)
                mark_running(
                    task["task_id"],
                    lang_stage,
                    sheets=sheets,
                    run_id=lang_run_id,
                    message=f"{LANGUAGE_NAMES[lang]} Natural TTS 生成中",
                    progress=0,
                )

                try:
                    if lang != "en":
                        multi_status = str((latest_multi or {}).get("status") or "")
                        if multi_status != "done":
                            raise UpstreamTranslationNotReady(
                                "最新 multi 狀態不是 done"
                                + (f"（目前={multi_status}）" if multi_status else "（目前無狀態）")
                                + "；非英文 TTS 必須等待多語翻譯完成"
                            )

                    segments, translation_payload, selected_name = load_translation_from_drive(
                        drive,
                        folders["translation"],
                        lang,
                        workdir,
                    )
                    if lang != "en":
                        validate_translation_revision(
                            lang,
                            translation_payload,
                            selected_name,
                            en_source_sha256,
                        )
                    source_sha256 = segments_fingerprint(segments)
                    if args.smart_fit_pilot and not video_duration:
                        raise RuntimeError(
                            "Smart TTS requires original source_info.json duration; "
                            "translation timestamps cannot prove the video hard limit"
                        )
                    duration_limit = (
                        float(video_duration)
                        if video_duration
                        else max(float(seg.get("end", 0) or 0) for seg in segments)
                    )
                    effective_duration_basis = (
                        duration_limit_basis
                        if video_duration
                        else "last_approved_source_timestamp"
                    )

                    if (
                        not args.force and not args.smart_fit_pilot
                        and existing_natural_output(
                            drive,
                            folders["audio"],
                            lang,
                            source_sha256,
                            duration_limit,
                            workdir,
                            request_duration_fit=(
                                task["task_id"]=="P257-L04" and
                                lang in {"en","es","th","id","km","vi"}
                            ),
                        )
                    ):
                        print(
                            f"[TTS:{lang}] Drive 已有相同 Final / voice 的 Natural TTS v2，略過重做",
                            flush=True,
                        )
                        completed.append(lang)
                        tts_completed.append(lang)
                        mark_done(
                            task["task_id"],
                            lang_stage,
                            sheets=sheets,
                            run_id=lang_run_id,
                            message=(
                                f"{LANGUAGE_NAMES[lang]} Natural TTS v2 "
                                "來源與聲線版本一致，略過重做"
                            ),
                        )
                        continue

                    if not args.force and not args.smart_fit_pilot and verify_uploaded_natural_output(
                        drive,folders["audio"],lang,source_sha256,
                        duration_limit,workdir
                    )=="needs_review":
                        # A complete natural preview is valid listening output.
                        # Do not synthesize it repeatedly when another
                        # language is being retried: keep its QA status clear.
                        manifest=_load_tts_manifest(
                            drive,folders["audio"],lang,workdir
                        ) or {}
                        timeline=manifest.get("timeline") or {}
                        over_duration.append({
                            "lang":lang,
                            "over":float(timeline.get("over_source") or 0),
                            "required_speedup":float(
                                timeline.get("required_speedup") or 1
                            ),
                        })
                        completed.append(lang)
                        tts_completed.append(lang)
                        mark_needs_review(
                            task["task_id"],lang_stage,
                            sheets=sheets,run_id=lang_run_id,
                            message=f"{LANGUAGE_NAMES[lang]} full natural "
                                "preview MP3 already verified on Drive; "
                                "video timing review still needed"
                        )
                        print(
                            f"[TTS-DRIVE-VERIFIED] {lang}=needs_review "
                            "(reused previous full natural preview)",flush=True
                        )
                        continue

                    if voice_access_denials >= 2:
                        raise RuntimeError(
                            "Microsoft Edge TTS WebSocket HTTP 403: "
                            "兩種不同語言連續遭語音服務拒絕，"
                            "已停止其他聲線的無效重試；請待服務恢復。"
                        )
                    print(
                        f"[TTS] {LANGUAGE_NAMES[lang]} ({lang}) / "
                        f"{NATURAL_TTS_PROFILES[lang]['voice']}",
                        flush=True,
                    )
                    cloud_cache = None
                    if os.environ.get("SOULKEY_TTS_PARALLEL_BLOCKS", "1") in {
                        "2", "3", "4"
                    }:
                        from natural_tts_drive_cache import DriveTTSBlockCache
                        language_blocks, _ = build_speech_blocks(segments, lang)
                        cloud_cache = DriveTTSBlockCache(
                            drive, folders["audio"], lang, source_sha256,
                            language_blocks, workdir / f"tts-cache-{lang}",
                        )
                    result = render_natural_language(
                        segments,
                        lang,
                        workdir / (
                            f"natural-tts-smart-pilot-{lang}" if args.smart_fit_pilot
                            else f"natural-tts-{lang}"
                        ),
                        source_duration=duration_limit,
                        duration_limit_basis=effective_duration_basis,
                        checkpoint_store=cloud_cache,
                        smart_fit_pilot=args.smart_fit_pilot,
                    )
                    if args.smart_fit_pilot and result["status"] == "needs_review":
                        # Never publish an overlong audio file to the shared
                        # folder. Retain review report + spoken script only,
                        # preserving an existing approved canonical MP3.
                        for key in ("narration_script", "smart_fit_report"):
                            path = Path(result[key])
                            upload_or_replace_file(
                                drive, folders["audio"], path, path.name,
                                display_name=formal_drive_name(task, path.name),
                            )
                    else:
                        upload_natural_outputs(
                            drive, folders["audio"], result, task,
                        )
                    # An API upload call returning is not enough. Re-fetch
                    # the Drive manifest + nonempty MP3 before marking done.
                    delivered=(
                        "needs_review"
                        if args.smart_fit_pilot and result["status"] == "needs_review"
                           and all(find_file(drive, folders["audio"], Path(result[key]).name)
                                   for key in ("narration_script", "smart_fit_report"))
                        else verify_uploaded_natural_output(
                            drive,folders["audio"],lang,source_sha256,
                            duration_limit,workdir
                        )
                    )
                    if delivered != result["status"]:
                        raise RuntimeError(
                            f"Drive audio delivery mismatch for {lang}: "
                            f"expected={result['status']} actual={delivered}"
                        )
                    print(f"[TTS-DRIVE-VERIFIED] {lang}={delivered}",flush=True)
                    completed.append(lang)
                    tts_completed.append(lang)

                    timeline = result["timeline"]
                    if result["status"] == "needs_review":
                        over_duration.append({
                            "lang": lang,
                            "over": float(timeline["over_source"]),
                            "required_speedup": float(timeline["required_speedup"]),
                        })
                        note = (
                            f"{LANGUAGE_NAMES[lang]} 智慧精簡未達時長驗收；"
                            f"自然長度={timeline['natural_duration']:.1f}s，"
                            f"影片上限={timeline['source_duration']:.1f}s；"
                            "未發布超時 MP3，已保留完整文稿與審核報告；"
                            "若有舊版正式檔案則維持不變"
                        )
                        mark_needs_review(
                            task["task_id"],
                            lang_stage,
                            sheets=sheets,
                            run_id=lang_run_id,
                            message=note,
                        )
                    else:
                        note = (
                            f"{LANGUAGE_NAMES[lang]} Natural TTS v2 完成；"
                            f"blocks={result['block_count']}；"
                            f"自然朗讀={timeline['natural_duration']:.1f}s；"
                            f"正式音檔={timeline['final_duration']:.1f}s；"
                            f"影片上限={timeline['source_duration']:.1f}s；"
                            f"調速={timeline['applied_speedup']:.3f}x"
                        )
                        mark_done(
                            task["task_id"],
                            lang_stage,
                            sheets=sheets,
                            run_id=lang_run_id,
                            message=note,
                        )

                except UpstreamTranslationNotReady as lang_exc:
                    lang_message = str(lang_exc)
                    blocked.append({"lang": lang, "reason": lang_message})
                    print(
                        f"[WAIT] TTS:{lang} 等待最新 multi：{lang_message}",
                        flush=True,
                    )
                    mark_needs_review(
                        task["task_id"],
                        lang_stage,
                        sheets=sheets,
                        run_id=lang_run_id,
                        message=(
                            f"{LANGUAGE_NAMES[lang]} 尚未配音："
                            "等待與目前 English Final 相符的 multi 翻譯；"
                            + lang_message
                        ),
                    )
                    continue

                except Exception as lang_exc:
                    lang_message = f"{type(lang_exc).__name__}: {lang_exc}"
                    if "Microsoft Edge TTS WebSocket HTTP 403" in lang_message:
                        voice_access_denials += 1
                        if voice_access_denials == 2:
                            print(
                                "[TTS-OUTAGE] Two voice profiles returned "
                                "provider HTTP 403. Keep completed files "
                                "unchanged; mark remaining new voices as "
                                "blocked instead of opening more connections.",
                                file=sys.stderr,flush=True
                            )
                    failed.append({"lang": lang, "error": lang_message})
                    print(
                        f"[ERROR] Natural TTS:{lang} 失敗，但其他語言繼續："
                        f"{lang_message}",
                        file=sys.stderr,
                        flush=True,
                    )
                    mark_error(
                        task["task_id"],
                        lang_stage,
                        sheets=sheets,
                        run_id=lang_run_id,
                        exc=lang_exc,
                    )
                    continue

            youtube_probe_note = "YouTube 音軌僅作 benchmark，不作正式音檔來源"

            if failed:
                status = "部分完成"
                failure_details = "｜".join(
                    f"{item['lang']}={item['error']}"
                    for item in failed
                )
                note = (
                    f"音檔完成：{','.join(completed) or '無'}；"
                    f"音源政策：{youtube_probe_note}；"
                    f"Natural TTS：{','.join(tts_completed) or '無'}；"
                    f"失敗：{','.join(x['lang'] for x in failed)}；"
                    f"原因：{failure_details}；"
                    "單一語言錯誤不阻擋其他語言"
                )
                if over_duration:
                    note += "；另有超時：" + ",".join(
                        f"{item['lang']}+{item['over']:.1f}s"
                        for item in over_duration
                    )
            elif blocked or over_duration:
                status = "待人工確認"
                blocked_text = ",".join(
                    f"{item['lang']}=等待multi"
                    for item in blocked
                )
                over_text = ",".join(
                    f"{item['lang']}+{item['over']:.1f}s"
                    for item in over_duration
                )
                notes = [
                    f"音檔完成：{','.join(completed) or '無'}",
                    f"音源政策：{youtube_probe_note}",
                    f"Natural TTS：{','.join(tts_completed) or '無'}",
                ]
                if blocked_text:
                    notes.append(f"等待最新 multi：{blocked_text}")
                if over_text:
                    notes.append(f"超過原片總長：{over_text}")
                note = "；".join(notes)
            elif len(completed) == len(langs):
                status = "完成"
                note = (
                    f"音檔完成：{','.join(completed)}；"
                    f"音源政策：{youtube_probe_note}；"
                    f"Natural TTS：{','.join(tts_completed) or '無'}"
                )
            else:
                status = "部分完成"
                note = (
                    f"音檔完成：{','.join(completed)}；"
                    f"音源政策：{youtube_probe_note}；"
                    f"Natural TTS：{','.join(tts_completed) or '無'}"
                )

            update_audio_status(
                sheets,
                task["sheet_row"],
                status,
                note,
            )

            if args.strict_delivery:
                strict_missing.extend(
                    f"{task['task_id']}:{x['lang']}"
                    for x in (failed + blocked)
                )
                strict_review.extend(
                    f"{task['task_id']}:{x['lang']}"
                    for x in over_duration
                )
                # An unaccounted-for selection must never be reported done.
                accounted={x for x in completed}
                accounted.update(x["lang"] for x in failed + blocked)
                strict_missing.extend(
                    f"{task['task_id']}:{lang}" for lang in langs
                    if lang not in accounted
                )

            if failed:
                # A single language can fail while the other requested
                # languages remain valid deliverables. Keep the aggregate
                # audio stage as needs_review / partial instead of turning the
                # entire Kaggle worker into a technical failure. The failed
                # language keeps its own tts:<lang> error status.
                mark_needs_review(
                    task["task_id"],
                    status_stage,
                    sheets=sheets,
                    run_id=run_id,
                    message=note,
                )
            elif status == "完成":
                mark_done(
                    task["task_id"],
                    status_stage,
                    sheets=sheets,
                    run_id=run_id,
                    message=note,
                )
            else:
                mark_needs_review(
                    task["task_id"],
                    status_stage,
                    sheets=sheets,
                    run_id=run_id,
                    message=note,
                )

            processed += 1

        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            print(f"[ERROR] {message}", file=sys.stderr)
            traceback.print_exc()
            update_audio_status(
                sheets,
                task["sheet_row"],
                "錯誤",
                message,
            )
            mark_error(
                task["task_id"],
                status_stage,
                sheets=sheets,
                run_id=run_id,
                exc=exc,
            )
            any_failed = True
            processed += 1

    print("")
    print("TTS 本次處理完成。")
    if args.strict_delivery and strict_missing:
        print(
            "[TTS-DELIVERY-MISSING] " + ",".join(dict.fromkeys(strict_missing)),
            file=sys.stderr,flush=True
        )
        return 2
    if args.strict_delivery and strict_review:
        print(
            "[TTS-DELIVERY-NEEDS-REVIEW] "
            + ",".join(dict.fromkeys(strict_review)),
            flush=True
        )
        return 3

    if any_failed:
        print(
            "[TTS ERROR] 發生工作層級錯誤；請查看狀態與 log。",
            file=sys.stderr,
            flush=True,
        )
        return 1

    print(
        "[TTS] 音檔階段結束；單一語言若失敗會保留為 needs_review，"
        "不再讓整個 Kaggle Job 失敗。",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
