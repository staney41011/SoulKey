"""Regression: P259 all-language audio plan uses F (audio_enabled), not G."""
import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TREE = ast.parse((ROOT / "central_tts_recovery.py").read_text(encoding="utf-8"))
FN = next(x for x in TREE.body if isinstance(x, ast.FunctionDef)
          and x.name == "approved_plan_rows")
namespace = {}
exec(compile(ast.Module(body=[FN], type_ignores=[]), "<approved_plan_rows>", "exec"), namespace)
approved_plan_rows = namespace["approved_plan_rows"]


class CentralPlanTests(unittest.TestCase):
    def test_true_in_column_f_is_selected(self):
        rows = [
            ["P259-L01", "en", "English", "TRUE", "human", "TRUE", "tts"],
            ["P259-L01", "th", "Thai", "TRUE", "ai", "TRUE", "tts"],
            ["P259-L01", "es", "Spanish", "TRUE", "ai", "FALSE", "tts"],
            ["P259-L02", "vi", "Vietnamese", "TRUE", "ai", "TRUE", "tts"],
        ]
        self.assertEqual(approved_plan_rows(rows, "P259-L01"), ["en", "th"])

    def test_ignores_duplicate_and_disabled(self):
        rows = [
            ["P259-L04", "ja", "Japanese", "TRUE", "ai", "TRUE", "tts"],
            ["P259-L04", "ja", "Japanese", "TRUE", "ai", "TRUE", "tts"],
            ["P259-L04", "pt", "Portuguese", "TRUE", "ai", "FALSE", "tts"],
        ]
        self.assertEqual(approved_plan_rows(rows, "P259-L04"), ["ja"])


if __name__ == "__main__":
    unittest.main()
