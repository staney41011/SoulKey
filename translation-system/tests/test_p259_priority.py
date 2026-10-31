"""Offline scheduling safety checks for the fourth lesson's six languages."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from p259_priority import (
    PRIORITY_LANGUAGE_CODES,
    is_priority,
    prioritize_translation_jobs,
    tts_job_passes,
)


class PriorityTests(unittest.TestCase):
    def test_exact_six_languages_and_human_english_final(self):
        self.assertEqual(PRIORITY_LANGUAGE_CODES, ("en", "th", "es", "id", "vi", "km"))
        self.assertTrue(all(is_priority("P259-L04", x) for x in PRIORITY_LANGUAGE_CODES))
        self.assertFalse(is_priority("P259-L04", "ta"))
        self.assertFalse(is_priority("P259-L04", "hi"))
        self.assertFalse(is_priority("P259-L03", "th"))

    def test_gemma_only_reorders_missing_ai_languages(self):
        task = lambda ident: {"task_id": ident}
        jobs = [
            (task("P259-L01"), "final-1", "vi"),
            (task("P259-L04"), "final-4", "ta"),
            (task("P259-L04"), "final-4", "id"),
            (task("P259-L02"), "final-2", "hi"),
            (task("P259-L04"), "final-4", "vi"),
        ]
        sorted_jobs = prioritize_translation_jobs(jobs)
        self.assertEqual([item[2] for item in sorted_jobs[:2]], ["id", "vi"])
        self.assertEqual([item[0]["task_id"] for item in sorted_jobs[2:]],
                         ["P259-L01", "P259-L04", "P259-L02"])
        self.assertEqual(len(sorted_jobs), len(jobs))

    def test_tts_schedules_six_once_before_other_58(self):
        tasks = [{"task_id": "P259-L01"}, {"task_id": "P259-L04"}, {"task_id": "P259-L02"}]
        languages = ["en", "th", "es", "id", "vi", "km", "hi", "ta", "ja"]
        selected = [(task["task_id"], lang) for task, priority_only in tts_job_passes(tasks)
                    for lang in languages
                    if is_priority(task["task_id"], lang) == priority_only]
        self.assertEqual(selected[:6], [("P259-L04", lang)
                                        for lang in PRIORITY_LANGUAGE_CODES])
        self.assertEqual(len(selected), len(tasks) * len(languages))
        self.assertEqual(len(set(selected)), len(selected))
        self.assertEqual(selected[6], ("P259-L01", "en"))


if __name__ == "__main__":
    unittest.main()
