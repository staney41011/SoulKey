import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from kaggle_checkpoint_summary import summarize

class SummaryTests(unittest.TestCase):
    def log(self,text):return json.dumps([{"stream_name":"stdout","time":32.5,"data":text}])
    def test_actual_progress_and_review_are_separate(self):
        result=summarize(self.log("GEMMA4_SERVER_RUNTIME_VERIFIED\nGEMMA4_QAT_12B_READY\nGEMMA4_P259_PENDING_LANGUAGES 23\nGEMMA4_P259_DELIVERED P259-L01 ne 59\nGEMMA4_P259_REVIEW_ONLY P259-L01 km ValueError private detail\nGEMMA4_P259_PROGRESS 1 1\n"))
        self.assertTrue(result["model_ready"]);self.assertTrue(result["native_runtime_verified"])
        self.assertEqual(result["progress"],{"passed":1,"review":1});self.assertEqual(result["pending_at_start"],23)
        self.assertEqual(result["delivered"],[{"task":"P259-L01","lang":"ne","segments":59}])
        self.assertEqual(result["review"][0]["error_class"],"ValueError")
    def test_no_lecture_text_or_credentials_can_be_published(self):
        private="DO_NOT_PUBLISH_LECTURE_OR_SECRET"
        result=summarize(self.log("Traceback token="+private+"\nGEMMA4_P259_REVIEW_ONLY P259-L01 km ValueError "+private+"\nGEMMA4_QA_UNRESOLVED_REASONS km "+json.dumps({"12":["numbers_mismatch",private+" incorrect meaning"]})+"\n"))
        self.assertNotIn(private,json.dumps(result))
        self.assertEqual(result["qa_reasons"]["km"],{"segment_ids":[12],"categories":{"numbers":1,"meaning":1}})
    def test_budget_stop_does_not_mean_complete(self):
        result=summarize(self.log("GEMMA4_P259_TRANSLATION_TIME_BUDGET_REACHED; resume remaining languages next run\n"))
        self.assertTrue(result["translation_budget_reached"]);self.assertEqual(result["delivered"],[])
    def test_missing_or_malformed_logs_have_no_inferred_progress(self):
        for raw in ("", "[]", '{"message":"private error"}'):
            result=summarize(raw)
            self.assertFalse(result["model_ready"]);self.assertNotIn("progress",result)

if __name__=="__main__":unittest.main(verbosity=2)
