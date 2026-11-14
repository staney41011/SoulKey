"""Regression tests: never use a subtitle cue as original-video runtime."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from source_video_duration import youtube_video_id, verified_original_duration


class OriginalVideoDurationTests(unittest.TestCase):
    def test_all_three_p261_original_video_lengths(self):
        for video_id, seconds in [
            ("4l1T2MlQYUI", 1896),
            ("3B7s7r-rn9o", 2056),
            ("yndPMtAH8vM", 1827),
        ]:
            result, basis = verified_original_duration(
                "https://youtu.be/" + video_id)
            self.assertEqual(result, seconds)
            self.assertEqual(basis, "verified_original_video_registry")

    def test_source_metadata_precedes_verified_registry(self):
        result, basis = verified_original_duration(
            "https://youtu.be/yndPMtAH8vM",
            {"id": "yndPMtAH8vM", "duration": 1827})
        self.assertEqual((result, basis), (1827, "original_video_source_info"))

    def test_mismatched_youtube_source_is_not_accepted(self):
        with self.assertRaisesRegex(ValueError, "video ID"):
            verified_original_duration(
                "https://youtu.be/4l1T2MlQYUI",
                {"id": "3B7s7r-rn9o", "duration": 3105})

    def test_subtitle_timestamps_are_not_duration_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "verified_video_durations.json"
            db.write_text("{}", encoding="utf-8")
            result, basis = verified_original_duration(
                "https://youtu.be/Unkn0wnVid0", {"segments": [
                    {"start": 0, "end": 3105}]}, db)
            self.assertIsNone(result)
            self.assertEqual(basis, "missing_verified_original_video_duration")

    def test_youtube_url_forms(self):
        for url in [
            "https://www.youtube.com/watch?v=4l1T2MlQYUI&t=5",
            "https://youtu.be/4l1T2MlQYUI",
            "https://m.youtube.com/watch?v=4l1T2MlQYUI",
        ]:
            self.assertEqual(youtube_video_id(url), "4l1T2MlQYUI")
        self.assertEqual(youtube_video_id("https://evil.example/4l1T2MlQYUI"), "")


if __name__ == "__main__":
    unittest.main()
