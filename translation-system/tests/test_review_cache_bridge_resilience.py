"""Ensure a failed optional GitHub review-cache bridge does not invalidate completed polish."""
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from github_review_cache import publish_review_cache


class ReviewCacheBridgeTest(unittest.TestCase):
    def test_http_404_is_nonfatal_drive_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            payload = Path(d) / "zh.json"
            payload.write_text(json.dumps({
                "version": 5,
                "segments": [{"id": 0, "text": "正確校稿"}],
            }, ensure_ascii=False), encoding="utf-8")
            err = urllib.error.HTTPError(
                "https://script.google.com/macros/s/xxx/exec",
                404, "Not Found", {}, io.BytesIO(b"no such endpoint")
            )
            with patch.dict(os.environ, {
                "SOULKEY_BRIDGE_URL": "https://script.google.com/macros/s/xxx/exec",
                "SOULKEY_RUNTIME_NONCE": "test-nonce",
            }):
                with patch("urllib.request.urlopen", side_effect=err):
                    result = publish_review_cache("P257-L01", payload)
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], "review_cache_bridge_unavailable")
            self.assertIn("HTTP 404", result["message"])
            self.assertEqual(json.loads(payload.read_text(encoding="utf-8"))["segments"][0]["text"], "正確校稿")

    def test_unauthorized_transport_failure_does_not_raise(self):
        with tempfile.TemporaryDirectory() as d:
            payload = Path(d) / "zh.json"
            payload.write_text('{"segments":[{"text":"稿"}]}', encoding="utf-8")
            with patch.dict(os.environ, {
                "SOULKEY_BRIDGE_URL": "https://script.google.com/macros/s/xxx/exec",
                "SOULKEY_RUNTIME_NONCE": "test-nonce",
            }):
                with patch("urllib.request.urlopen",
                           side_effect=urllib.error.URLError("temporary unavailable")):
                    result = publish_review_cache("P257-L03", payload)
            self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
