"""Offline regression for the P260-L01 Gemma 4 multi-language recovery."""
import unittest

from gemini_multi_production_runner import (
    LANGS,
    is_transient_gemini_error,
    merge_translation_rows,
    row_missing_languages,
    translate_batch_with_provider_fallback,
    translation_target_groups,
)


class RecordingGemma4:
    def __init__(self):
        self.calls = []

    def structured(self, prompt, schema, **kwargs):
        cols = [
            x for x in schema["properties"]["segments"]["items"]["required"]
            if x != "segment_id"
        ]
        self.calls.append(cols)
        # Every subgroup has exactly the requested schema keys.
        ids = [0, 1]
        return {
            "segments": [
                {"segment_id": sid, **{lang: f"{lang}:translated:{sid}" for lang in cols}}
                for sid in ids
            ]
        }, None


class Gemma4MultilingualRecoveryTest(unittest.TestCase):
    def test_all_15_languages_use_bounded_subgroups(self):
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
