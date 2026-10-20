"""Production routes use A+B fit without rebuilding existing approved output."""
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[2]

def code(rel):
    return (ROOT / rel).read_text(encoding="utf8")


class SmartTTSProduction(unittest.TestCase):
    def test_default_is_smart_with_legacy_emergency_only(self):
        runner=code("translation-system/tts_runner.py")
        self.assertIn('default=True,',runner)
        self.assertIn('--legacy-tts-timing',runner)
        self.assertIn('smart_fit_pilot=args.smart_fit_pilot',runner)
        self.assertIn('if (\n                        not args.force\n                        and existing_natural_output(',runner)
        self.assertIn('existing_natural_output(',runner)

    def test_video_duration_is_hard_stop(self):
        runner=code("translation-system/tts_runner.py")
        self.assertIn('args.smart_fit_pilot and not video_duration',runner)
        self.assertIn('original source_info.json duration',runner)
        self.assertIn('encoded_seconds > source_duration',runner)
        self.assertIn('timeline_mp3.unlink(missing_ok=True)',runner)
        self.assertIn('"needs_review"',runner)
        self.assertIn('if args.strict_delivery and strict_review:',runner)

    def test_review_preview_is_uploaded_but_formal_mp3_is_never_faked(self):
        runner=code("translation-system/tts_runner.py")
        self.assertNotIn("smart_fit_review.mp3",runner)
        self.assertIn('("preview_mp3", "alignment_report", "manifest")',runner)
        self.assertIn('upload_natural_outputs(',runner)
        self.assertIn('delivered=verify_uploaded_natural_output(',runner)
        self.assertIn('timeline_mp3.unlink(missing_ok=True)',runner)
        self.assertIn('if result["status"]=="needs_review"',runner)
        self.assertIn('f"{lang}.preview.mp3"',runner)
        self.assertIn('未發布超時正式 MP3',runner)

    def test_studio_and_batch_always_route_through_smart_fit(self):
        worker=code("translation-system/web_job_worker.py")
        batch=code("translation-system/batch_full_runner.py")
        self.assertEqual(worker.count('"--smart-fit-pilot",'),2)
        self.assertIn('"--smart-fit-pilot",',batch)
        self.assertEqual(worker.count('"--strict-delivery",'),2)
        self.assertIn('"--strict-delivery",',batch)

if __name__ == "__main__":
    unittest.main()
