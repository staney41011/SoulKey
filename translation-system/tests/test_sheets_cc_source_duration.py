"""Guard against ever treating YouTube CC end timestamps as video runtime."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class SheetsSourceDurationTests(unittest.TestCase):
    def test_sheets_tts_requires_verified_original_video_duration(self):
        path = ROOT / "translation-system/google_sheet_pilot_tts_runner.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        main = next(
            x for x in tree.body
            if isinstance(x, ast.FunctionDef) and x.name == "main")
        called = {
            node.func.id for node in ast.walk(main)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertIn("load_source_duration_limit", called)
        self.assertIn("check_english_coverage", called)
        self.assertIn("compare_manuscript_to_video", called)
        self.assertNotIn("recover_duration_from_english_cc", called)
        self.assertNotIn(
            "recover_duration_from_english_cc",
            {x.name for x in tree.body if isinstance(x, ast.FunctionDef)},
        )

    def test_legacy_tts_cannot_use_last_subtitle_cue_as_video_length(self):
        text = (ROOT / "translation-system/tts_runner.py").read_text(
            encoding="utf-8")
        self.assertNotIn("last_approved_source_timestamp", text)
        self.assertIn("duration_limit = float(video_duration)", text)


if __name__ == "__main__":
    unittest.main()
