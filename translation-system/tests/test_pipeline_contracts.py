import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


class PipelineContracts(unittest.TestCase):
    def test_bridge_protocol_prevents_frontend_deployment_drift(self):
        bridge = read("bridge/apps-script/Code.gs")
        app = read("studio/app-20260923-48.js")
        quick = read("studio/review-editor.js")
        worker = read("translation-system/web_job_worker.py")
        self.assertIn("const BRIDGE_PROTOCOL_VERSION = 9", bridge)
        self.assertIn("bridge_protocol: BRIDGE_PROTOCOL_VERSION", bridge)
        self.assertIn("const REQUIRED_BRIDGE_PROTOCOL = 9", app)
        self.assertIn("const REQUIRED_BRIDGE_PROTOCOL=9", quick)
        self.assertIn("REQUIRED_BRIDGE_PROTOCOL = 9", worker)
        self.assertIn("bridgeProtocolVersion<=0", app)
        self.assertIn("bridgeProtocolVersion<=0", quick)
        self.assertIn("Apps Script Bridge 版本過舊", worker)

    def test_youtube_cc_keeps_chinese_on_asr_and_writes_readable_files(self):
        youtube_io = read("translation-system/youtube_io.py")
        cc_runner = read("translation-system/cc_runner.py")
        runner = read("translation-system/runner.py")

        self.assertIn(
            'AUTO_CC_TARGETS = ("en", "th", "es", "id", "vi", "sd", "ta")',
            youtube_io,
        )
        self.assertNotIn(
            'AUTO_CC_TARGETS = ("zh-Hant"',
            youtube_io,
        )
        self.assertIn('youtube.{target}.txt', youtube_io)
        self.assertIn('youtube.{target}.srt', youtube_io)
        self.assertIn('youtube.{target}.transcript.txt', youtube_io)
        self.assertIn("write_cc_readable_files_from_json", youtube_io)
        self.assertIn("既有 JSON 回填", cc_runner)
        self.assertIn("_download_missing_auto_translations", youtube_io)
        self.assertIn('query["tlang"] = target', youtube_io)
        self.assertIn("HTTP 429，進入退避重試", youtube_io)
        self.assertIn('zh-TW.transcript.txt', read("translation-system/asr.py"))
        self.assertIn('中文一律使用 Taiwan-Breeze ASR', cc_runner)
        self.assertIn('中文只使用原始音軌 Taiwan-Breeze ASR', runner)

    def test_frontend_bridge_actions_have_server_handlers(self):
        app = read("studio/app-20260923-48.js")
        quick = read("studio/review-editor.js")
        bridge = read("bridge/apps-script/Code.gs")
        required_actions = {
            "language_plan_get", "language_plan_save", "language_settings",
            "review_cache_seed", "review_finish", "review_load", "review_save",
            "review_share_draft_save", "review_share_finalize",
            "review_share_finalize_en", "run_stage", "smoke", "status_batch",
            "status_health", "tasks_get", "tasks_upsert", "worker_secret_test",
            "worker_setup", "drive_names_migrate", "task_reschedule",
        }
        for action in required_actions:
            self.assertTrue(
                ("action === \"" + action + "\"" in bridge)
                or ("\"" + action + "\"" in bridge and action in {"status_batch","status_health","tasks_get","language_settings","language_plan_get","review_load"}),
                action,
            )
        self.assertIn('action:"review_cache_seed"', app)
        self.assertIn('action:"review_finish"', quick)

    def test_formal_drive_naming_preserves_canonical_lookups(self):
        naming = read("translation-system/drive_naming.py")
        google_io = read("translation-system/google_io.py")
        bridge = read("bridge/apps-script/Code.gs")
        app = read("studio/app-20260923-48.js")

        self.assertIn("第{period}期_第{lesson}堂課_", naming)
        self.assertIn("SOULKEY_CANONICAL_NAME:", naming)
        self.assertIn("canonical_from_description", google_io)
        self.assertIn("output_label(name)", google_io)
        self.assertIn("formalDriveName_", bridge)
        self.assertIn("canonicalFromDescription_", bridge)
        self.assertIn("migrateFormalDriveNames_", bridge)
        self.assertIn('action:"drive_names_migrate"', app)

    def test_course_reschedule_preserves_stable_identity_and_moves_drive_slot(self):
        bridge = read("bridge/apps-script/Code.gs")
        app = read("studio/app-20260923-48.js")
        config = read("translation-system/config.py")
        naming = read("translation-system/drive_naming.py")

        self.assertIn('"課程UID"', bridge)
        self.assertIn("SKC-", bridge)
        self.assertIn("function rescheduleTask_", bridge)
        self.assertIn("swapLessonFolderPositions_", bridge)
        self.assertIn("lesson-folders-v3:", bridge)
        self.assertIn("const task = taskInfo_(taskId);", bridge)
        self.assertNotIn("function parseTaskId_", bridge)
        self.assertIn('action:"task_reschedule"', app)
        self.assertIn("renderScheduleManager", app)
        self.assertIn('TASK_SHEET_RANGE = "任務佇列!A2:Z"', config)
        self.assertIn('"course_uid": 20', config)
        self.assertIn('re.split(r"[|｜丨]"', naming)

    def test_bridge_and_worker_machine_stages_match(self):
        bridge = read("bridge/apps-script/Code.gs")
        worker = read("translation-system/web_job_worker.py")
        for stage in ("zh","metadata","asr","polish","vernacular","en","multi","tts","finish","cc","batch"):
            self.assertIn('"' + stage + '"', bridge)
            self.assertIn('"' + stage + '"', worker)

    def test_bridge_oauth_token_can_refresh_during_long_jobs(self):
        google_io = read("translation-system/google_io.py")
        self.assertIn("class BridgeCredentials", google_io)
        self.assertIn('"action": "worker_runtime"', google_io)
        self.assertIn("timedelta(minutes=45)", google_io)

    def test_language_codes_align_across_studio_translation_and_tts(self):
        app = read("studio/app-20260923-48.js")
        quick = read("studio/review-editor.js")
        config = read("translation-system/config.py")
        multi = read("translation-system/gemini_multi_production_runner.py")
        for code in ("th","es","id","vi","sd","ta"):
            self.assertIn('code:"' + code + '"', app)
            self.assertIn('"' + code + '":', config)
            self.assertIn('"' + code + '"', multi)
        self.assertIn('en:"English"', quick)
        self.assertIn('"en":', config)

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

    def test_batch_text_outputs_are_bound_to_upstream_revisions(self):
        text_runner = read("translation-system/gemini_text_production_runner.py")
        batch = read("translation-system/batch_full_runner.py")
        self.assertIn('"source_sha256": source_fingerprint(source_segments)', text_runner)
        self.assertIn('"source_sha256": source_fingerprint(payload.get("segments") or [])', text_runner)
        self.assertIn("drive_json_matches_source", batch)
        self.assertIn("polish_changed", batch)
        self.assertIn("vernacular_changed", batch)
        self.assertIn("english_changed", batch)

    def test_legacy_text_outputs_without_fingerprint_are_regenerated(self):
        batch = read("translation-system/batch_full_runner.py")
        self.assertIn(
            "has no source_sha256;",
            batch,
        )
        self.assertIn(
            "force one-time regeneration from the current source.",
            batch,
        )
        self.assertNotIn("legacy metadata upgraded", batch)

    def test_every_multi_checkpoint_keeps_english_source_fingerprint(self):
        multi = read("translation-system/gemini_multi_production_runner.py")
        self.assertIn("缺少 source fingerprint", multi)
        self.assertNotIn("Legacy v2 checkpoints had no source fingerprint. Accept", multi)
        self.assertNotIn(
            "checkpoint_payload(args.task_id, len(source_segments), translations, qa_batches, seq)",
            multi,
        )
        # Resume-QA, per-batch translation, per-batch QA, and final checkpoint
        # must all carry the current English Final fingerprint.
        self.assertGreaterEqual(multi.count("source_sha256,"), 4)

    def test_batch_multi_always_enters_source_aware_checkpoint_runner(self):
        batch = read("translation-system/batch_full_runner.py")
        self.assertNotIn("multi_complete = all(", batch)
        self.assertIn("Merely seeing th/es/... JSON", batch)


if __name__ == "__main__":
    unittest.main()
