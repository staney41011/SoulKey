"""Offline regression tests for YouTube-to-Chinese Gemini capacity fallback."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gemini_engine import GeminiAPIError
from gemini_source_runner import (
    transient_video_error,
    video_model_candidates,
    transcribe_youtube_with_model_fallback,
    save_outputs,
)


class FakeVideoClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.models = []

    def structured_video(self, url, prompt, schema, *, model, thinking_level):
        self.models.append(model)
        outcome = self.responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome, None


class VideoCapacityFallbackTests(unittest.TestCase):
    def test_unique_candidates(self):
        self.assertEqual(
            video_model_candidates(
                "gemini-3.8-flash", "gemini-3.8-flash,gemini-3.1-flash-lite"
            ),
            ["gemini-3.8-flash", "gemini-3.1-flash-lite"],
        )

    @patch("time.sleep")
    def test_503_uses_second_video_capable_model(self, sleeper):
        response = {"segments": [
            {"id": 0, "start": 0, "end": 8, "text": "學習修養的重要"}
        ]}
        client = FakeVideoClient([
            GeminiAPIError('HTTP 503: high demand'),
            response,
        ])
        result, _, model = transcribe_youtube_with_model_fallback(
            client, "https://youtu.be/example", "prompt", {},
            primary="gemini-3.8-flash",
            fallback_models="gemini-3.1-flash-lite",
        )
        self.assertEqual(result, response)
        self.assertEqual(model, "gemini-3.1-flash-lite")
        self.assertEqual(
            client.models, ["gemini-3.8-flash", "gemini-3.1-flash-lite"]
        )
        sleeper.assert_called_once_with(15)

    @patch("time.sleep")
    def test_auth_errors_do_not_switch_models(self, sleeper):
        client = FakeVideoClient([GeminiAPIError("HTTP 401: invalid API key")])
        with self.assertRaisesRegex(GeminiAPIError, "401"):
            transcribe_youtube_with_model_fallback(
                client, "https://youtu.be/example", "prompt", {},
                fallback_models="gemini-3.1-flash-lite",
            )
        self.assertEqual(len(client.models), 1)
        sleeper.assert_not_called()

    @patch("time.sleep")
    def test_all_models_overloaded_fails_explicitly(self, sleeper):
        client = FakeVideoClient([
            GeminiAPIError("HTTP 503: busy"),
            GeminiAPIError("HTTP 429: quota"),
        ])
        with self.assertRaisesRegex(GeminiAPIError, "429"):
            transcribe_youtube_with_model_fallback(
                client, "https://youtu.be/example", "prompt", {},
                fallback_models="gemini-3.1-flash-lite",
            )
        self.assertEqual(len(client.models), 2)

    def test_written_transcript_records_real_model(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            output = save_outputs(
                Path(directory), "P257-L01", "https://youtu.be/example",
                [{"id": 0, "start": 0, "end": 5, "text": "中文"}],
                model="gemini-3.1-flash-lite",
            )
            data = json.loads(output["json"].read_text(encoding="utf-8"))
            self.assertEqual(data["model"], "gemini-3.1-flash-lite")


if __name__ == "__main__":
    unittest.main()
