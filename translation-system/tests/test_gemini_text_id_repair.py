"""Reproduces P261-L02 missing/duplicate ID faults without real API calls."""
import ast
import json
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "gemini_text_production_runner.py"


class FakeGeminiAPIError(RuntimeError):
    pass
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
        "GeminiAPIError": FakeGeminiAPIError,
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
        if len(self.calls) == 1 and self.failure_mode == "bad_json_once":
            raise FakeGeminiAPIError(
                "Gemma 4 Structured Output invalid JSON: Expecting value: line 1 column 1 (char 0)")
        if len(self.calls) == 1 and self.failure_mode == "http_500_once":
            raise FakeGeminiAPIError('HTTP 500: {"error": {"message": "Internal error encountered."}}')
        if self.failure_mode == "always_bad_json":
            raise FakeGeminiAPIError("Gemma 4 Structured Output invalid JSON")
        if self.failure_mode == "http_403":
            raise FakeGeminiAPIError("HTTP 403: unauthorized")
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

    def test_invalid_json_retries_smaller_groups_not_whole_course(self):
        src = segments(list(range(300, 312)))
        api = FakeGemma("bad_json_once")
        out = production_functions()["transform_segments"](api, src, [], "en")
        self.assertEqual([r["id"] for r in out], list(range(300, 312)))
        self.assertEqual(api.calls[0], list(range(300, 312)))
        self.assertEqual(api.calls[1], list(range(300, 304)))

    def test_http_500_recovers_after_smaller_retries(self):
        src = segments([300, 301, 302, 303])
        api = FakeGemma("http_500_once")
        out = production_functions()["transform_segments"](api, src, [], "en")
        self.assertEqual(len(out), 4)
        self.assertEqual([r["id"] for r in out], [300, 301, 302, 303])

    def test_persistent_bad_json_fails_closed_without_fabricated_segments(self):
        api = FakeGemma("always_bad_json")
        with self.assertRaisesRegex(RuntimeError, "repair exhausted"):
            production_functions()["transform_segments"](api, segments([300]), [], "en")
        self.assertEqual(len(api.calls), 5)

    def test_permanent_auth_error_is_not_retried(self):
        api = FakeGemma("http_403")
        with self.assertRaisesRegex(FakeGeminiAPIError, "403"):
            production_functions()["transform_segments"](api, segments([300]), [], "en")
        self.assertEqual(len(api.calls), 1)

    def test_prior_valid_chunk_remains_checkpointed_after_bad_json(self):
        class LaterFailure(FakeGemma):
            def structured(self, prompt, schema, **kwargs):
                req = json.loads(prompt[prompt.rfind("\n[") + 1:])
                if req and req[0]["id"] >= 12:
                    raise FakeGeminiAPIError("Gemma 4 Structured Output invalid JSON")
                return super().structured(prompt, schema, **kwargs)

        api = LaterFailure("none")
        saved = []
        with self.assertRaisesRegex(RuntimeError, "repair exhausted"):
            production_functions()["transform_segments"](
                api, segments(list(range(13))), [], "en",
                checkpoint_callback=lambda rows, total: saved.append((len(rows), total)),
            )
        self.assertEqual(saved, [(12, 13)])


if __name__ == "__main__":
    unittest.main()
