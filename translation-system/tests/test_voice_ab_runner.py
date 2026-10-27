"""Offline checks for the isolated SoulKey Edge / VoxCPM2 A/B trial."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "experiments" / "voice_ab_runner.py"
SAMPLES = ROOT / "experiments" / "voice_ab_samples.demo.json"
NOTEBOOK = ROOT / "experiments" / "soulkey_voice_ab_kaggle.ipynb"
SPEC = importlib.util.spec_from_file_location("soulkey_voice_ab_runner", SCRIPT)
voice_ab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(voice_ab)


class VoiceABOfflineTests(unittest.TestCase):
    def test_language_inputs(self):
        fixture = json.loads(SAMPLES.read_text(encoding="utf-8"))
        texts = voice_ab.validate_samples(fixture)
        self.assertEqual(tuple(texts), ("en", "th", "km", "lo", "my"))
        self.assertIn("not_from_soulkey_lecture", fixture["source"])

    def test_bad_inputs(self):
        fixture = json.loads(SAMPLES.read_text(encoding="utf-8"))
        del fixture["languages"]["lo"]
        with self.assertRaisesRegex(ValueError, "lo"):
            voice_ab.validate_samples(fixture)
        fixture["languages"]["lo"] = {"text": ""}
        with self.assertRaisesRegex(ValueError, "lo"):
            voice_ab.validate_samples(fixture)

    def test_dry_run_is_side_effect_free(self):
        with tempfile.TemporaryDirectory() as temp:
            output_dir = Path(temp) / "not-created"
            options = voice_ab.cli([
                "--samples", str(SAMPLES), "--output-dir", str(output_dir), "--dry-run"
            ])
            with patch.object(voice_ab, "load_voxcpm",
                              side_effect=AssertionError("must not load model")):
                result = voice_ab.run(options)
            self.assertEqual(result["mode"], "validation_only")
            self.assertFalse(output_dir.exists())

    def test_all_network_failures_recorded_no_fake_winner(self):
        with tempfile.TemporaryDirectory() as temp:
            options = voice_ab.cli([
                "--samples", str(SAMPLES), "--output-dir", str(Path(temp) / "out"),
                "--edge-only"
            ])
            async def failing_edge(*args):
                raise ConnectionError("simulated offline Edge backend")
            with patch.object(voice_ab, "preflight",
                              return_value={"simulated": True}), \
                 patch.object(voice_ab, "generate_edge",
                              side_effect=failing_edge):
                report = voice_ab.run(options)
            self.assertEqual(len(report["results"]), 5)
            self.assertTrue(all(row["status"] == "failed"
                                for row in report["results"]))
            self.assertFalse(report["automatic_winner_selected"])
            self.assertTrue((options.output_dir / "ab_report.json").exists())
            self.assertEqual(len((options.output_dir / "human_review.csv")
                                 .read_text(encoding="utf-8-sig").splitlines()), 1)

    def test_notebook_exactly_embeds_runner_and_samples(self):
        notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        cells = ["".join(cell["source"]) for cell in notebook["cells"]
                 if cell["cell_type"] == "code"]
        runner = next(cell for cell in cells
                      if cell.startswith("%%writefile /kaggle/working/voice_ab_runner.py"))
        sample = next(cell for cell in cells
                      if cell.startswith("%%writefile /kaggle/working/voice_ab_samples.demo.json"))
        self.assertEqual(runner.split("\n", 1)[1], SCRIPT.read_text(encoding="utf-8"))
        self.assertEqual(sample.split("\n", 1)[1], SAMPLES.read_text(encoding="utf-8"))
        self.assertEqual(notebook["nbformat"], 4)
        self.assertTrue(any("torch.cuda.is_available" in cell for cell in cells))

    def test_no_production_drive_or_github_writes(self):
        source = SCRIPT.read_text(encoding="utf-8")
        for bad in ("upload_or_replace_file", "from google_io", "github_push",
                    "script.google.com"):
            self.assertNotIn(bad, source)
        self.assertIn("model.tts_model.sample_rate", source)


if __name__ == "__main__":
    unittest.main()
