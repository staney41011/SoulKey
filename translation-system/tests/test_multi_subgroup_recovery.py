"""Offline regression for the P260-L01 Gemma 4 multi-language recovery."""
import ast
import os
import time
from pathlib import Path
import unittest
from unittest.mock import patch

# Compile only the pure production functions. CI's fast syntax job does not
# install Google OAuth libraries; avoid importing Google services here.
SOURCE = (Path(__file__).resolve().parents[1] /
          "gemini_multi_production_runner.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
NAMES = {
    "is_transient_gemini_error",
    "is_hard_quota_error",
    "build_translation_batches",
    "translate_batch_with_provider_fallback",
    "translation_target_groups",
    "row_missing_languages",
    "merge_translation_rows",
    "translate_batch_with_missing_id_recovery",
    "TranslationFailoverClient",
}
MODULE = ast.Module(
    body=[n for n in TREE.body
          if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in NAMES],
    type_ignores=[],
)
NS = {"SUPPORTED_TARGETS": {"th", "es", "id", "vi", "hi", "ja", "ko", "it", "pt"},
      "os": os, "time": time}
for n in TREE.body:
    if isinstance(n, ast.Assign):
        for target in n.targets:
            if isinstance(target, ast.Name) and target.id in {"LANGS", "TRANSIENT_GEMINI_MARKERS"}:
                NS[target.id] = ast.literal_eval(n.value)
exec(compile(ast.fix_missing_locations(MODULE), "<SoulKey multi functions>", "exec"), NS)
LANGS = NS["LANGS"]
is_transient_gemini_error = NS["is_transient_gemini_error"]
is_hard_quota_error = NS["is_hard_quota_error"]
build_translation_batches = NS["build_translation_batches"]
merge_translation_rows = NS["merge_translation_rows"]
row_missing_languages = NS["row_missing_languages"]
translate_batch_with_provider_fallback = NS["translate_batch_with_provider_fallback"]
translation_target_groups = NS["translation_target_groups"]
TranslationFailoverClient = NS["TranslationFailoverClient"]
translate_batch_with_missing_id_recovery = NS["translate_batch_with_missing_id_recovery"]


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


class FakeModel:
    text_model = "gemma-4-26b-a4b-it"

    def __init__(
        self,
        primary_failures=0,
        fail_alternate=False,
        primary_error="HTTP 500 Internal Error",
    ):
        self.primary_failures = primary_failures
        self.fail_alternate = fail_alternate
        self.primary_error = primary_error
        self.primary_calls = 0
        self.calls = []

    def structured(self, prompt, schema, **kwargs):
        model = kwargs.get("model") or self.text_model
        self.calls.append(model)
        if model == self.text_model:
            self.primary_calls += 1
            if self.primary_calls <= self.primary_failures:
                raise RuntimeError(self.primary_error)
        if model != self.text_model and self.fail_alternate:
            raise RuntimeError("HTTP 404 model unavailable")
        return {"segments": [{"segment_id": 1, "ja": "こんにちは"}]}, None


class FailoverRegressionTest(unittest.TestCase):
    def test_gemma4_success_is_kept_as_primary(self):
        fake = FakeModel()
        client = TranslationFailoverClient(fake, primary_attempts=3)
        client.structured("test", {"required": ["segments"]})
        self.assertEqual(fake.calls, ["gemma-4-26b-a4b-it"])
        self.assertFalse(client.fallback_used)

    def test_gemma4_retries_twice_then_succeeds_without_gemini(self):
        fake = FakeModel(primary_failures=2)
        client = TranslationFailoverClient(fake, primary_attempts=3)
        with patch.object(time, "sleep", return_value=None):
            result, _ = client.structured("test", {"required": ["segments"]})
        self.assertEqual(result["segments"][0]["segment_id"], 1)
        self.assertEqual(fake.calls, ["gemma-4-26b-a4b-it"] * 3)
        self.assertFalse(client.fallback_used)

    def test_gemma4_exhausts_three_then_fails_over_and_tries_again_next_group(self):
        fake = FakeModel(primary_failures=99)
        client = TranslationFailoverClient(
            fake, fallback_model="gemini-3.5-flash", primary_attempts=3
        )
        with patch.object(time, "sleep", return_value=None):
            result, _ = client.structured("group one", {"required": ["segments"]})
            client.structured("group two", {"required": ["segments"]})
        self.assertEqual(result["segments"][0]["segment_id"], 1)
        self.assertEqual(fake.calls, (
            ["gemma-4-26b-a4b-it"] * 3 + ["gemini-3.5-flash"]
        ) * 2)
        self.assertTrue(client.fallback_used)
        self.assertIn("gemini-3.5-flash", client.models_used)

    def test_failover_unavailable_is_not_reported_as_success(self):
        fake = FakeModel(primary_failures=99, fail_alternate=True)
        client = TranslationFailoverClient(
            fake, fallback_model="gemini-3.5-flash", primary_attempts=3
        )
        with patch.object(time, "sleep", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "HTTP 404"):
                client.structured("test", {"required": ["segments"]})
        self.assertFalse(client.fallback_used)
        self.assertEqual(client.cooldown_until, 0)
        self.assertEqual(fake.calls,
                         ["gemma-4-26b-a4b-it"] * 3 + ["gemini-3.5-flash"])

    def test_daily_quota_does_not_retry_exhausted_gemma(self):
        fake = FakeModel(
            primary_failures=99,
            primary_error="HTTP 429: limit 20 requests per day, retry in 6h",
        )
        client = TranslationFailoverClient(
            fake, fallback_model="gemini-3.5-flash", primary_attempts=3
        )
        client.structured("test", {"required": ["segments"]})
        self.assertEqual(fake.calls,
                         ["gemma-4-26b-a4b-it", "gemini-3.5-flash"])

    def test_authentication_error_never_tries_fallback(self):
        fake = FakeModel(
            primary_failures=99,
            primary_error="HTTP 401 authentication failed",
        )
        client = TranslationFailoverClient(fake, primary_attempts=3)
        with self.assertRaisesRegex(RuntimeError, "HTTP 401"):
            client.structured("test", {"required": ["segments"]})
        self.assertEqual(fake.calls, ["gemma-4-26b-a4b-it"])

    def test_disabled_fallback_still_attempts_gemma_three_times(self):
        fake = FakeModel(primary_failures=99)
        client = TranslationFailoverClient(
            fake, fallback_model="off", primary_attempts=3
        )
        with patch.object(time, "sleep", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "HTTP 500"):
                client.structured("test", {"required": ["segments"]})
        self.assertEqual(fake.calls, ["gemma-4-26b-a4b-it"] * 3)
        self.assertFalse(client.fallback_used)


class MissingSegmentIdRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.batch = [
            {"id": 18, "text": "First approved English paragraph."},
            {"id": 22, "text": "Second approved English paragraph."},
        ]
        self.langs = ["ko", "it", "pt"]

    def test_sparse_ids_missing_second_segment_retry_only_id22(self):
        calls = []
        def fake(client, nvidia, batch, glossary, langs):
            ids = [x["id"] for x in batch]
            calls.append(ids)
            returned = [18] if len(calls) == 1 else ids
            return [
                {"segment_id": sid, **{lang: f"{sid} {lang}" for lang in langs}}
                for sid in returned
            ], "gemini"
        with patch.dict(NS, {"translate_batch_with_provider_fallback": fake}):
            rows, engine = translate_batch_with_missing_id_recovery(
                None, None, self.batch, "", self.langs
            )
        self.assertEqual(calls, [[18, 22], [22]])
        self.assertEqual([x["segment_id"] for x in rows], [18, 22])
        self.assertEqual(engine, "gemini")

    def test_missing_id_after_all_attempts_fails_closed(self):
        def fake(client, nvidia, batch, glossary, langs):
            ids = [x["id"] for x in batch]
            return [
                {"segment_id": 18, **{lang: "value" for lang in langs}}
            ] if 18 in ids else [], "gemini"
        with patch.dict(NS, {"translate_batch_with_provider_fallback": fake}):
            with self.assertRaisesRegex(RuntimeError, "still missing"):
                translate_batch_with_missing_id_recovery(
                    None, None, self.batch, "", self.langs, max_retries=2
                )

    def test_wrong_or_duplicate_id_rejected(self):
        for returned in ([{"segment_id": 31}],
                         [{"segment_id": 18}, {"segment_id": 18}]):
            def fake(client, nvidia, batch, glossary, langs):
                return [
                    {**x, **{lang: "value" for lang in langs}}
                    for x in returned
                ], "gemini"
            with self.subTest(rows=returned), patch.dict(
                NS, {"translate_batch_with_provider_fallback": fake}
            ):
                with self.assertRaisesRegex(RuntimeError, "(unexpected|duplicate)"):
                    translate_batch_with_missing_id_recovery(
                        None, None, self.batch, "", self.langs
                    )


class Gemma4MultilingualRecoveryTest(unittest.TestCase):
    def test_all_15_languages_use_bounded_subgroups(self):
        # Ensure the real main loop uses and persists these groups, not merely
        # that the helper exists.
        self.assertIn("for group in translation_target_groups(missing_langs)", SOURCE)
        self.assertIn("Translation checkpoint saved for", SOURCE)
        groups = translation_target_groups(LANGS)
        self.assertEqual(len(groups), 5)
        self.assertTrue(all(0 < len(x) <= 3 for x in groups))
        prioritized = ([x for x in LANGS if x in NS["SUPPORTED_TARGETS"]]
                       + [x for x in LANGS if x not in NS["SUPPORTED_TARGETS"]])
        self.assertEqual([x for group in groups for x in group], prioritized)
        self.assertEqual([x for group in groups[:3] for x in group],
                         prioritized[:9])

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

    def test_long_lecture_batches_stay_small_and_keep_sparse_ids(self):
        sources = [
            {"id": 18, "text": "short"},
            {"id": 22, "text": "x" * 851},
            {"id": 27, "text": "y" * 350},
            {"id": 34, "text": "z" * 400},
            {"id": 46, "text": "last"},
        ]
        batches = build_translation_batches(
            sources, max_segments=2, max_chars=900
        )
        self.assertEqual([[s["id"] for s in b] for b in batches],
                         [[18], [22], [27, 34], [46]])
        self.assertTrue(all(len(batch) <= 2 for batch in batches))

    def test_quota_error_detection_and_bounded_retries(self):
        self.assertTrue(is_hard_quota_error(RuntimeError(
            "HTTP 429: Rate limit exceeded: 20 requests per day"
        )))
        self.assertFalse(is_hard_quota_error(RuntimeError(
            "HTTP 429: too many requests per minute"
        )))
        self.assertFalse(is_hard_quota_error(RuntimeError("HTTP 503")))
        self.assertIn("timeout=gemma_timeout", SOURCE)
        self.assertIn('SOULKEY_GEMMA4_TIMEOUT_SECONDS", "95"', SOURCE)
        self.assertIn("max_chars=(900 if len(requested) > 10 else 1600)", SOURCE)

    def test_invalid_structured_json_is_transient_retry(self):
        self.assertTrue(is_transient_gemini_error(
            RuntimeError("Gemma 4 Structured Output invalid JSON: Extra data")
        ))
        self.assertFalse(is_transient_gemini_error(
            RuntimeError("Authentication failed: invalid API key")
        ))


if __name__ == "__main__":
    unittest.main()
