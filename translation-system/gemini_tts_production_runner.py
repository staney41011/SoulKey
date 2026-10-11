import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import traceback
import wave
import zipfile
from array import array
from datetime import datetime
from pathlib import Path

from config import COL, SPREADSHEET_ID, TASK_SHEET_RANGE
from gemini_engine import DEFAULT_TTS_MODEL, GeminiClient
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
from status_io import new_run_id, mark_done, mark_error, mark_needs_review, mark_running


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
}
VOICE = os.getenv("GEMINI_TTS_VOICE", "Kore")
MAX_CHARS = int(os.getenv("GEMINI_TTS_MAX_CHARS", "3500"))
TTS_CHECKPOINT_VERSION = 1


def pad_row(row, length=20):
    return list(row) + [""] * max(0, length - len(row))


def find_task(sheets, task_id):
    for index, raw in enumerate(read_values(sheets, SPREADSHEET_ID, TASK_SHEET_RANGE), start=2):
        row = pad_row(raw, 20)
        if str(row[COL["task_id"]] or "").strip() == task_id:
            return {
                "sheet_row": index,
                "task_id": task_id,
                "period": digits(row[COL["period"]]),
                "lesson": str(row[COL["lesson"]] or "").strip(),
            }
    return None


def source_fingerprint(segments):
    payload = [
        {
            "id": int(seg.get("id", i)),
            "text": re.sub(r"\\s+", " ", str(seg.get("text") or "")).strip(),
        }
        for i, seg in enumerate(segments)
    ]
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def tts_checkpoint_name(lang):
    return f"{lang}.tts_checkpoint.json"


def tts_part_name(lang, index):
    return f"{lang}.tts.part.{int(index):04d}.wav"


def existing_final_tts(drive, audio_folder_id, lang):
    names = [
        f"{lang}.wav",
        f"{lang}.mp3",
        f"{lang}.tts_manifest.json",
    ]
    found = [find_file(drive, audio_folder_id, name) for name in names]
    return all(found)


