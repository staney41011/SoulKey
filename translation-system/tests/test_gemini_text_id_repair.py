"""Reproduces P261-L02 missing/duplicate ID faults without real API calls."""
import ast
import json
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "gemini_text_production_runner.py"
NAMES = {
    "validate_ids",
    "glossary_for_batch",
    "_valid_unique_translations",
    "_translate_chunk_recovering_ids",
    "transform_segments",
}


def production_functions():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in NAMES]
    scope = {
        "json": json,
        "TEXT_SCHEMA": {"type": "object"},
        "normalize_segments": lambda obj: obj["segments"],
        "parse_glossary_rows": lambda rows: [],
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(SOURCE), "exec"), scope)
    return scope


def segments(ids):
    return [{"id": ident, "start": ident * 2, "end": ident * 2 + 1,
             "text": f"第{ident}段中文內容"} for ident in ids]


class FakeGemma:
    def __init__(self, failure_mode):
        self.failure_mode = failure_mode
        self.calls = []

    def structured(self, prompt, schema, **kwargs):
        # Input array follows the final newline, including repair attempts.
        req = json.loads(prompt[prompt.rfind("\n[") + 1:])
        ids = [x["id"] for x in req]
        self.calls.append(ids)
        rows = [{"id": i, "text": f"English translation {i}",
                 "notes": ""} for i in ids]
        if len(self.calls) == 1:
            if self.failure_mode == "duplicate80":
                rows[-1]["id"] = 80  # Missing 83; 80 appears twice.
            elif self.failure_mode == "wrong5":
                rows[1]["id"] = 5  # Missing 25, unrelated 5 returned.
        if self.failure_mode == "always_wrong" and ids == [83]:
            rows = [{"id": 999, "text": "incorrect", "notes": ""}]
        return {"segments": rows}, None


class RecoverGemmaEnglishIds(unittest.TestCase):
    def test_duplicate_80_and_missing_83_are_repaired_without_guessing(self):
        api = FakeGemma("duplicate80")
        src = segments(list(range(72, 84)))
        out = production_functions()["transform_segments"](api, src, [], "en")
        self.assertEqual([r["id"] for r in out], list(range(72, 84)))
        self.assertEqual(api.calls, [list(range(72, 84)), [80, 83]])
        self.assertEqual(out[8]["text"], "English translation 80")
        self.assertEqual(out[-1]["text"], "English translation 83")
        self.assertEqual(out[0]["start"], src[0]["start"])

    def test_hallucinated_id_is_not_assigned_to_missing_source(self):
        api = FakeGemma("wrong5")
        src = segments(list(range(24, 36)))
        out = production_functions()["transform_segments"](api, src, [], "en")
        self.assertEqual(api.calls[1], [25])
        self.assertEqual([r["id"] for r in out], list(range(24, 36)))
        self.assertEqual(out[1]["text"], "English translation 25")

    def test_reuse_matching_checkpoint_without_api(self):
        src = segments([72, 73, 74])
        cache = {x["id"]: {"text": f"Cached {x['id']}", "notes": ""} for x in src}
        api = FakeGemma("none")
        out = production_functions()["transform_segments"](
            api, src, [], "en", cached_rows=cache,
        )
        self.assertEqual(len(out), 3)
        self.assertEqual(api.calls, [])

    def test_never_publish_while_id_remains_missing(self):
        api = FakeGemma("always_wrong")
        with self.assertRaisesRegex(RuntimeError, "repair exhausted"):
            production_functions()["transform_segments"](api, segments([83]), [], "en")
        self.assertEqual(api.calls, [[83]] * 5)


if __name__ == "__main__":
    unittest.main()
