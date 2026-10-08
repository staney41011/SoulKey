import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


class PipelineContracts(unittest.TestCase):
    def test_new_lessons_require_central_registration_before_execution(self):
        app = read("studio/app-20260923-48.js")
        bridge = read("bridge/apps-script/Code.gs")
        self.assertIn("confirmedRemoteTaskIds = new Set(", app)
        self.assertIn('if(!confirmedRemoteTaskIds.has(taskId))', app)
        self.assertIn('if(data.type==="tasks_saved")', app)
        self.assertIn("const sentToCloud=submitBridgePost(", app)
        self.assertIn('error: "task_not_registered"', bridge)
        self.assertIn('readTasks_().some(function(item)', bridge)
        self.assertIn('const codeNumber = Number(', bridge)
        self.assertNotIn('(code + " " + name).replace(/[^0-9]/g, "")', bridge)
        self.assertIn('ensurePeriodStructure_(period, Number(', bridge)

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

    def test_kaggle_bootstrap_empty_log_retries_before_false_asr_failure(self):
        workflow = read(".github/workflows/kaggle_web_job.yml")
        self.assertIn('ATTEMPT_STARTED_AT="$(date +%s)"', workflow)
        self.assertIn('COMPACT_LOG=', workflow)
        self.assertIn('"$COMPACT_LOG" = "[]"', workflow)
        self.assertIn('"$ATTEMPT_ELAPSED" -lt 120', workflow)
        self.assertIn('if [ "$ATTEMPT" -lt "$MAX_ATTEMPTS" ]; then', workflow)
        self.assertIn('echo "[KAGGLE STARTUP] Retries exhausted', workflow)
        self.assertIn('group: soulkey-kaggle-web-worker', workflow)
        self.assertIn('cancel-in-progress: false', workflow)

    def test_asr_prefers_verified_drive_audio_over_expired_youtube_cookies(self):
        runner = read("translation-system/runner.py")
        self.assertIn('for extension in ("webm", "m4a", "mp3", "wav")', runner)
        self.assertIn('canonical = "source_audio." + extension', runner)
        self.assertIn('item = find_file(drive, folders["source"], canonical)', runner)
        self.assertIn("download_drive_file(drive, item", runner)
        self.assertIn('"source_type": "drive_cached_audio"', runner)
        self.assertIn("if duration < 60:", runner)
        self.assertIn('if audio_path is None:', runner)
        self.assertIn("audio_path, download_meta = download_audio(", runner)
        self.assertIn('"audio_16k_mono.wav"', runner)

    def test_youtube_cc_keeps_chinese_on_asr_and_writes_readable_files(self):
        youtube_io = read("translation-system/youtube_io.py")
        cc_runner = read("translation-system/cc_runner.py")
        runner = read("translation-system/runner.py")

        self.assertIn(
            'AUTO_CC_TARGETS = ("en", "th", "es", "id", "vi", "hi", "ta", "ja", "ko")',
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

        app = read("studio/app-20260923-48.js")
        index = read("studio/index.html")
        self.assertIn('const YOUTUBE_CC_TARGETS = ["en","th","es","id","vi","hi","ta","ja","ko"]', app)
        self.assertIn('if(kind==="asr")', app)
        self.assertIn('zh-TW\\.transcript\\.txt', app)
        self.assertIn("9/9 語純逐字稿已齊全", app)
        self.assertIn("一般使用者只顯示無時間軸純逐字稿", index)
        self.assertIn("429 會逐語言退避重試", index)
        self.assertNotIn("JSON / 時間軸 TXT / SRT / 純逐字稿", index)

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
            "period_reorder",
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
        self.assertIn("function reorderPeriodTasks_", bridge)
        self.assertIn('action:"period_reorder"', app)
        self.assertIn("scheduleDraftOrder", app)
        self.assertIn("套用新順序", read("studio/index.html"))
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
        for code in ("th","es","id","vi","hi","ta"):
            self.assertIn('code:"' + code + '"', app)
            self.assertIn('"' + code + '":', config)
            self.assertIn('"' + code + '"', multi)
        natural = read("translation-system/natural_tts_config.py")
        engine = read("translation-system/gemini_engine.py")
        naming = read("translation-system/drive_naming.py")
        batch = read("translation-system/batch_full_runner.py")
        for code in ("ja", "ko"):
            self.assertIn('code:"' + code + '"', app)
            self.assertIn('"' + code + '":', multi)
            self.assertIn('"' + code + '":', natural)
            self.assertIn('"' + code + '":', engine)
            self.assertIn('"' + code + '":', naming)
            self.assertIn('"' + code + '"', batch)
        self.assertIn('ja-JP-KeitaNeural', natural)
        self.assertIn('ko-KR-InJoonNeural', natural)
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
        self.assertIn("CHECKPOINT_SCHEMA_VERSION = 4", multi)

    def test_multi_checkpoint_migrates_legacy_language_rows_partially(self):
        multi = read("translation-system/gemini_multi_production_runner.py")
        self.assertIn("CHECKPOINT_SCHEMA_VERSION = 4", multi)
        self.assertIn('"languages": active_languages', multi)
        self.assertIn("row_missing_languages", multi)
        self.assertIn("incomplete_source_segments", multi)
        self.assertIn("merge_translation_rows", multi)
        self.assertIn("CHECKPOINT-MIGRATION", multi)
        self.assertIn("fill={','.join(missing_langs)}", multi)
        self.assertIn("missing_langs", multi)
        self.assertIn("requested,", multi)

    def test_tts_resume_is_bound_to_translation_revision(self):
        engine = read("translation-system/tts_engine.py")
        runner = read("translation-system/tts_runner.py")
        self.assertIn("segments_fingerprint", engine)
        self.assertIn('"source_sha256": segments_fingerprint(segments)', engine)
        self.assertIn('manifest.get("source_sha256")', runner)

    def test_zh_polish_falls_back_to_local_qwen(self):
        worker = read("translation-system/web_job_worker.py")
        self.assertIn("def run_polish_with_local_fallback()", worker)
        self.assertIn("polish_runner.py", worker)
        self.assertIn("Qwen3-4B local", worker)
        self.assertIn("polish_engine = run_polish_with_local_fallback()", worker)

    def test_asr_bypasses_pyav_for_normalized_wav(self):
        asr = read("translation-system/asr.py")
        self.assertIn("def _load_local_pcm(", asr)
        self.assertIn("wavfile.read", asr)
        self.assertIn("audio_samples = _load_local_pcm(audio_path)", asr)
        self.assertIn("model.transcribe(\n        audio_samples,", asr)
        self.assertNotIn("model.transcribe(\n        str(audio_path),", asr)

    def test_tts_token_length_accepts_transformers_batch_encoding(self):
        engine = read("translation-system/tts_engine.py")
        block = engine.split("def _input_length(inputs):", 1)[1].split(
            "def _numeric_spoken_fallback", 1
        )[0]
        self.assertIn('inputs.get("input_ids")', block)
        self.assertNotIn("isinstance(inputs, dict)", block)

    def test_youtube_audio_prefers_true_auto_dub_over_generic_en(self):
        youtube_io = read("translation-system/youtube_io.py")

        self.assertIn("def _requested_track_score(", youtube_io)
        self.assertIn("dubbed-auto", youtube_io)
        self.assertIn('"is_original_hint"', youtube_io)
        self.assertIn("1 if dubbed else 0", youtube_io)
        self.assertIn("1 if audio_only else 0", youtube_io)
        self.assertIn("best = max(", youtube_io)
        self.assertIn("選定主音軌", youtube_io)

    def test_youtube_audio_filename_keeps_language_code(self):
        youtube_io = read("translation-system/youtube_io.py")
        runner = read("translation-system/tts_runner.py")

        self.assertIn(
            'destination.parent / (destination.name + "." + raw_ext)',
            youtube_io,
        )
        self.assertIn(
            'destination.name + "." + preferred_codec',
            youtube_io,
        )
        self.assertNotIn(
            'destination.with_suffix("." + preferred_codec)',
            youtube_io,
        )
        self.assertNotIn(
            "download_multilingual_audio_tracks",
            runner,
        )

    def test_youtube_multiaudio_download_reuses_discovery_client(self):
        youtube_io = read("translation-system/youtube_io.py")

        self.assertIn('"_soulkey_discovery_client"', youtube_io)
        self.assertIn('"discovery_client"', youtube_io)
        self.assertIn('"discovery_extractor_args"', youtube_io)
        self.assertIn("def _download_audio_with_discovery_profile(", youtube_io)
        self.assertIn("same-client fallback", youtube_io)
        self.assertIn("def _requested_track_score(", youtube_io)
        self.assertIn("best = max(", youtube_io)
        self.assertNotIn(
            "_extract_info(\n                    url=url,\n                    options=options,\n                    download=True",
            youtube_io,
        )

    def test_youtube_multiaudio_probes_multiple_player_clients(self):
        youtube_io = read("translation-system/youtube_io.py")

        self.assertIn("def _audio_discovery_attempts(", youtube_io)
        self.assertIn("def _audio_language_groups_from_info(", youtube_io)
        self.assertIn("def _audio_discovery_score(", youtube_io)
        self.assertIn('for client in ("web", "web_safari", "mweb")', youtube_io)
        self.assertIn('"web_embedded"', youtube_io)
        self.assertIn('"android_vr"', youtube_io)
        self.assertIn("successful_clients", youtube_io)
        self.assertIn("discovery_clients", youtube_io)
        self.assertIn("合併後語言音軌", youtube_io)
        self.assertIn("requested_languages=requested_languages", youtube_io)

    def test_audio_stages_use_cpu_natural_tts_without_youtube_probe(self):
        worker = read("translation-system/web_job_worker.py")
        workflow = read(".github/workflows/kaggle_web_job.yml")

        tts_branch = worker.split('elif args.stage == "tts":', 1)[1].split(
            'elif args.stage == "batch":', 1
        )[0]
        self.assertNotIn("require_gpu_runtime", tts_branch)
        self.assertNotIn("prepare_youtube_runtime()", tts_branch)
        self.assertIn("Natural TTS v2", tts_branch)

        finish_branch = worker.split('elif args.stage == "finish":', 1)[1]
        self.assertNotIn('require_gpu_runtime("tts")', finish_branch)
        self.assertIn("Natural TTS v2", finish_branch)

        self.assertIn('gpu_stages = {"zh", "asr", "batch"}', workflow)
        self.assertNotIn('^(zh|asr|tts)$', workflow)

    def test_single_language_tts_failure_does_not_fail_worker(self):
        runner = read("translation-system/tts_runner.py")

        failed_block = runner.split("if failed:", 1)[1].split(
            'elif status == "完成":', 1
        )[0]
        self.assertIn("mark_needs_review(", failed_block)
        self.assertNotIn("any_failed = True", failed_block)
        self.assertIn("單一語言若失敗會保留為 needs_review", runner)

    def test_natural_tts_is_primary_and_youtube_is_benchmark_only(self):
        runner = read("translation-system/tts_runner.py")
        batch = read("translation-system/batch_full_runner.py")
        bridge = read("bridge/apps-script/Code.gs")

        self.assertNotIn(
            "from youtube_io import download_multilingual_audio_tracks",
            runner,
        )
        self.assertIn("build_speech_blocks", runner)
        self.assertIn("render_blocks", runner)
        self.assertIn("edge-natural-v2", runner)
        self.assertIn("YouTube 音軌僅作 benchmark", runner)
        self.assertIn('[f"{lang}.final.json", f"{lang}.json"]', runner)

        self.assertNotIn("has_youtube or has_tts", batch)
        self.assertIn("if not has_tts:", batch)

        overview = bridge.split("function courseFilesOverview_(taskId)", 1)[1].split(
            "function formalizableCanonicalName_", 1
        )[0]
        self.assertIn("priority = 100", overview)
        self.assertIn("priority = 40", overview)
        self.assertIn('lang + ".preview.mp3"', overview)

    def test_natural_tts_uses_continuous_total_duration_policy(self):
        runner = read("translation-system/tts_runner.py")
        planner = read("translation-system/natural_tts_planner.py")
        assembler = read("translation-system/natural_tts_assemble.py")

        self.assertIn("assemble_continuous_with_limit", runner)
        self.assertIn('"assembly_policy": "continuous_total_duration"', runner)
        self.assertIn('"source_info.json"', runner)
        self.assertIn('"source_info.duration"', runner)
        self.assertNotIn("gap >= gap_split_seconds", planner)
        self.assertIn("required_speedup", assembler)
        self.assertIn("MAX_SPEEDUP", assembler)

    def test_tts_fingerprint_uses_same_text_normalization_as_multi(self):
        engine = read("translation-system/tts_engine.py")
        self.assertIn('text = str(seg.get("text") or "").strip()', engine)
        self.assertIn("if not text:", engine)
        self.assertIn("continue", engine)

    def test_tts_worker_self_heals_multi_before_non_english_audio(self):
        worker = read("translation-system/web_job_worker.py")
        self.assertIn('"zh", "polish", "vernacular", "en", "multi", "tts", "batch"', worker)
        self.assertIn("[TTS:DEPENDENCY]", worker)
        self.assertIn("gemini_multi_production_runner.py", worker)
        tts_branch = worker.split('elif args.stage == "tts":', 1)[1].split('elif args.stage == "batch":', 1)[0]
        self.assertLess(
            tts_branch.index("gemini_multi_production_runner.py"),
            tts_branch.index("tts_runner.py"),
        )

    def test_tts_waits_for_matching_multi_revision(self):
        runner = read("translation-system/tts_runner.py")
        multi = read("translation-system/gemini_multi_production_runner.py")

        self.assertIn('"source_sha256": str(source_sha256 or "")', multi)
        self.assertIn("source_sha256=source_sha256", multi)
        self.assertIn("load_english_final_fingerprint", runner)
        self.assertIn("validate_translation_revision", runner)
        self.assertIn("latest_stage_status", runner)
        self.assertIn("最新 multi 狀態不是 done", runner)
        self.assertIn("UpstreamTranslationNotReady", runner)
        self.assertIn("等待與目前 English Final 相符的 multi 翻譯", runner)
        self.assertIn("translation_payload", runner)
        self.assertIn("declared_sha != en_source_sha256", runner)

    def test_tts_aggregate_status_keeps_per_language_errors(self):
        runner = read("translation-system/tts_runner.py")
        self.assertIn('failure_details = "｜".join(', runner)
        self.assertIn('f"原因：{failure_details}；"', runner)

    def test_tts_never_uses_hosted_inference_api(self):
        config = read("translation-system/config.py")
        engine = read("translation-system/tts_engine.py")
        runner = read("translation-system/tts_runner.py")
        converter = read("translation-system/mms_vits_converter.py")

        self.assertIn('"hi": "facebook/mms-tts-hin"', config)
        self.assertNotIn("GeminiClient", engine)
        self.assertNotIn("synthesize_gemini_language", engine)
        self.assertNotIn("synthesize_gemini_language", runner)
        self.assertNotIn("gemini-3.8-flash-tts", config)
        self.assertIn("MMS_HF_RESOLVE_BASE", converter)
        self.assertIn("urllib.request.Request", converter)
        self.assertNotIn("hf_hub_download", converter)
        self.assertNotIn("dl.fbaipublicfiles.com", converter)

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

    def test_multi_runner_defines_nvidia_usage_before_final_reporting(self):
        multi = read("translation-system/gemini_multi_production_runner.py")
        assignment = "nvidia_used = bool(nvidia_repair_used or nvidia_fallback_used)"
        self.assertIn(assignment, multi)
        self.assertLess(multi.index(assignment), multi.index('"nvidia_second_opinion_used": nvidia_used'))

    def test_english_cc_review_groups_fragments_into_sentences(self):
        app = read("studio/app-20260923-48.js")
        review = read("studio/review-editor.js")

        for source in (app, review):
            self.assertIn("function mergeEnglishTextParts(parts)", source)
            self.assertIn("function englishSentenceEnded(text)", source)

        self.assertIn("function groupEnglishReviewItems(items)", app)
        self.assertIn("const groupedItems=groupEnglishReviewItems(items)", app)
        self.assertIn('data-en-ids=', app)

        self.assertIn("function englishGroups()", review)
        self.assertIn("function writeEnglishGroup(group,text)", review)
        self.assertIn('data-ids=', review)
        self.assertIn("const groups=englishGroups();", review)
        self.assertIn("segments_json:JSON.stringify(finalSegments)", review)

    def test_english_review_persists_drafts_and_loads_final_first(self):
        app = read("studio/app-20260923-48.js")
        bridge = read("bridge/apps-script/Code.gs")

        self.assertIn('action:"review_en_draft_save"', app)
        self.assertIn("function saveEnglishReviewDraft(", app)
        self.assertIn("英文確認進度已儲存", app)
        self.assertIn("正在寫入 Google Drive English Final", app)
        self.assertIn("englishFinalizePendingTaskId", app)

        self.assertIn('action === "review_en_draft_save"', bridge)
        self.assertIn("function reviewEnglishDraftSave_(", bridge)
        self.assertIn('"en.review.draft.json"', bridge)

        en_loader = bridge.split('if (kind === "en") {', 1)[1].split(
            'return { ok: false, error: "unsupported_review_kind" }', 1
        )[0]
        self.assertIn('"en.final.json"', en_loader)
        self.assertIn('"en.review.draft.json"', en_loader)
        self.assertLess(en_loader.index('"en.final.json"'), en_loader.index('"en.json"'))
        self.assertIn('source: "en.final.json"', en_loader)

    def test_tts_cleans_english_overlap_and_keeps_one_voice_seed(self):
        runner = read("translation-system/tts_runner.py")
        engine = read("translation-system/tts_engine.py")

        self.assertIn("def _dedupe_english_segments_for_tts(", runner)
        self.assertIn('if lang == "en":', runner)
        self.assertIn("_dedupe_english_segments_for_tts(segments)", runner)

        self.assertIn("set_seed(seed)", engine)
        self.assertNotIn("set_seed(seed + seg_id + chunk_index)", engine)
        self.assertIn('"voice_policy": "single_deterministic_voice_per_lesson"', engine)

    def test_english_cc_removes_cross_group_rolling_overlap(self):
        app = read("studio/app-20260923-48.js")
        review = read("studio/review-editor.js")
        bridge = read("bridge/apps-script/Code.gs")
        polish = read("translation-system/polish_runner.py")

        for source in (app, review):
            self.assertIn("function englishLeadingOverlapCount(", source)
            self.assertIn("function trimLeadingEnglishOverlap(", source)
            self.assertIn("function dedupeEnglishRows(", source)
            self.assertIn("size>=3", source)
            self.assertIn("duration>=60", source)
            self.assertNotIn("duration>=20", source)

        self.assertIn("function englishLeadingOverlapCount_", bridge)
        self.assertIn("function trimLeadingEnglishOverlap_", bridge)
        self.assertIn("mergeEnglishRollingParts_(matched)", bridge)
        self.assertIn("englishHistory", bridge)

        self.assertIn("def _english_leading_overlap_count(", polish)
        self.assertIn("def _trim_english_leading_overlap(", polish)
        self.assertIn("def _merge_english_rolling_parts(", polish)
        self.assertIn("english_history = \"\"", polish)

    def test_review_video_floats_and_english_share_link_opens_step_two(self):
        app = read("studio/app-20260923-48.js")
        index = read("studio/index.html")
        styles = read("studio/styles.css")
        review = read("studio/review-editor.js")

        self.assertIn('id="zh-review-media-anchor"', index)
        self.assertIn('id="zh-review-media-bar"', index)
        self.assertIn('id="create-en-review-share"', index)
        self.assertIn('id="en-review-share-state"', index)
        self.assertIn("function updateZhReviewVideoFloat()", app)
        self.assertIn('bar.classList.add("floating-video")', app)
        self.assertIn('quickReviewUrl(task,"en")', app)
        self.assertIn('.zh-review-media-bar.floating-video', styles)
        self.assertIn('const requestedStep=String(params.get("step")', review)
        self.assertIn("en:2", review)
        self.assertIn("if(requestedStepNumber===2) setStep(2)", review)

    def test_course_file_overview_can_collapse_and_remember_state(self):
        app = read("studio/app-20260923-48.js")
        index = read("studio/index.html")
        styles = read("studio/styles.css")

        self.assertIn('id="course-files-toggle"', index)
        self.assertIn('id="course-files-body"', index)
        self.assertIn('const COURSE_FILES_COLLAPSED_KEY=', app)
        self.assertIn("function courseFilesCollapsed()", app)
        self.assertIn("function setCourseFilesCollapsed(collapsed,persist=true)", app)
        self.assertIn("setCourseFilesCollapsed(false,true)", app)
        self.assertIn("if(!courseFilesCollapsed()) requestCourseFiles(task.id)", app)
        self.assertIn(".course-files-panel.collapsed", styles)
        self.assertIn(".course-files-body[hidden]", styles)

    def test_task_file_overview_is_read_only_step_after_workflow(self):
        app = read("studio/app-20260923-48.js")
        index = read("studio/index.html")
        bridge = read("bridge/apps-script/Code.gs")

        self.assertIn('id="course-files-panel"', index)
        self.assertIn('id="course-files-list"', index)
        self.assertIn('data-course-files-jump', app)
        self.assertIn('data-course-file-copy', app)
        self.assertIn('function requestCourseFiles(taskId,force=false)', app)
        self.assertIn('function renderCourseFiles(task)', app)
        self.assertIn('action:"course_files"', app)
        self.assertIn('if(data.type==="course_files")', app)
        self.assertIn('if (action === "course_files")', bridge)
        self.assertIn('function courseFilesOverview_(taskId)', bridge)
        self.assertIn('"course_files"', bridge)
        overview = bridge.split("function courseFilesOverview_(taskId)", 1)[1].split(
            "function formalizableCanonicalName_", 1
        )[0]
        self.assertIn('"逐字稿"', overview)
        self.assertIn('"音檔"', overview)
        self.assertIn('"完成影片"', overview)
        self.assertIn('"zh-TW.final.txt"', overview)
        self.assertIn('"en.final.txt"', overview)
        self.assertIn('"youtube.en.transcript.txt"', overview)
        self.assertIn('/\\.mp3$/i', overview)
        self.assertIn('/\\.(mp4|mkv|webm)$/i', overview)
        self.assertNotIn('"03_字幕"', overview)
        self.assertNotIn('key: "subtitle"', overview)
        self.assertNotIn('.srt"', overview)
        self.assertNotIn('key:"course-files"', app)

    def test_studio_surfaces_root_failure_reason_and_removes_p255_test_button(self):
        app = read("studio/app-20260923-48.js")
        index = read("studio/index.html")
        styles = read("studio/styles.css")
        bridge = read("bridge/apps-script/Code.gs")

        self.assertNotIn("run-p255-batch", index)
        self.assertNotIn("run-p255-batch", app)
        self.assertIn("function remoteErrorReason(item)", app)
        self.assertIn("root_error_message", app)
        self.assertIn("失敗原因", app)
        self.assertIn("course-error-reason", styles)
        self.assertIn("stage-message.error", styles)
        self.assertIn("root_error_message: rootErrorMessage", bridge)
        self.assertIn("function isGenericWorkerError_", bridge)
        self.assertIn("CalledProcessError", bridge)
        self.assertIn("Kaggle Kernel 執行失敗", bridge)

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
