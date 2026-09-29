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

    def test_bridge_drive_review_contract_covers_zh_en_and_cc(self):
        bridge = read("bridge/apps-script/Code.gs")
        self.assertIn('if (kind === "zh")', bridge)
        self.assertIn('if (kind === "en")', bridge)
        self.assertIn("loadZhReviewChunk_", bridge)
        self.assertIn('"en.json"', bridge)
        self.assertIn('"youtube.en.json"', bridge)
        self.assertIn("alignEnglishCcToReviewItems_", bridge)

    def test_batch_resume_does_not_eagerly_require_asr_setup(self):
        batch = read("translation-system/batch_full_runner.py")
        main_tail = batch.split("def main():", 1)[1]
        self.assertNotIn("prepare_youtube_runtime(system_dir)\n    prepare_asr_model()", main_tail)
        self.assertIn("segments.json already exists", batch)
        self.assertIn("guest PO token / checkpoint", batch)

    def test_gemini_source_fallback_has_transport_retries(self):
        source = read("translation-system/gemini_source_runner.py")
        self.assertIn("max_attempts=4", source)

    def test_human_finals_invalidate_completed_downstream_work(self):
        bridge = read("bridge/apps-script/Code.gs")
        self.assertIn("invalidateDownstreamAfterHumanFinal_", bridge)
        self.assertIn('taskId,\n      "multi"', bridge)
        self.assertIn('taskId,\n      "tts"', bridge)

    def test_language_plan_changes_stale_completed_outputs(self):
        bridge = read("bridge/apps-script/Code.gs")
        app = read("studio/app-20260923-48.js")
        self.assertIn("languagePlanSignatures_", bridge)
        self.assertIn("translation_changed", bridge)
        self.assertIn("audio_changed", bridge)
        self.assertIn("requestTaskStatuses()", app)

    def test_quick_review_writes_require_bridge_auth(self):
        bridge = read("bridge/apps-script/Code.gs")
        editor = read("studio/review-editor.js")
        do_post = bridge.split("function doPost(e)", 1)[1].split(
            "function bridgeRequest", 1
        )[0]
        auth_check = do_post.index("if (!bridgeKey || bridgeKey !== expectedKey)")
        for action in (
            'action === "review_share_draft_save"',
            'action === "review_share_finalize"',
            'action === "review_share_finalize_en"',
            'action === "review_finish"',
        ):
            self.assertGreater(do_post.index(action), auth_check)
        self.assertIn("bridge_key:bridgeKeyValue()", editor)

    def test_chinese_stage_dispatches_full_asr_polish_flow(self):
        app = read("studio/app-20260923-48.js")
        worker = read("translation-system/web_job_worker.py")
        self.assertIn('const dispatchStage=next.key==="zh" ? "zh" : next.key', app)
        self.assertIn('if args.stage == "zh":', worker)
        self.assertIn('"--stage", "polish"', worker)
        self.assertNotIn(
            'const dispatchStage=next.key==="zh" ? "metadata" : next.key',
            app,
        )

    def test_missing_youtube_cookies_do_not_block_source_acquisition(self):
        app = read("studio/app-20260923-48.js")
        worker = read("translation-system/web_job_worker.py")
        self.assertNotIn("現在執行只會再次失敗", app)
        self.assertIn("guest PO token / anonymous clients", worker)
        self.assertNotIn("Kaggle API 觸發不會可靠保留 Notebook Secret", worker)

    def test_replacing_youtube_url_invalidates_derived_outputs(self):
        bridge = read("bridge/apps-script/Code.gs")
        self.assertIn("const sourceChanged", bridge)
        self.assertIn("YouTube 來源網址已變更；舊輸出不可沿用", bridge)
        self.assertIn('["zh", "en-review", "multi", "tts"]', bridge)


if __name__ == "__main__":
    unittest.main()
