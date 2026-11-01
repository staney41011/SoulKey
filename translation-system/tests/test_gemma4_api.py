"""Offline regression for SoulKey Gemma 4 API migration; no API key needed."""
import json
import os
import unittest
from unittest.mock import patch

from gemini_engine import DEFAULT_TEXT_MODEL, GeminiAPIError, GeminiClient


SCHEMA = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "text": {"type": "string"},
                },
                "required": ["id", "text"],
            },
        },
    },
    "required": ["segments"],
}


def gemma_response(obj):
    return {
        "candidates": [{
            "content": {"role": "model", "parts": [
                {"text": json.dumps(obj, ensure_ascii=False)}
            ]},
            "finishReason": "STOP",
        }],
        "usageMetadata": {
            "promptTokenCount": 50,
            "candidatesTokenCount": 30,
            "thoughtsTokenCount": 2,
            "totalTokenCount": 82,
        },
    }


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append((url, headers, payload))
        return self.responses.pop(0)


class Gemma4ApiTest(unittest.TestCase):
    def make_client(self, transport):
        return GeminiClient(
            api_key="fake-test-token",
            transport=transport,
            sleeper=lambda _: None,
            max_attempts=2,
        )

    def test_gemma_is_default_and_uses_generate_content(self):
        self.assertEqual(DEFAULT_TEXT_MODEL, "gemma-4-26b-a4b-it")
        expected = {"segments": [{"id": 7, "text": "สวัสดี"}]}
        mock = FakeTransport([(200, json.dumps(gemma_response(expected)).encode())])
        result, usage = self.make_client(mock).structured(
            "Translate", SCHEMA,
            system_instruction="Preserve exact segment ids.",
        )
        self.assertEqual(result, expected)
        self.assertEqual(usage.total_tokens, 82)
        self.assertEqual(usage.input_tokens, 50)
        url, headers, payload = mock.calls[0]
        self.assertTrue(url.endswith(
            "/models/gemma-4-26b-a4b-it:generateContent"
        ))
        self.assertNotIn("/interactions", url)
        self.assertEqual(headers["x-goog-api-key"], "fake-test-token")
        self.assertEqual(payload["generationConfig"]["responseSchema"], SCHEMA)
        self.assertEqual(
            payload["generationConfig"]["thinkingConfig"]["thinkingLevel"],
            "minimal",
        )
        self.assertEqual(
            payload["systemInstruction"]["parts"][0]["text"],
            "Preserve exact segment ids.",
        )

    def test_retry_rate_limit_does_not_skip_work(self):
        success = gemma_response({"segments": []})
        mock = FakeTransport([
            (429, b'{"error":"quota"}'),
            (200, json.dumps(success).encode()),
        ])
        self.assertEqual(
            self.make_client(mock).structured("Translate", SCHEMA)[0],
            {"segments": []},
        )
        self.assertEqual(len(mock.calls), 2)

    def test_schema_400_falls_back_to_json_mode(self):
        success = gemma_response({"segments": []})
        mock = FakeTransport([
            (400, b'{"error":{"message":"responseSchema unsupported"}}'),
            (200, json.dumps(success).encode()),
        ])
        result, _ = self.make_client(mock).structured("Translate", SCHEMA)
        self.assertEqual(result["segments"], [])
        self.assertNotIn(
            "responseSchema", mock.calls[1][2]["generationConfig"]
        )
        self.assertIn(
            "Return ONLY", mock.calls[1][2]["contents"][0]["parts"][0]["text"]
        )

    def test_invalid_json_is_not_published(self):
        mock = FakeTransport([(
            200,
            json.dumps({"candidates": [{
                "content": {"parts": [{"text": "not JSON"}]}
            }]}).encode(),
        )])
        with self.assertRaises(GeminiAPIError):
            self.make_client(mock).structured("Translate", SCHEMA)

    def test_no_secret_does_not_make_network_request(self):
        mock = FakeTransport([])
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            with self.assertRaisesRegex(GeminiAPIError, "GEMINI_API_KEY"):
                GeminiClient(api_key="", transport=mock).structured(
                    "Translate", SCHEMA
                )
        self.assertEqual(mock.calls, [])


if __name__ == "__main__":
    unittest.main()