def load_tts_checkpoint(drive, audio_folder_id, lang, local_dir):
    item = find_file(drive, audio_folder_id, tts_checkpoint_name(lang))
    if not item:
        return None

    path = local_dir / tts_checkpoint_name(lang)
    download_drive_file(drive, item["id"], path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    if int(payload.get("version") or 0) != TTS_CHECKPOINT_VERSION:
        return None
    return payload


def save_tts_checkpoint(drive, audio_folder_id, lang, local_dir, payload):
    path = local_dir / tts_checkpoint_name(lang)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    upload_or_replace_file(
        drive,
        audio_folder_id,
        path,
        tts_checkpoint_name(lang),
    )


def load_segments(drive, folder_id, lang, workdir):
    names = ["en.final.json", "en.json"] if lang == "en" else [f"{lang}.json"]
    for name in names:
        item = find_file(drive, folder_id, name)
        if not item:
            continue
        path = workdir / name
        download_drive_file(drive, item["id"], path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        segments = payload.get("segments") or []
        if segments:
            print(f"[TTS:{lang}] source={name}", flush=True)
            return segments
    raise RuntimeError(f"找不到 {lang} TTS 文字來源")


def split_text_segments(segments, max_chars=MAX_CHARS):
    chunks = []
    current = []
    chars = 0

    for seg in segments:
        text = re.sub(r"\s+", " ", str(seg.get("text") or "")).strip()
        if not text:
            continue

        if current and chars + len(text) + 1 > max_chars:
            chunks.append(current)
            current = []
            chars = 0

        current.append({
            "id": int(seg.get("id", len(current))),
            "start": float(seg.get("start") or 0),
            "end": float(seg.get("end") or 0),
            "text": text,
        })
        chars += len(text) + 1

    if current:
        chunks.append(current)

    if not chunks:
        raise RuntimeError("TTS 沒有可朗讀文字")
    return chunks


def read_wav(path):
    with wave.open(str(path), "rb") as wf:
        params = {
            "nchannels": wf.getnchannels(),
            "sampwidth": wf.getsampwidth(),
            "framerate": wf.getframerate(),
            "comptype": wf.getcomptype(),
        }
        frames = wf.readframes(wf.getnframes())
    return params, frames


def concatenate_wavs(paths, output_path, pause_seconds=0.18, target_duration=None):
    first_params = None
    all_frames = bytearray()

    for index, path in enumerate(paths):
        params, frames = read_wav(path)
        if first_params is None:
            first_params = params
        if params != first_params:
            raise RuntimeError(f"Gemini TTS WAV 參數不一致：{path}")
        all_frames.extend(frames)

        if index < len(paths) - 1:
            samples = int(first_params["framerate"] * pause_seconds)
            frame_bytes = first_params["nchannels"] * first_params["sampwidth"]
            all_frames.extend(b"\x00" * samples * frame_bytes)

    frame_bytes = first_params["nchannels"] * first_params["sampwidth"]
    total_samples = len(all_frames) // frame_bytes
    speech_duration = total_samples / first_params["framerate"]

    within_source_duration = True
    remaining_silence = 0.0
    over_by_seconds = 0.0

    if target_duration and target_duration > 0:
        if speech_duration < target_duration:
            remaining_silence = target_duration - speech_duration
            pad_samples = int(first_params["framerate"] * remaining_silence)
            all_frames.extend(b"\x00" * pad_samples * frame_bytes)
        elif speech_duration > target_duration:
            within_source_duration = False
            over_by_seconds = speech_duration - target_duration

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as wf:
        wf.setnchannels(first_params["nchannels"])
        wf.setsampwidth(first_params["sampwidth"])
        wf.setframerate(first_params["framerate"])
        wf.setcomptype(first_params["comptype"], "not compressed")
        wf.writeframes(bytes(all_frames))

    full_duration = (
        len(all_frames) // frame_bytes / first_params["framerate"]
    )

    return {
        "sample_rate": first_params["framerate"],
        "speech_duration": speech_duration,
        "full_duration": full_duration,
        "within_source_duration": within_source_duration,
        "remaining_silence": remaining_silence,
        "over_by_seconds": over_by_seconds,
    }


def wav_to_mp3(wav_path, mp3_path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("找不到 FFmpeg")
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(wav_path),
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "128k",
            str(mp3_path),
        ],
        check=True,
    )


def synthesize_language(
    client,
    lang,
    segments,
    outdir,
    *,
    drive,
    audio_folder_id,
):
    lang_dir = outdir / f"tts-{lang}"
    chunk_dir = lang_dir / f"{lang}_segments"
    chunk_dir.mkdir(parents=True, exist_ok=True)

    chunks = split_text_segments(segments)
    fingerprint = source_fingerprint(segments)
    checkpoint = load_tts_checkpoint(
        drive,
        audio_folder_id,
        lang,
        lang_dir,
    )

    completed = {}
    if (
        checkpoint
        and checkpoint.get("source_fingerprint") == fingerprint
        and checkpoint.get("model") == DEFAULT_TTS_MODEL
        and checkpoint.get("voice") == VOICE
        and int(checkpoint.get("chunk_count") or 0) == len(chunks)
    ):
        for item in checkpoint.get("chunks") or []:
            try:
                completed[int(item["chunk"])] = item
            except Exception:
                continue
        print(
            f"[TTS:{lang}] resume checkpoint: "
            f"{len(completed)}/{len(chunks)} chunks",
            flush=True,
        )
    else:
        checkpoint = {
            "version": TTS_CHECKPOINT_VERSION,
            "language": lang,
            "model": DEFAULT_TTS_MODEL,
            "voice": VOICE,
            "source_fingerprint": fingerprint,
            "chunk_count": len(chunks),
            "chunks": [],
            "status": "running",
        }

    chunk_paths = []
    manifest_chunks = []

    for index, chunk in enumerate(chunks, start=1):
        path = chunk_dir / f"{index:04d}.wav"
        part_name = tts_part_name(lang, index)
        cached = completed.get(index)

        if cached:
            item = find_file(drive, audio_folder_id, part_name)
            if item:
                download_drive_file(drive, item["id"], path)
                chunk_paths.append(path)
                manifest_chunks.append(cached)
                print(
                    f"[Gemini TTS:{lang}] chunk {index}/{len(chunks)} "
                    "resume from Drive",
                    flush=True,
                )
                continue

        text = "\n".join(x["text"] for x in chunk)
        style = (
            "calm, clear, warm educational lecture narration; "
            "natural pacing; pronounce religious and proper nouns carefully; "
            "read the supplied text verbatim without paraphrasing"
        )
        print(
            f"[Gemini TTS:{lang}] chunk {index}/{len(chunks)} "
            f"chars={len(text)}",
            flush=True,
        )
        audio, mime, usage = client.tts(
            text,
            voice=VOICE,
            style=style,
            model=DEFAULT_TTS_MODEL,
        )
        path.write_bytes(audio)

        # Persist every successful TTS request immediately. A quota error or
        # Kaggle reset must never force this audio chunk to be generated again.
        upload_or_replace_file(
            drive,
            audio_folder_id,
            path,
            part_name,
        )

        entry = {
            "chunk": index,
            "first_segment_id": chunk[0]["id"],
            "last_segment_id": chunk[-1]["id"],
            "characters": len(text),
            "mime_type": mime,
            "tokens": usage.total_tokens,
            "file": path.name,
            "drive_file": part_name,
        }
        completed[index] = entry
        manifest_chunks.append(entry)

        checkpoint["chunks"] = [
            completed[key] for key in sorted(completed)
        ]
        checkpoint["status"] = "running"
        save_tts_checkpoint(
            drive,
            audio_folder_id,
            lang,
            lang_dir,
            checkpoint,
        )
        print(
            f"✅ [TTS:{lang}] chunk {index} persistent checkpoint saved",
            flush=True,
        )
        chunk_paths.append(path)

    target_duration = max(float(x.get("end") or 0) for x in segments)
    wav_path = lang_dir / f"{lang}.wav"
    mp3_path = lang_dir / f"{lang}.mp3"
    info = concatenate_wavs(
        chunk_paths,
        wav_path,
        target_duration=target_duration,
    )
    wav_to_mp3(wav_path, mp3_path)

    manifest_path = lang_dir / f"{lang}.tts_manifest.json"
    manifest = {
        "language": lang,
        "language_name": LANGUAGE_NAMES[lang],
        "engine": "gemini",
        "model": DEFAULT_TTS_MODEL,
        "voice": VOICE,
        "source_fingerprint": fingerprint,
        "timeline_aligned": False,
        "duration_policy": "natural_speech_no_speed_change",
        "target_duration": round(target_duration, 3),
        "speech_duration": round(info["speech_duration"], 3),
        "full_duration": round(info["full_duration"], 3),
        "within_source_duration": info["within_source_duration"],
        "remaining_silence": round(info["remaining_silence"], 3),
        "over_by_seconds": round(info["over_by_seconds"], 3),
        "chunks": manifest_chunks,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    zip_path = lang_dir / f"{lang}.segments.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in chunk_paths:
            zf.write(path, arcname=path.name)

    checkpoint["chunks"] = manifest_chunks
    checkpoint["status"] = "complete"
    checkpoint["manifest"] = manifest
    save_tts_checkpoint(
        drive,
        audio_folder_id,
        lang,
        lang_dir,
        checkpoint,
    )

    return {
        "wav": wav_path,
        "mp3": mp3_path,
        "manifest": manifest_path,
        "segments_zip": zip_path,
        **manifest,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--langs", required=True)
    parser.add_argument(
        "--force",
        action="store_true",
        help="重新生成即使 Drive 已有完整 TTS 成果",
    )
    args = parser.parse_args()

    langs = list(dict.fromkeys(x.strip() for x in args.langs.split(",") if x.strip()))
    invalid = [x for x in langs if x not in LANGUAGE_NAMES]
    if invalid:
        raise RuntimeError("不支援語言：" + ",".join(invalid))

    drive, sheets = build_google_services()
    task = find_task(sheets, args.task_id)
    if not task:
        raise RuntimeError(f"找不到任務：{args.task_id}")
    if task["period"] is None or not task["lesson"]:
        raise RuntimeError("任務缺少期數或堂次")

    folders = resolve_lesson_folders(drive, sheets, int(task["period"]), task["lesson"])
    workdir = Path("/kaggle/working/gemini-tts") / args.task_id
    workdir.mkdir(parents=True, exist_ok=True)

    api_key = str(os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        api_key = get_secret("GEMINI_API_KEY")
    client = GeminiClient(
        api_key=api_key,
        tts_model=DEFAULT_TTS_MODEL,
        max_attempts=1,
        timeout=180,
    )

    run_id = new_run_id(args.task_id, "tts")
    mark_running(
        args.task_id,
        "tts",
        sheets=sheets,
        run_id=run_id,
        message="Gemini TTS 執行中：" + ",".join(langs),
        progress=5,
    )

    completed = []
    over = []
    try:
        update_cells(
            sheets,
            SPREADSHEET_ID,
            {
                f"任務佇列!P{task['sheet_row']}": "處理中",
                f"任務佇列!T{task['sheet_row']}": "Gemini 多語 TTS 執行中",
            },
        )

        for lang in langs:
            lang_run = new_run_id(args.task_id, f"tts:{lang}")

            if (
                not args.force
                and existing_final_tts(drive, folders["audio"], lang)
            ):
                print(
                    f"[TTS:{lang}] Drive 已有完整 wav/mp3/manifest，略過重做",
                    flush=True,
                )
                completed.append(lang)
                mark_done(
                    args.task_id,
                    f"tts:{lang}",
                    sheets=sheets,
                    run_id=lang_run,
                    message=f"Gemini {LANGUAGE_NAMES[lang]} TTS 已存在，略過重做",
                )
                continue
            mark_running(
                args.task_id,
                f"tts:{lang}",
                sheets=sheets,
                run_id=lang_run,
                message=f"Gemini {LANGUAGE_NAMES[lang]} TTS",
                progress=5,
            )

            segments = load_segments(
                drive,
                folders["translation"],
                lang,
                workdir,
            )
            result = synthesize_language(
                client,
                lang,
                segments,
                workdir,
                drive=drive,
                audio_folder_id=folders["audio"],
            )
            for key in ("wav", "mp3", "manifest", "segments_zip"):
                path = result[key]
                upload_or_replace_file(
                    drive,
                    folders["audio"],
                    path,
                    Path(path).name,
                )

            completed.append(lang)
            if result["within_source_duration"]:
                mark_done(
                    args.task_id,
                    f"tts:{lang}",
                    sheets=sheets,
                    run_id=lang_run,
                    message=f"Gemini {LANGUAGE_NAMES[lang]} TTS 完成",
                )
            else:
                over.append({
                    "lang": lang,
                    "seconds": result["over_by_seconds"],
                })
                mark_needs_review(
                    args.task_id,
                    f"tts:{lang}",
                    sheets=sheets,
                    run_id=lang_run,
                    message=(
                        f"TTS 超過原片 {result['over_by_seconds']:.1f}s；"
                        "保留完整語音，不調速不截斷"
                    ),
                )

        note = (
            f"Gemini TTS完成：{','.join(completed)}"
            + (
                "；超時=" + ",".join(
                    f"{x['lang']}+{x['seconds']:.1f}s" for x in over
                )
                if over else ""
            )
        )
        update_cells(
            sheets,
            SPREADSHEET_ID,
            {
                f"任務佇列!P{task['sheet_row']}": "完成" if not over else "待確認",
                f"任務佇列!S{task['sheet_row']}": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                f"任務佇列!T{task['sheet_row']}": note[:450],
            },
        )

        if over:
            mark_needs_review(
                args.task_id,
                "tts",
                sheets=sheets,
                run_id=run_id,
                message=note,
            )
        else:
            mark_done(
                args.task_id,
                "tts",
                sheets=sheets,
                run_id=run_id,
                message=note,
            )
        print(f"[DONE] {note}", flush=True)
        return 0

    except Exception as exc:
        mark_error(
            args.task_id,
            "tts",
            sheets=sheets,
            run_id=run_id,
            exc=exc,
        )
        print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
