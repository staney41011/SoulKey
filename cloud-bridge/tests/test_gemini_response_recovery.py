"""Never silently pass incomplete Gemini content or lose source segment IDs."""
import importlib.util
import pathlib
import sys
import unittest
from unittest.mock import patch

ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("soulkey_translation_worker",ROOT/"translation_worker.py")
worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
spec2=importlib.util.spec_from_file_location("gemini_quality",ROOT/"gemini_quality.py")
qa=importlib.util.module_from_spec(spec2);spec2.loader.exec_module(qa)

class GeminiRecoveryTest(unittest.TestCase):
    def test_missing_parts_is_explicit_recoverable_error(self):
        with self.assertRaisesRegex(worker.GeminiResponseError,"gemini_missing_parts:MAX_TOKENS"):
            worker._decode_gemini_response({"candidates":[{"finishReason":"MAX_TOKENS","content":{}}]})

    def test_blocked_content_never_passes_or_bisects(self):
        with self.assertRaisesRegex(RuntimeError,"Gemini content blocked"):
            worker._decode_gemini_response({"candidates":[{"finishReason":"SAFETY"}]})

    def test_invalid_json_is_recoverable(self):
        with self.assertRaises(worker.GeminiResponseError):
            worker._decode_gemini_response({"candidates":[{"finishReason":"STOP",
              "content":{"parts":[{"text":'{"segments":['}]}}]})

    def test_good_response_parses(self):
        self.assertEqual(worker._decode_gemini_response(
            {"candidates":[{"finishReason":"STOP","content":{"parts":[{"text":'{"segments":[]}'}]}}]}),
            {"segments":[]})

    def test_translation_split_keeps_all_ids(self):
        segments=[{"id":i,"text":"Hello "+str(i)} for i in range(8)]
        counts=[]
        def gemini_mock(prompt,schema=None):
            import json
            data=json.loads(prompt.split("\\n\\n")[-1])["segments"]
            counts.append(len(data))
            if len(data)>2:raise worker.GeminiResponseError("gemini_missing_parts:MAX_TOKENS")
            return {"segments":[{"id":x["id"],"text":"Translated "+str(x["id"])} for x in data]}
        with patch.object(worker,"GEMINI","test-key"),patch.object(worker,"gemini",side_effect=gemini_mock):
            result=worker.translate("es",segments)
        self.assertEqual([x["id"] for x in result],list(range(8)))
        self.assertEqual([x["text"] for x in result],["Translated "+str(i) for i in range(8)])
        self.assertEqual(counts,[8,4,2,2,4,2,2])

    def test_qa_split_checks_every_segment(self):
        src=[{"id":i,"text":"Welcome "+str(i)} for i in range(8)]
        translated=[{"id":i,"text":"Bienvenido "+str(i)} for i in range(8)]
        checked=[]
        def gemini_mock(prompt,schema=None):
            import json
            rows=json.loads(prompt.split("DATA:\\n",1)[1])
            checked.extend(x["segment_id"] for x in rows)
            if len(rows)>2:raise worker.GeminiResponseError("gemini_missing_parts:MAX_TOKENS")
            return {"failures":[]}
        result,stats=qa.audit_and_repair(src,translated,"es",gemini_mock)
        self.assertEqual(result,translated)
        self.assertEqual(sorted(set(checked)),list(range(8)))
        self.assertEqual(stats["unresolved"],0)

    def test_single_blocked_segment_fails_closed(self):
        src=[{"id":0,"text":"Welcome"}]
        translated=[{"id":0,"text":"Bienvenido"}]
        def fail(*_):
            raise worker.GeminiResponseError("gemini_missing_parts")
        with self.assertRaises(worker.GeminiResponseError):
            qa.audit_and_repair(src,translated,"es",fail)

if __name__=="__main__":unittest.main()
