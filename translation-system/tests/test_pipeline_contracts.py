import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


class PipelineContracts(unittest.TestCase):
    def test_studio_review_pages_have_drive_fallbacks(self):
        app = read("studio/app-20260923-48.js")
        quick = read("studio/review-editor.js")

        self.assertIn('requestReviewData(taskId,"zh",0)', app)
        self.assertIn('requestReviewData(taskId,"en",0)', app)
        self.assertIn('requestDriveReview("zh",0)', quick)
        self.assertIn('requestDriveReview("en",0)', quick)

    def test_github_cache_is_not_the_only_review_source(self):
        app = read("studio/app-20260923-48.js")
        quick = read("studio/review-editor.js")
        self.assertIn("Google Drive", app)
        self.assertIn("Google Drive", quick)
        self.assertIn("review_cache_seed", app)

    def test_batch_rebuilds_review_cache_and_requires_all_audio(self):
        batch = read("translation-system/batch_full_runner.py")
        self.assertIn("ensure_review_cache(", batch)
        self.assertIn("missing_audio", batch)
        self.assertIn('"en-review"', batch)
        self.assertIn('"zh"', batch)

    def test_requested_language_selection_reaches_gemini_runner(self):
        worker = read("translation-system/web_job_worker.py")
        multi = read("translation-system/gemini_multi_production_runner.py")
        self.assertIn('"--langs", translate_langs', worker)
        self.assertIn("requested = [x for x in LANGS if x in set(requested)]", multi)
        self.assertIn("for lang in requested:", multi)

    def test_checkpoints_are_bound_to_english_final(self):
        multi = read("translation-system/gemini_multi_production_runner.py")
        self.assertIn("source_sha256", multi)
        self.assertIn("English Final 已變更", multi)
        self.assertIn('"version": 3', multi)

    def test_tts_resume_is_bound_to_translation_revision(self):
        engine = read("translation-system/tts_engine.py")
        runner = read("translation-system/tts_runner.py")
        self.assertIn("segments_fingerprint", engine)
        self.assertIn('"source_sha256": segments_fingerprint(segments)', engine)
        self.assertIn('manifest.get("source_sha256")', runner)

    def test_partial_tts_failure_is_not_success(self):
        runner = read("translation-system/tts_runner.py")
        self.assertIn("any_failed = True", runner)
        self.assertIn("[TTS ERROR]", runner)
        self.assertRegex(runner, r"if any_failed:\s+print\([\s\S]*?return 1")

    def test_kaggle_log_step_does_not_download_all_outputs(self):
        workflow = read(".github/workflows/kaggle_web_job.yml")
        # A prose comment may mention the old command; there must be no shell
        # line that actually executes it.
        self.assertIsNone(
            re.search(r"^\s*kaggle kernels output\b", workflow, flags=re.M)
        )
        self.assertIn("timeout 90s kaggle kernels logs", workflow)

    def test_bridge_drive_review_contract_covers_zh_and_en(self):
        bridge = read("bridge/apps-script/Code.gs")
        self.assertIn('if (kind === "zh")', bridge)
        self.assertIn('if (kind === "en")', bridge)
        self.assertIn("loadZhReviewChunk_", bridge)
        self.assertIn('"en.json"', bridge)


if __name__ == "__main__":
    unittest.main()
