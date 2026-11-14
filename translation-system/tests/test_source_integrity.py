import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from source_integrity import (bounds, check_english_coverage,
                              compare_chinese_english_end, compare_manuscript_to_video)


class P261SourceIntegrityTests(unittest.TestCase):
    def test_l01_caption_fallback_allows_small_english_timestamp_margin(self):
        en = [{"start": 0.82, "end": 48}, {"start": 1840.5, "end": 1900}]
        result = check_english_coverage(en, 1896)
        self.assertGreater(result["coverage_ratio"], 0.99)

    def test_l01_chinese_exceeds_english_by_twenty_minutes(self):
        en = [{"start": 0.82, "end": 1900}]
        zh = [{"start": 0.82, "end": 3105}]
        result = compare_chinese_english_end(zh, en)
        self.assertTrue(result["needs_review"])
        self.assertAlmostEqual(result["difference_seconds"], 1205)

    def test_l03_and_l04_have_matching_coverage(self):
        for duration, en_end, zh_end in [(2056, 2054.08, 2054.08),
                                          (1827, 1825.15, 1826.49)]:
            en = [{"start": 0, "end": en_end}]
            zh = [{"start": 0, "end": zh_end}]
            check_english_coverage(en, duration)
            self.assertFalse(compare_chinese_english_end(zh, en)["needs_review"])

    def test_all_languages_use_original_video_not_each_other(self):
        # Exact YouTube length for L01 is 1896s, not either subtitle end.
        english = compare_manuscript_to_video(
            [{"start": 0.82, "end": 1900}], 1896)
        chinese = compare_manuscript_to_video(
            [{"start": 0.82, "end": 3105}], 1896)
        self.assertFalse(english["needs_review"])
        self.assertTrue(chinese["needs_review"])
        self.assertEqual(chinese["reason"], "past_original_video_end")
        self.assertEqual(chinese["overrun_seconds"], 1209)
        self.assertEqual(chinese["original_video_duration"], 1896)

    def test_original_video_reference_for_l03_and_l04(self):
        for duration, chinese_end in [(2056, 2054.08), (1827, 1826.49)]:
            audit = compare_manuscript_to_video(
                [{"start": 0, "end": chinese_end}], duration)
            self.assertFalse(audit["needs_review"])
            self.assertEqual(audit["original_video_duration"], duration)

    def test_mismatched_source_rejected_before_tts(self):
        with self.assertRaisesRegex(ValueError, "beyond source evidence"):
            check_english_coverage([{"start": 0, "end": 3000}], 1896)
        with self.assertRaisesRegex(ValueError, "too little source coverage"):
            check_english_coverage([{"start": 0, "end": 600}], 1896)
        with self.assertRaises(ValueError):
            bounds([{"start": 70, "end": 30}])


if __name__ == "__main__":
    unittest.main()
