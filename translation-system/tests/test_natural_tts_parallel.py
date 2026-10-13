"""Offline concurrency, fail-fast and recovery tests. No external API calls."""
import asyncio
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import natural_tts_parallel as p
from natural_tts_planner import SpeechBlock


def blocks(n=9):
    return [
        SpeechBlock(i, [i], i * 2.0, i * 2.0 + 1,
                    f"Synthetic sample {i}.",
                    hashlib.sha256(f"Synthetic sample {i}.".encode()).hexdigest())
        for i in range(1, n + 1)
    ]


class ParallelTests(unittest.TestCase):
    def test_bounded_ordering_and_speed(self):
        async def run(limit):
            active = 0
            peak = 0

            async def worker(i):
                nonlocal active, peak
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0.025 + (i % 4) * 0.009)
                active -= 1
                return i * i

            committed = []

            async def save(i, res):
                committed.append((i, res))

            result = await p.parallel_map_ordered(
                list(range(12)), worker, save, concurrency=limit
            )
            return result, peak, committed

        result, peak, saved = asyncio.run(run(4))
        self.assertEqual(result, [i * i for i in range(12)])
        self.assertLessEqual(peak, 4)
        self.assertGreaterEqual(peak, 3)
        self.assertEqual(len(saved), 12)

    def test_failure_preserves_completed_and_resume_skips_them(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            invocations = []
            failed_once = {"value": False}

            async def synth(block, **args):
                invocations.append(block.index)
                if block.index == 3 and not failed_once["value"]:
                    failed_once["value"] = True
                    raise RuntimeError("forced synthetic TTS failure")
                args["output_mp3"].write_bytes(b"synthetic mp3")
                args["boundary_path"].write_text("{}", encoding="utf8")
                await asyncio.sleep((block.index % 3) * 0.005)
                return {
                    "block_index": block.index,
                    "text_sha256": block.text_sha256,
                    "duration": 1,
                }

            def convert(mp3, wav):
                wav.write_bytes(b"fake wav")

            with patch.object(p, "synthesize_block", side_effect=synth), \
                 patch.object(p, "mp3_to_pcm_wav", side_effect=convert), \
                 patch.object(p, "_ffprobe_duration", return_value=1.0):
                with self.assertRaisesRegex(RuntimeError, "forced synthetic"):
                    asyncio.run(p.render_blocks_parallel(
                        lang="en", blocks=blocks(8),
                        output_dir=root, concurrency=2,
                    ))
                saved = json.loads((root / "en.tts_checkpoint.json").read_text())
                first_done = {x["block_index"] for x in saved["blocks"]}
                self.assertIn(1, first_done)
                previous_calls = len(invocations)
                meta, wavs = asyncio.run(p.render_blocks_parallel(
                    lang="en", blocks=blocks(8),
                    output_dir=root, concurrency=2,
                ))
                self.assertEqual([x["block_index"] for x in meta], list(range(1, 9)))
                self.assertEqual(len(wavs), 8)
                self.assertTrue(all(Path(w).exists() for w in wavs))
                self.assertTrue(any(x["reused"] for x in meta))
                self.assertEqual(
                    set(invocations[previous_calls:]),
                    set(range(1, 9)) - first_done,
                )
                saved2 = json.loads((root / "en.tts_checkpoint.json").read_text())
                self.assertEqual(len(saved2["blocks"]), 8)

    def test_reject_invalid_parallelism(self):
        async def work(_):
            return 1

        async def done(_, result):
            pass

        with self.assertRaises(ValueError):
            asyncio.run(p.parallel_map_ordered(
                [1], work, done, concurrency=16,
            ))

    def test_disallows_duplicate_indices(self):
        with tempfile.TemporaryDirectory() as temp:
            twice = [blocks(1)[0], blocks(1)[0]]
            with self.assertRaisesRegex(ValueError, "duplicate"):
                asyncio.run(p.render_blocks_parallel(
                    lang="en", blocks=twice, output_dir=temp, concurrency=2
                ))


if __name__ == "__main__":
    unittest.main()
