"""Synthetic live Edge TTS integration smoke for the *pilot branch only*.

No real lecture text, OAuth tokens, Drive, production MP3 or Kaggle touched.
Designed for small-volume CLI testing with at most four concurrent sockets.
"""
import asyncio
import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from natural_tts_planner import SpeechBlock
from natural_tts_edge import render_blocks, _ffprobe_duration


def samples():
    messages = [
        "Learning together brings patience and understanding.",
        "Simple acts of kindness can brighten someone's day.",
        "When we listen attentively, we understand others better.",
        "A calm mind makes it easier to appreciate the present.",
        "Practicing gratitude helps us grow in everyday life.",
        "We learn from our experiences and share what is useful.",
        "Community begins when we sincerely care for one another.",
        "True progress is built through steady thoughtful effort.",
        "Taking time to reflect can improve our choices.",
        "We treat everyone with respect and understanding.",
        "Words spoken with kindness can make a difference.",
        "Each day gives us an opportunity to practice patience.",
    ]
    return [
        SpeechBlock(
            index=i + 1, segment_ids=[i + 1],
            source_start=i * 4.0, source_end=i * 4.0 + 3.0,
            text=text, text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        ) for i, text in enumerate(messages)
    ]


def run(root, count, concurrency):
    folder = root / f"concurrency_{concurrency}"
    os.environ["SOULKEY_TTS_PARALLEL_BLOCKS"] = str(concurrency)
    started = time.monotonic()
    results, wavs = asyncio.run(render_blocks(
        lang="en", blocks=samples()[:count], output_dir=folder,
    ))
    elapsed = round(time.monotonic() - started, 3)
    indices = [x["block_index"] for x in results]
    if indices != list(range(1, count + 1)):
        raise RuntimeError("speech block ordering is incorrect")
    audio_seconds = 0.0
    for row, wav in zip(results, wavs):
        idx = row["block_index"]
        mp3 = folder / "blocks" / f"{idx:04d}.mp3"
        if not (mp3.is_file() and wav.is_file() and mp3.stat().st_size > 1000):
            raise RuntimeError(f"block {idx} is not fully delivered")
        audio_seconds += _ffprobe_duration(mp3)
    checkpoint = folder / "en.tts_checkpoint.json"
    if len(json.loads(checkpoint.read_text())["blocks"]) != count:
        raise RuntimeError("checkpoint does not cover all blocks")
    if any(x.get("reused") for x in results):
        raise RuntimeError("fresh run incorrectly reused blocks")
    # Fresh output replay must make zero new service calls via local checkpoint.
    resumed, _ = asyncio.run(render_blocks(
        lang="en", blocks=samples()[:count], output_dir=folder,
    ))
    if not all(x.get("reused") for x in resumed):
        raise RuntimeError("checkpoint restart unnecessarily regenerated blocks")
    return {
        "concurrency": concurrency, "blocks": count, "wall_seconds": elapsed,
        "audio_seconds": round(audio_seconds, 3),
        "first_pass_created": len(results), "second_pass_reused": len(resumed),
        "success": True,
    }


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--count", type=int, default=12)
    args = ap.parse_args()
    root = Path(args.output_dir)
    root.mkdir(parents=True, exist_ok=True)
    if not 1 <= args.count <= 12:
        raise ValueError("count must be between 1 and 12")
    result = {"scope": "synthetic GitHub CPU pilot, never production", "tests": []}
    try:
        # Rotate order from the original benchmark to reduce warm-up bias.
        for concurrency in (2, 1, 4):
            row = run(root, args.count, concurrency)
            result["tests"].append(row)
            print("PILOT_TRIAL", json.dumps(row), flush=True)
            time.sleep(2)
        baseline = next(x["wall_seconds"] for x in result["tests"] if x["concurrency"] == 1)
        result["relative_speed"] = {
            str(x["concurrency"]): round(baseline / x["wall_seconds"], 3)
            for x in result["tests"]
        }
        result["passed"] = True
    except Exception as exc:
        result["passed"] = False
        result["failure"] = type(exc).__name__ + ": " + str(exc).split("url=")[0][:160]
    finally:
        report_path = root / "report.json"
        report_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print("PILOT_FINAL", json.dumps(result, ensure_ascii=False), flush=True)
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
