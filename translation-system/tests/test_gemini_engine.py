import base64
import json
import unittest

from gemini_engine import (
    GeminiAPIError,
    GeminiClient,
    QA_SCHEMA,
    local_language_issue,
    normalize_segments,
    relevant_glossary,
    semantic_polish_zh,
    translate_and_qa,
    validate_returned_ids,
)


def response_text(payload):
    return {
        "status": "completed",
        "steps": [{
            "type": "model_output",
            "content": [{
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=False),
            }],
        }],
        "usage": {
            "total_input_tokens": 10,
            "total_output_tokens": 5,
            "total_thought_tokens": 2,
            "total_tokens": 17,
        },
    }


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append(payload)
        item = self.responses.pop(0)
        if isinstance(item, tuple):
            return item
        return 200, json.dumps(item).encode()


class GeminiEngineTest(unittest.TestCase):
    def test_structured_output_and_usage(self):
        transport = FakeTransport([
            response_text({"items": [{
                "id": 1,
                "pass": True,
                "meaning_preserved": True,
                "missing_content": False,
                "added_content": False,
                "wrong_language": False,
                "glossary_violation": False,
                "tts_ready": True,
                "issues": [],
                "repair_instruction": "",
            }]})
        ])
        client = GeminiClient(
            api_key="test",
            transport=transport,
            sleeper=lambda _: None,
        )
        parsed, usage = client.structured("x", QA_SCHEMA)
        self.assertTrue(parsed["items"][0]["pass"])
        self.assertEqual(usage.total_tokens, 17)
        self.assertEqual(
            transport.calls[0]["response_format"]["mime_type"],
            "application/json",
        )

    def test_retry_429(self):
        transport = FakeTransport([
            (429, b'{"error":"rate"}'),
            response_text({"items": []}),
        ])
        client = GeminiClient(
            api_key="test",
            transport=transport,
            sleeper=lambda _: None,
        )
        parsed, _ = client.structured("x", QA_SCHEMA)
        self.assertEqual(parsed["items"], [])
        self.assertEqual(len(transport.calls), 2)

    def test_tts_requires_wav(self):
        wav = b"RIFF" + b"x" * 20
        transport = FakeTransport([{
            "status": "completed",
            "steps": [{
                "type": "model_output",
                "content": [{
                    "type": "audio",
                    "mime_type": "audio/wav",
                    "data": base64.b64encode(wav).decode(),
                }],
            }],
        }])
        client = GeminiClient(api_key="test", transport=transport)
        audio, mime, _ = client.tts("hello")
        self.assertEqual(audio, wav)
        self.assertEqual(mime, "audio/wav")

    def test_missing_key_fails_closed(self):
        client = GeminiClient(api_key="", transport=FakeTransport([]))
        with self.assertRaises(GeminiAPIError):
            client.structured("x", QA_SCHEMA)

    def test_segment_ids(self):
        src = [{"id": 1, "text": "a"}, {"id": 2, "text": "b"}]
        validate_returned_ids(
            src,
            [{"id": 2, "text": "B"}, {"id": 1, "text": "A"}],
            "test",
        )
        with self.assertRaises(GeminiAPIError):
            validate_returned_ids(src, [{"id": 1}], "test")

    def test_script_guard(self):
        self.assertEqual(
            local_language_issue(
                "This is still English and was not translated at all.",
                "This is still English and was not translated at all.",
                "th",
            ),
            "source_text_copied",
        )
        self.assertEqual(
            local_language_issue(
                "นี่คือข้อความภาษาไทยที่เขียนอย่างเป็นธรรมชาติ",
                "This is a Thai sentence.",
                "th",
            ),
            "",
        )

    def test_glossary_retrieval(self):
        glossary = [
            {"zh": "道場", "en": "Tao community", "locked": True},
            {"zh": "三寶", "en": "Three Treasures", "locked": True},
        ]
        found = relevant_glossary(
            glossary,
            "The Three Treasures are explained here.",
            "th",
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["zh"], "三寶")

    def test_translate_and_qa_passes_clean_thai(self):
        transport = FakeTransport([
            response_text({"segments": [{
                "id": 1,
                "text": "เราควรรักษาคุณค่าของชีวิตและช่วยเหลือผู้อื่น",
                "notes": "",
            }]}),
            response_text({"items": [{
                "id": 1,
                "pass": True,
                "meaning_preserved": True,
                "missing_content": False,
                "added_content": False,
                "wrong_language": False,
                "glossary_violation": False,
                "tts_ready": True,
                "issues": [],
                "repair_instruction": "",
            }]}),
        ])
        client = GeminiClient(api_key="test", transport=transport)
        result = translate_and_qa(
            client,
            {"segments": [{
                "id": 1,
                "start": 0,
                "end": 4,
                "text": "We should value life and help others.",
            }]},
            "th",
            glossary_rows=[],
            chunk_size=12,
        )
        self.assertEqual(result["qa_pass_count"], 1)
        self.assertEqual(result["qa_fail_count"], 0)
        self.assertEqual(result["segments"][0]["repair_attempts"], 0)

    def test_translate_and_qa_repairs_wrong_language(self):
        qa_fail = {
            "id": 1,
            "pass": False,
            "meaning_preserved": True,
            "missing_content": False,
            "added_content": False,
            "wrong_language": True,
            "glossary_violation": False,
            "tts_ready": False,
            "issues": ["translation is still English"],
            "repair_instruction": "translate fully into Thai",
        }
        qa_pass = {
            "id": 1,
            "pass": True,
            "meaning_preserved": True,
            "missing_content": False,
            "added_content": False,
            "wrong_language": False,
            "glossary_violation": False,
            "tts_ready": True,
            "issues": [],
            "repair_instruction": "",
        }
        transport = FakeTransport([
            response_text({"segments": [{
                "id": 1,
                "text": "This sentence is still in English and must be repaired.",
                "notes": "",
            }]}),
            response_text({"items": [qa_fail]}),
            response_text({"segments": [{
                "id": 1,
                "text": "ประโยคนี้ได้รับการแปลเป็นภาษาไทยอย่างถูกต้องแล้ว",
                "notes": "",
            }]}),
            response_text({"items": [qa_pass]}),
        ])
        client = GeminiClient(api_key="test", transport=transport)
        result = translate_and_qa(
            client,
            {"segments": [{
                "id": 1,
                "start": 0,
                "end": 4,
                "text": "This sentence is still in English and must be repaired.",
            }]},
            "th",
            glossary_rows=[],
            repair_attempts=2,
        )
        self.assertEqual(result["qa_fail_count"], 0)
        self.assertEqual(result["segments"][0]["repair_attempts"], 1)
        self.assertIn("ภาษาไทย", result["segments"][0]["text"])

    def test_semantic_polish_locked_term_guard(self):
        transport = FakeTransport([
            response_text({"segments": [{
                "id": 7,
                "text": "尤其在白羊期裡面更要把握機會。",
                "changed": True,
                "notes": "spelling normalized",
                "term_candidates": [],
            }]})
        ])
        client = GeminiClient(api_key="test", transport=transport)
        glossary_rows = [[
            "白陽期",
            "宗教術語",
            "固定用語",
            "White Yang Era",
            "",
            "",
            "",
            "",
            "TRUE",
            "",
        ]]
        result = semantic_polish_zh(
            client,
            {"segments": [{
                "id": 7,
                "start": 0,
                "end": 5,
                "text": "尤其在白陽期裡面更要把握機會。",
            }]},
            glossary_rows=glossary_rows,
        )
        row = result["segments"][0]
        self.assertEqual(row["text"], "尤其在白陽期裡面更要把握機會。")
        self.assertFalse(row["changed"])
        self.assertIn("locked_term_guard:白陽期", row["notes"])

    def test_normalize_segments(self):
        payload = {"segments": [
            {"id": 3, "start": 1.2, "end": 2.4, "text": " hello "},
        ]}
        rows = normalize_segments(payload)
        self.assertEqual(rows[0]["id"], 3)
        self.assertEqual(rows[0]["text"], "hello")


if __name__ == "__main__":
    unittest.main()
