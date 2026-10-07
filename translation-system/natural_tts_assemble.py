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


def _ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise RuntimeError("ffmpeg not found")
    return path


def wav_to_mp3(wav_path: Path, mp3_path: Path) -> None:
    subprocess.run(
        [
            _ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(wav_path),
            "-codec:a", "libmp3lame", "-b:a", "128k",
            str(mp3_path),
        ],
        check=True,
    )


def _read_pcm(path: Path):
    with wave.open(str(path), "rb") as wf:
        if wf.getnchannels() != 1 or wf.getsampwidth() != 2:
            raise RuntimeError(f"unexpected WAV format: {path}")
        return wf.getframerate(), wf.readframes(wf.getnframes())


def _write_pcm(path: Path, sample_rate: int, frames: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(frames)


def _silence(sample_rate: int, seconds: float) -> bytes:
    samples = max(0, int(round(float(seconds) * sample_rate)))
    return bytes(samples * 2)


def assemble_preview(
    wav_parts: list[Path],
    output_wav: Path,
    pause_seconds: float = DEFAULT_BLOCK_PAUSE_SECONDS,
):
    if not wav_parts:
        raise RuntimeError("no preview audio parts")

    sample_rate = None
    output = bytearray()

    for index, path in enumerate(wav_parts):
        rate, frames = _read_pcm(path)
        if sample_rate is None:
            sample_rate = rate
        if rate != sample_rate:
            raise RuntimeError("sample rate mismatch")
        output.extend(frames)
        if index < len(wav_parts) - 1:
            output.extend(_silence(sample_rate, pause_seconds))

    _write_pcm(output_wav, sample_rate, bytes(output))
    return {
        "sample_rate": sample_rate,
        "duration": round(len(output) / 2 / sample_rate, 3),
    }


def assemble_timeline(
    blocks,
    wav_parts: list[Path],
    output_wav: Path,
    *,
    source_duration: float,
    minimum_pause: float = DEFAULT_TIMELINE_PAUSE_SECONDS,
):
    if len(blocks) != len(wav_parts):
        raise RuntimeError("block/audio count mismatch")

    sample_rate = None
    output = bytearray()
    cursor = 0.0
    schedule = []
    max_drift = 0.0

    for block, path in zip(blocks, wav_parts):
        rate, frames = _read_pcm(path)
        if sample_rate is None:
            sample_rate = rate
        if rate != sample_rate:
            raise RuntimeError("sample rate mismatch")

        duration = len(frames) / 2 / sample_rate
        actual_start = max(float(block.source_start), cursor)
        if output:
            actual_start = max(actual_start, cursor + minimum_pause)

        current_seconds = len(output) / 2 / sample_rate
        if actual_start > current_seconds:
            output.extend(_silence(sample_rate, actual_start - current_seconds))

        output.extend(frames)
        actual_end = actual_start + duration
        cursor = actual_end
        drift = max(0.0, actual_end - float(block.source_end))
        max_drift = max(max_drift, drift)

        schedule.append({
            "block_index": block.index,
            "segment_ids": block.segment_ids,
            "source_start": round(float(block.source_start), 3),
            "source_end": round(float(block.source_end), 3),
            "actual_start": round(actual_start, 3),
            "actual_end": round(actual_end, 3),
            "generated_duration": round(duration, 3),
            "drift": round(drift, 3),
        })

    speech_end = len(output) / 2 / sample_rate
    if source_duration > speech_end:
        output.extend(_silence(sample_rate, source_duration - speech_end))

    final_duration = len(output) / 2 / sample_rate
    over_source = max(0.0, final_duration - source_duration)
    needs_review = (
        max_drift > MAX_DRIFT_SECONDS
        or over_source > MAX_OVER_SOURCE_SECONDS
    )

    _write_pcm(output_wav, sample_rate, bytes(output))
    return {
        "sample_rate": sample_rate,
        "speech_end": round(speech_end, 3),
        "source_duration": round(source_duration, 3),
        "final_duration": round(final_duration, 3),
        "max_drift": round(max_drift, 3),
        "over_source": round(over_source, 3),
        "needs_review": bool(needs_review),
        "schedule": schedule,
    }


def write_alignment_report(path: Path, *, preview: dict, timeline: dict):
    path.write_text(
        json.dumps(
            {"preview": preview, "timeline": timeline},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
