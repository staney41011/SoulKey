"""Offline regression for the P260-L01 Gemma 4 multi-language recovery."""
import ast
from pathlib import Path
import unittest

# Compile only the pure production functions. CI's fast syntax job does not
# install Google OAuth libraries; avoid importing Google services here.
SOURCE = (Path(__file__).resolve().parents[1] /
          "gemini_multi_production_runner.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
NAMES = {
    "is_transient_gemini_error",
    "translate_batch_with_provider_fallback",
    "translation_target_groups",
    "row_missing_languages",
    "merge_translation_rows",
}
MODULE = ast.Module(
    body=[n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name in NAMES],
    type_ignores=[],
)
NS = {"SUPPORTED_TARGETS": {"th", "es", "id", "vi"}}
for n in TREE.body:
    if isinstance(n, ast.Assign):
        for target in n.targets:
            if isinstance(target, ast.Name) and target.id in {"LANGS", "TRANSIENT_GEMINI_MARKERS"}:
                NS[target.id] = ast.literal_eval(n.value)
exec(compile(ast.fix_missing_locations(MODULE), "<SoulKey multi functions>", "exec"), NS)
LANGS = NS["LANGS"]
is_transient_gemini_error = NS["is_transient_gemini_error"]
merge_translation_rows = NS["merge_translation_rows"]
row_missing_languages = NS["row_missing_languages"]
translate_batch_with_provider_fallback = NS["translate_batch_with_provider_fallback"]
translation_target_groups = NS["translation_target_groups"]


class RecordingGemma4:
    def __init__(self):
        self.calls = []


def fake_gemini_translate_with_backoff(client, batch, glossary, langs, **kwargs):
    client.calls.append(list(langs))
    return {
        "segments": [
            {"segment_id": sid["id"],
             **{lang: f"{lang}:translated:{sid['id']}" for lang in langs}}
            for sid in batch
        ]
    }


NS["gemini_translate_with_backoff"] = fake_gemini_translate_with_backoff


class Gemma4MultilingualRecoveryTest(unittest.TestCase):
    def test_all_15_languages_use_bounded_subgroups(self):
        # Ensure the real main loop uses and persists these groups, not merely
        # that the helper exists.
        self.assertIn("for group in translation_target_groups(missing_langs)", SOURCE)
        self.assertIn("Translation checkpoint saved for", SOURCE)
        groups = translation_target_groups(LANGS)
        self.assertEqual(len(groups), 5)
        self.assertTrue(all(0 < len(x) <= 3 for x in groups))
        self.assertEqual([x for group in groups for x in group], LANGS)

    def test_missing_language_resume_can_skip_completed_group(self):
        source = [{"id": 0, "text": "part zero"}, {"id": 1, "text": "part one"}]
        gemma = RecordingGemma4()
        translated = {}
        groups = translation_target_groups(LANGS)
        for group in groups:
            needed = [
                lang for lang in group
                if any(lang in row_missing_languages(translated.get(s["id"]), [lang])
                       for s in source)
            ]
            rows, engine = translate_batch_with_provider_fallback(
                gemma, None, source, "", needed
            )
            self.assertEqual(engine, "gemini")
            self.assertEqual(sorted(x["segment_id"] for x in rows), [0, 1])
            merge_translation_rows(translated, rows, needed)
        self.assertEqual(len(gemma.calls), 5)
        self.assertTrue(all(not row_missing_languages(translated[x], LANGS) for x in (0, 1)))
        # A recovered checkpoint has all languages; do not re-request one.
        self.assertEqual([
            lang for lang in groups[0]
            if any(lang in row_missing_languages(translated.get(s["id"]), [lang])
                   for s in source)
        ], [])

    def test_invalid_structured_json_is_transient_retry(self):
        self.assertTrue(is_transient_gemini_error(
            RuntimeError("Gemma 4 Structured Output invalid JSON: Extra data")
        ))
        self.assertFalse(is_transient_gemini_error(
            RuntimeError("Authentication failed: invalid API key")
        ))


if __name__ == "__main__":
    unittest.main()
