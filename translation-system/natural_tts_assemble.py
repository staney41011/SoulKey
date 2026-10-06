from __future__ import annotations

import json
import shutil
import subprocess
import wave
from pathlib import Path

from natural_tts_config import (
    DEFAULT_BLOCK_PAUSE_SECONDS,
    DEFAULT_TIMELINE_PAUSE_SECONDS,
    MAX_DRIFT_SECONDS,
    MAX_OVER_SOURCE_SECONDS,
)
from natural_tts_planner import SpeechBlock


def ffmpeg_path():
    path = shutil.which("ffmpeg")
    if not path:
        raise RuntimeError("ffmpeg not found")
    return path


def wav_to_mp3(wav_path: Path, mp3_path: Path):
    subprocess.run([
        ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(wav_path), "-codec:a", "libmp3lame",
        "-b:a", "128k", str(mp3_path),
    ], check=True)


def read_pcm(path: Path):
    with wave.open(str(path), "rb") as wf:
        if wf.getnchannels() != 1 or wf.getsampwidth() != 2:
            raise RuntimeError(f"unexpected WAV format: {path}")
        return wf.getframerate(), wf.readframes(wf.getnframes())


def write_pcm(path: Path, sample_rate: int, frames: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(frames)


def silence(sample_rate: int, seconds: float):
    return bytes(max(0, int(round(sample_rate * seconds))) * 2)


def assemble_preview(wav_parts, output_wav, pause_seconds=DEFAULT_BLOCK_PAUSE_SECONDS):
    if not wav_parts:
        raise RuntimeError("no preview parts")
    sample_rate = None
    output = bytearray()
    for index, path in enumerate(wav_parts):
        rate, frames = read_pcm(path)
        sample_rate = sample_rate or rate
        if rate != sample_rate:
            raise RuntimeError("sample rate mismatch")
        output.extend(frames)
        if index < len(wav_parts) - 1:
            output.extend(silence(sample_rate, pause_seconds))
    write_pcm(output_wav, sample_rate, bytes(output))
    return {"duration": round(len(output) / 2 / sample_rate, 3)}


def assemble_timeline(blocks, wav_parts, output_wav, source_duration):
    if len(blocks) != len(wav_parts):
        raise RuntimeError("block/audio count mismatch")

    sample_rate = None
    output = bytearray()
    cursor = 0.0
    schedule = []
    max_drift = 0.0

    for block, path in zip(blocks, wav_parts):
        rate, frames = read_pcm(path)
        sample_rate = sample_rate or rate
        if rate != sample_rate:
            raise RuntimeError("sample rate mismatch")

        duration = len(frames) / 2 / sample_rate
        actual_start = max(block.source_start, cursor)
        if output:
            actual_start = max(actual_start, cursor + DEFAULT_TIMELINE_PAUSE_SECONDS)

        current_seconds = len(output) / 2 / sample_rate
        if actual_start > current_seconds:
            output.extend(silence(sample_rate, actual_start - current_seconds))

        output.extend(frames)
        actual_end = actual_start + duration
        cursor = actual_end
        drift = max(0.0, actual_end - block.source_end)
        max_drift = max(max_drift, drift)
        schedule.append({
            "block_index": block.index,
            "segment_ids": block.segment_ids,
            "source_start": round(block.source_start, 3),
            "source_end": round(block.source_end, 3),
            "actual_start": round(actual_start, 3),
            "actual_end": round(actual_end, 3),
            "drift": round(drift, 3),
        })

    speech_end = len(output) / 2 / sample_rate
    if source_duration > speech_end:
        output.extend(silence(sample_rate, source_duration - speech_end))

    final_duration = len(output) / 2 / sample_rate
    over_source = max(0.0, final_duration - source_duration)
    needs_review = (
        max_drift > MAX_DRIFT_SECONDS
        or over_source > MAX_OVER_SOURCE_SECONDS
    )
    write_pcm(output_wav, sample_rate, bytes(output))
    return {
        "speech_end": round(speech_end, 3),
        "source_duration": round(source_duration, 3),
        "final_duration": round(final_duration, 3),
        "max_drift": round(max_drift, 3),
        "over_source": round(over_source, 3),
        "needs_review": needs_review,
        "schedule": schedule,
    }


def write_alignment_report(path: Path, preview_info, timeline_info):
    path.write_text(json.dumps({
        "preview": preview_info,
        "timeline": timeline_info,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
