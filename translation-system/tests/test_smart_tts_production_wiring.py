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
        self.assertIn('not args.force and not args.smart_fit_pilot',runner)
        self.assertIn('existing_natural_output(',runner)

    def test_video_duration_is_hard_stop(self):
        runner=code("translation-system/tts_runner.py")
        self.assertIn('args.smart_fit_pilot and not video_duration',runner)
        self.assertIn('original source_info.json duration',runner)
        self.assertIn('encoded_seconds > source_duration',runner)
        self.assertIn('timeline_mp3.unlink(missing_ok=True)',runner)
        self.assertIn('"needs_review"',runner)
        self.assertIn('if args.strict_delivery and strict_review:',runner)

    def test_no_overlong_audio_uploaded(self):
        runner=code("translation-system/tts_runner.py")
        self.assertNotIn('smart_fit_review.mp3',runner)
        section=runner.split('if args.smart_fit_pilot and result["status"] == "needs_review":')[1]
        section=section.split('                    else:' + chr(10) + '                        upload_natural_outputs(')[0]
        self.assertIn('("narration_script", "smart_fit_report")',section)
        self.assertNotIn('preview_mp3',section)
        self.assertNotIn('upload_natural_outputs(',section)

    def test_studio_and_batch_always_route_through_smart_fit(self):
        worker=code("translation-system/web_job_worker.py")
        batch=code("translation-system/batch_full_runner.py")
        self.assertEqual(worker.count('"--smart-fit-pilot",'),2)
        self.assertIn('"--smart-fit-pilot",',batch)
        self.assertEqual(worker.count('"--strict-delivery",'),2)
        self.assertIn('"--strict-delivery",',batch)

if __name__ == "__main__":
    unittest.main()
