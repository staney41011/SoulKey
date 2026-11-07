import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sheets_quality_core import (
 audit_segment,selected_for_review,parse_model_result,QA_SCHEMA,
 summarize_language,gate_ready,check_repair,normalized_numbers,stable_sha
)
from sheets_quality_core import text_sha

def rows(n=10):
    source=[];draft=[]
    for i in range(n):
        t=f"The teacher visited {i+20} vegetarian restaurants."
        source.append({"id":i,"text":t,"start":float(i*5),"end":float(i*5+4)})
        draft.append({"id":i,"text":f"El maestro visitó {i+20} restaurantes vegetarianos.",
                      "source_hash":text_sha(t),"start":float(i*5),"end":float(i*5+4)})
    return source,draft

class QualityTests(unittest.TestCase):
    def test_accurate_numbers_and_scripts(self):
        s,t=rows()
        result=audit_segment(s[0],t[0],"es",[])
        self.assertEqual(result["hard_errors"],[])
        self.assertEqual(result["source_numbers"],["20"])
        self.assertEqual(result["target_numbers"],["20"])
        self.assertNotIn("numeric_semantics_require_review",result["risk_flags"])
    def test_mismatch_is_flagged_but_not_silently_rewritten(self):
        s,t=rows()
        t[0]["text"]="El maestro visitó 60 restaurantes vegetarianos."
        audit=audit_segment(s[0],t[0],"es",[])
        self.assertIn("numeric_semantics_require_review",audit["risk_flags"])
    def test_source_tamper_fails_closed(self):
        s,t=rows()
        t[0]["source_hash"]="bad"
        self.assertIn("english_revision_hash_mismatch",
                     audit_segment(s[0],t[0],"es",[])["hard_errors"])
        t[0]["source_hash"]=text_sha(s[0]["text"])
        t[0]["start"]=99
        self.assertIn("timeline_changed",audit_segment(s[0],t[0],"es",[])["hard_errors"])
    def test_glossary_locked_risk(self):
        s,t=rows()
        s[0]["text"]="We cultivate Dao at the temple."
        t[0]["source_hash"]=text_sha(s[0]["text"])
        a=audit_segment(s[0],t[0],"es",
              [{"en":"Dao","es":"Camino","locked":True,"description":"Spiritual path"}])
        self.assertTrue(any("locked_glossary" in x for x in a["risk_flags"]))
        self.assertFalse(check_repair(t[0],"sin el término designado","es",a))
    def test_model_rows_must_be_exact_and_no_autopublish_ambiguity(self):
        expected={1,2}
        good={"items":[{"id":1,"grade":"A","reason":"","corrected_text":""},
                       {"id":2,"grade":"C","reason":"spiritual ambiguity","corrected_text":""}]}
        self.assertEqual(parse_model_result(good,expected)[2]["grade"],"C")
        with self.assertRaises(ValueError):
            parse_model_result({"items":[good["items"][0]]},expected)
        with self.assertRaises(ValueError):
            parse_model_result({"items":[{"id":1,"grade":"B",
                                          "reason":"wrong","corrected_text":""},
                                         good["items"][1]]},expected)
    def test_deterministic_sample_and_blocking(self):
        s,t=rows(16)
        audits=[audit_segment(x,y,"es",[]) for x,y in zip(s,t)]
        choices=selected_for_review(audits,"P260-L01","es")
        self.assertEqual(choices,selected_for_review(audits,"P260-L01","es"))
        self.assertGreaterEqual(len(choices),3)
        for a in audits:
            a["selected_for_ai"]=a["id"] in choices
        partial=summarize_language(audits,{})
        self.assertEqual(partial["state"],"needs_review")
        decisions={str(i):{"grade":"A"} for i in choices}
        complete=summarize_language(audits,decisions)
        self.assertEqual(complete["state"],"approved_risk_based")
        self.assertLess(complete["model_reviewed_pass"],16)
        self.assertFalse(gate_ready({"es":complete},["es","th"])["ready"])
    def test_unicode_numeric_handling(self):
        self.assertEqual(normalized_numbers("५०"),["50"])
        self.assertEqual(normalized_numbers("50"),["50"])

if __name__=="__main__":
    unittest.main()
