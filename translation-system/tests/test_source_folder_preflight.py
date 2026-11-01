"""Read-only source-folder preflight; no cloud access or API keys."""
import sys
import types
import unittest
from unittest.mock import Mock, patch

from web_job_worker import preflight_source_lesson_folders


class LessonPreflightTests(unittest.TestCase):
    def _modules(self, rows, resolver):
        config = types.ModuleType("config")
        config.SPREADSHEET_ID = "fake-spreadsheet"
        config.TASK_SHEET_RANGE = "任務佇列!A2:Z"
        io = types.ModuleType("google_io")
        io.build_google_services = Mock(return_value=("drive", "sheets"))
        io.read_values = Mock(return_value=rows)
        paths = types.ModuleType("lesson_paths")
        paths.resolve_lesson_folders = resolver
        return patch.dict(sys.modules, {
            "config": config, "google_io": io, "lesson_paths": paths,
        })

    def test_existing_lesson_passes_without_writes(self):
        check = Mock(return_value={"lesson": "ok"})
        with self._modules([["P259-L04", "259", "第4堂"]], check):
            preflight_source_lesson_folders(["P259-L04"])
        check.assert_called_once_with("drive", "sheets", 259, "第4堂")

    def test_missing_period_folder_fails_before_gpu(self):
        check = Mock(side_effect=RuntimeError("期數設定找不到第 260 期的資料夾URL。"))
        with self._modules([["P260-L04", "260", "第4堂"]], check):
            with self.assertRaisesRegex(RuntimeError, "P260-L04.*期數設定"):
                preflight_source_lesson_folders(["P260-L04"])

    def test_unregistered_task_blocked(self):
        check = Mock()
        with self._modules([], check):
            with self.assertRaisesRegex(RuntimeError, "未登錄"):
                preflight_source_lesson_folders(["P260-L05"])
        check.assert_not_called()


if __name__ == "__main__":
    unittest.main()
