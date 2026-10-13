"""Opt-in bounded parallel Edge TTS with atomic local checkpoints.

Production remains on the existing serial renderer unless explicitly enabled.
No Drive/Sheets writes occur in this module.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from natural_tts_config import NATURAL_TTS_PROFILES, NATURAL_TTS_PROFILE_REVISION
from natural_tts_edge import _ffprobe_duration, mp3_to_pcm_wav, synthesize_block


def _atomic_json(path: Path, obj: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


async def parallel_map_ordered(items, worker, on_completed, *, concurrency: int):
    """Bounded task window: commit each success; return input order."""
    if not (1 <= concurrency <= 4):
        raise ValueError("parallel TTS concurrency must be 1..4")
    things = list(items)
    queue = iter(enumerate(things))
    pending = {}
    results = {}

    def fill():
        while len(pending) < concurrency:
            try:
                idx, item = next(queue)
            except StopIteration:
                return
            pending[asyncio.create_task(worker(item))] = idx

    fill()
    try:
        while pending:
            finished, _ = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            first_failure = None
            for task in sorted(finished, key=lambda t: pending[t]):
                idx = pending.pop(task)
                try:
                    result = task.result()
                    await on_completed(idx, result)
                    results[idx] = result
                except BaseException as exc:
                    if first_failure is None:
                        first_failure = exc
            if first_failure is not None:
                raise first_failure
            fill()
    except BaseException:
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending.keys(), return_exceptions=True)
        raise
    return [results[i] for i in range(len(things))]


async def render_blocks_parallel(*, lang, blocks, output_dir, concurrency, checkpoint_store=None):
    """Resume only matching voice/text blocks and atomically commit successes.

    The checkpoint is local. Persist the output directory outside the ephemeral
    runner if cross-session block-level resume is required.
    """
    profile = NATURAL_TTS_PROFILES[lang]
    if profile["engine"] != "edge":
        raise ValueError(f"{lang} is not an Edge TTS language")
    output_dir = Path(output_dir)
    block_dir = output_dir / "blocks"
    wav_dir = output_dir / "blocks-wav"
    block_dir.mkdir(parents=True, exist_ok=True)
    wav_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = output_dir / f"{lang}.tts_checkpoint.json"
    context = {
        "language": lang,
        "profile_revision": NATURAL_TTS_PROFILE_REVISION,
        "voice": profile["voice"],
        "rate": profile["rate"],
        "pitch": profile["pitch"],
    }
    if len({block.index for block in blocks}) != len(blocks):
        raise ValueError("duplicate TTS block indexes are forbidden")
    previous = {}
    if checkpoint_path.exists():
        try:
            saved = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            if all(saved.get(k) == v for k, v in context.items()):
                previous = {int(m["block_index"]): m for m in saved.get("blocks", [])}
        except (ValueError, KeyError, TypeError):
            previous = {}
    completed = {}
    cache_tasks = []
    cache_groups_scheduled = set()
    cache_upload_lock = asyncio.Lock()

    async def worker(block):
        index = block.index
        mp3 = block_dir / f"{index:04d}.mp3"
        bounds = block_dir / f"{index:04d}.boundaries.jsonl"
        wav = wav_dir / f"{index:04d}.wav"
        before = previous.get(index) or {}
        reusable = before.get("text_sha256") == block.text_sha256 and mp3.exists()
        if reusable:
            try:
                reusable = await asyncio.to_thread(_ffprobe_duration, mp3) > 0
                if reusable and not wav.exists():
                    # Remote checkpoints save only compact MP3. Rebuild WAV here.
                    await asyncio.to_thread(mp3_to_pcm_wav, mp3, wav)
            except (OSError, RuntimeError, ValueError):
                reusable = False
        if reusable:
            meta = dict(before)
            meta["reused"] = True
        else:
            # Never write a partially generated MP3 over the approved one.
            staging_mp3 = mp3.with_name(mp3.stem + ".part.mp3")
            staging_wav = wav.with_name(wav.stem + ".part.wav")
            staging_bounds = bounds.with_name(bounds.stem + ".part.jsonl")
            for file in (staging_mp3, staging_wav, staging_bounds):
                file.unlink(missing_ok=True)
            meta = await synthesize_block(
                block, voice=profile["voice"], rate=profile["rate"],
                pitch=profile["pitch"], output_mp3=staging_mp3,
                boundary_path=staging_bounds,
            )
            await asyncio.to_thread(mp3_to_pcm_wav, staging_mp3, staging_wav)
            if not (staging_mp3.stat().st_size > 0 and staging_wav.stat().st_size > 0):
                raise RuntimeError(f"Invalid staged audio block {index}")
            os.replace(staging_mp3, mp3)
            if staging_bounds.exists():
                os.replace(staging_bounds, bounds)
            os.replace(staging_wav, wav)
            meta["audio_file"] = mp3.name
            meta["boundary_file"] = bounds.name
            meta["reused"] = False
        meta.update({
            "block_index": index, "segment_ids": block.segment_ids,
            "source_start": block.source_start, "source_end": block.source_end,
            "text_sha256": block.text_sha256,
        })
        return meta, wav

    async def upload_group(group, snapshot):
        async with cache_upload_lock:
            try:
                await asyncio.to_thread(
                    checkpoint_store.save_group, group, snapshot, output_dir
                )
            except Exception as exc:
                # Cloud checkpoint is best-effort; final MP3 delivery remains
                # separately verified and must not be mistaken for success.
                print(
                    f"[TTS-CACHE] {lang} group {group} upload failed: "
                    f"{type(exc).__name__}", flush=True
                )

    async def on_completed(_, value):
        meta, _ = value
        index = int(meta["block_index"])
        completed[index] = meta
        _atomic_json(checkpoint_path, {
            **context, "blocks": [completed[k] for k in sorted(completed)]
        })
        if checkpoint_store is not None:
            group = (index - 1) // 8
            if (
                group not in cache_groups_scheduled
                and group not in getattr(checkpoint_store, "restored_groups", set())
                and all(k in completed for k in checkpoint_store.group_members(group))
            ):
                cache_groups_scheduled.add(group)
                snapshot = {
                    k: completed[k] for k in checkpoint_store.group_members(group)
                }
                cache_tasks.append(asyncio.create_task(upload_group(group, snapshot)))

    try:
        done = await parallel_map_ordered(
            blocks, worker, on_completed, concurrency=concurrency
        )
    finally:
        if cache_tasks:
            await asyncio.gather(*cache_tasks, return_exceptions=True)
    metas = [x[0] for x in done]
    wavs = [x[1] for x in done]
    _atomic_json(output_dir / f"{lang}.edge_blocks.json", {
        **context, "engine": "edge", "blocks": metas
    })
    return metas, wavs
