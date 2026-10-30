#!/usr/bin/env python3
"""Offline tests: protect old Apps Script jobs from expired nonce replays."""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest
from unittest.mock import patch
import io

path = Path(__file__).resolve().parents[1] / "bridge_runtime_preflight.py"
spec = importlib.util.spec_from_file_location("bridge_runtime_preflight", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RuntimePreflightTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
        self.base = {
            "ok": True,
            "task_id": "P259-L03",
            "stage": "tts",
            "google_access_token": "PRIVATE_TOKEN_NEVER_LOG",
            "expires_at": (self.now + timedelta(hours=7)).isoformat(),
        }

    def test_fresh_runtime_can_start_without_exposing_token(self):
        with patch("sys.stdout", new_callable=io.StringIO) as captured:
            value = module.validate_runtime(self.base, "P259-L03", "tts", 7200, self.now)
            print("PREFLIGHT_OK", value // 60)
        self.assertEqual(value, 7 * 3600)
        self.assertNotIn("PRIVATE_TOKEN", captured.getvalue())

    def test_expired_rerun_is_blocked_before_gpu(self):
        value = {**self.base, "expires_at": (self.now - timedelta(seconds=1)).isoformat()}
        with self.assertRaisesRegex(module.PreflightError, "runtime_too_old"):
            module.validate_runtime(value, "P259-L03", "tts", 7200, self.now)

    def test_insufficient_time_for_four_lesson_tts(self):
        value = {**self.base, "expires_at": (self.now + timedelta(hours=3)).isoformat()}
        with self.assertRaisesRegex(module.PreflightError, "runtime_too_old"):
            module.validate_runtime(value, "P259-L03", "tts",
                                    module.required_remaining_seconds("tts", "central4"), self.now)

    def test_mismatched_task_or_stage_is_blocked(self):
        for task, stage in [("P259-L04", "tts"), ("P259-L03", "multi")]:
            with self.assertRaisesRegex(module.PreflightError, "runtime_task_or_stage_mismatch"):
                module.validate_runtime(self.base, task, stage, 10, self.now)

    def test_missing_oauth_cannot_start(self):
        value = {**self.base, "google_access_token": ""}
        with self.assertRaisesRegex(module.PreflightError, "runtime_google_oauth_unavailable"):
            module.validate_runtime(value, "P259-L03", "tts", 10, self.now)

    def test_rejects_untrusted_hosts_or_insecure_urls(self):
        for url in [
            "http://script.google.com/macros/s/abc/exec",
            "https://evil.example/macros/s/abc/exec",
            "https://script.google.com.evil.example/macros/s/abc/exec",
            "https://script.google.com@evil.example/macros/s/abc/exec",
        ]:
            with self.assertRaises(module.PreflightError):
                module.validate_bridge_url(url)
        module.validate_bridge_url("https://script.google.com/macros/s/abc/exec")

    def test_duration_estimates_preserve_legacy_long_work(self):
        self.assertEqual(module.required_remaining_seconds("tts", "central4"), 5 * 3600)
        self.assertEqual(module.required_remaining_seconds("batch"), 4 * 3600)
        self.assertEqual(module.required_remaining_seconds("zh"), 2 * 3600)


if __name__ == "__main__":
    unittest.main(verbosity=2)
