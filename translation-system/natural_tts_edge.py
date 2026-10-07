from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

from natural_tts_config import NATURAL_TTS_PROFILES, NATURAL_TTS_PROFILE_REVISION
from natural_tts_planner import SpeechBlock


def _ffprobe_duration(path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe not found")
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def _ffmpeg() -> str:
    value = shutil.which("ffmpeg")
    if not value:
        raise RuntimeError("ffmpeg not found")
    return value


def mp3_to_pcm_wav(mp3_path: Path, wav_path: Path, sample_rate: int = 24000):
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            _ffmpeg(),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(mp3_path),
            "-ar",
            str(sample_rate),
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(wav_path),
        ],
        check=True,
    )


async def synthesize_block(
    block: SpeechBlock,
    *,
    voice: str,
    rate: str,
    pitch: str,
    output_mp3: Path,
    boundary_path: Path,
    attempts: int = 3,
):
    import edge_tts

    output_mp3.parent.mkdir(parents=True, exist_ok=True)
    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            communicate = edge_tts.Communicate(
                text=block.text,
                voice=voice,
                rate=rate,
                pitch=pitch,
                boundary="SentenceBoundary",
            )
            await communicate.save(str(output_mp3), str(boundary_path))
            duration = _ffprobe_duration(output_mp3)
            if duration <= 0:
                raise RuntimeError("zero duration Edge audio")
            return {
                "block_index": block.index,
                "segment_ids": block.segment_ids,
                "source_start": block.source_start,
                "source_end": block.source_end,
                "text": block.text,
                "text_sha256": block.text_sha256,
                "duration": duration,
                "attempt": attempt,
                "audio_file": output_mp3.name,
                "boundary_file": boundary_path.name,
            }
        except Exception as exc:
            last_error = exc
            if attempt == attempts:
                break
            await asyncio.sleep(min(8, 2 ** attempt))

    raise RuntimeError(
        f"Edge TTS block {block.index} failed after {attempts} attempts: {last_error}"
    )


async def render_blocks(
    *,
    lang: str,
    blocks: list[SpeechBlock],
    output_dir: Path,
):
    profile = NATURAL_TTS_PROFILES[lang]
    if profile["engine"] != "edge":
        raise ValueError(f"{lang} is not an Edge language")

    block_dir = output_dir / "blocks"
    wav_dir = output_dir / "blocks-wav"
    block_dir.mkdir(parents=True, exist_ok=True)
    wav_dir.mkdir(parents=True, exist_ok=True)

    results = []
    wav_paths = []
    checkpoint_path = output_dir / f"{lang}.tts_checkpoint.json"

    checkpoint = {}
    if checkpoint_path.exists():
        try:
            payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            if (
                payload.get("profile_revision") == NATURAL_TTS_PROFILE_REVISION
                and payload.get("voice") == profile["voice"]
                and payload.get("rate") == profile["rate"]
                and payload.get("pitch") == profile["pitch"]
            ):
                checkpoint = {
                    int(x["block_index"]): x
                    for x in (payload.get("blocks") or [])
                    if "block_index" in x
                }
        except Exception:
            checkpoint = {}

    for block in blocks:
        mp3 = block_dir / f"{block.index:04d}.mp3"
        boundary = block_dir / f"{block.index:04d}.boundaries.jsonl"
        wav = wav_dir / f"{block.index:04d}.wav"

        previous = checkpoint.get(block.index) or {}
        can_reuse = bool(
            previous.get("text_sha256") == block.text_sha256
            and mp3.exists()
            and wav.exists()
        )
        if can_reuse:
            try:
                duration = _ffprobe_duration(mp3)
                if duration <= 0:
                    can_reuse = False
            except Exception:
                can_reuse = False

        if can_reuse:
            meta = dict(previous)
            meta["reused"] = True
        else:
            meta = await synthesize_block(
                block,
                voice=profile["voice"],
                rate=profile["rate"],
                pitch=profile["pitch"],
                output_mp3=mp3,
                boundary_path=boundary,
            )
            mp3_to_pcm_wav(mp3, wav)
            meta["reused"] = False

        results.append(meta)
        wav_paths.append(wav)

        checkpoint_payload = {
            "language": lang,
            "profile_revision": NATURAL_TTS_PROFILE_REVISION,
            "voice": profile["voice"],
            "rate": profile["rate"],
            "pitch": profile["pitch"],
            "blocks": results,
        }
        checkpoint_path.write_text(
            json.dumps(checkpoint_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    manifest = {
        "language": lang,
        "engine": "edge",
        "profile_revision": NATURAL_TTS_PROFILE_REVISION,
        "voice": profile["voice"],
        "rate": profile["rate"],
        "pitch": profile["pitch"],
        "blocks": results,
    }
    (output_dir / f"{lang}.edge_blocks.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return results, wav_paths
