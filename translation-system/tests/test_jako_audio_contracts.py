import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "translation-system"))
from natural_tts_config import MAX_SPEEDUP, MAX_SPEEDUP_BY_LANGUAGE, NATURAL_TTS_PROFILES


class JakoAudioWorkflowTests(unittest.TestCase):
    def test_quick_review_exposes_all_nine_audio_languages(self):
        ui = (ROOT / "studio/review.html").read_text(encoding="utf-8")
        js = (ROOT / "studio/review-editor.js").read_text(encoding="utf-8")
        for lang in ("en", "th", "es", "id", "vi", "hi", "ta", "ja", "ko"):
            self.assertIn('data-output-lang="' + lang + '"', ui)
            self.assertIn(lang + ':', js)
        self.assertEqual(ui.count('data-output-lang="'), 9)

    def test_course_overview_exposes_japanese_and_korean_previews_without_duplicates(self):
        script = (ROOT / "bridge/apps-script/Code.gs").read_text(encoding="utf-8")
        review = script.split("function courseFilesOverview_(taskId)", 1)[1].split("function formalizableCanonicalName_", 1)[0]
        self.assertIn('"ja", "ko"', review)
        self.assertIn("formalLangs[audioBaseLang_(name)] = true", review)
        self.assertIn('return !formalLangs[lang]', review)
        self.assertIn("尚未完成影片對時", review)

    def test_natural_voice_is_only_tts_engine_and_has_jako_caps(self):
        runner = (ROOT / "translation-system/tts_runner.py").read_text(encoding="utf-8")
        self.assertIn("render_natural_language", runner)
        self.assertIn("max_speedup=MAX_SPEEDUP_BY_LANGUAGE.get(lang, MAX_SPEEDUP)", runner)
        self.assertEqual(MAX_SPEEDUP, 1.08)
        self.assertGreater(MAX_SPEEDUP_BY_LANGUAGE["ja"], 1.09585)
        self.assertGreater(MAX_SPEEDUP_BY_LANGUAGE["ko"], 1.138172)
        self.assertLessEqual(MAX_SPEEDUP_BY_LANGUAGE["ja"], 1.12)
        self.assertLessEqual(MAX_SPEEDUP_BY_LANGUAGE["ko"], 1.16)
        for language in ("ja", "ko"):
            self.assertEqual(NATURAL_TTS_PROFILES[language]["engine"], "edge")
        self.assertIn('else ("manifest", "alignment_report")', runner)
        self.assertIn('if timeline_info["needs_review"]:', runner)
        self.assertIn('wav_to_mp3(preview_wav, preview_mp3)\n    else:\n        wav_to_mp3(timeline_wav, timeline_mp3)', runner)
        self.assertNotIn('and find_file(drive, audio_folder, f"{lang}.preview.mp3")', runner)


if __name__ == "__main__":
    unittest.main()
