"""Regression tests: no cross-lesson, incomplete or unreviewed TTS source."""
import unittest,importlib.util,pathlib,json,hashlib
P=pathlib.Path(__file__).resolve().parents[1]/"central_tts_source.py"
spec=importlib.util.spec_from_file_location("central_tts_source",P)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def fixture():
 doc={"task_id":"P259-L04","kind":"en","segments":[
   {"id":0,"start":0,"end":31,"text":"Welcome"},
   {"id":1,"start":31,"end":58,"text":"Be kind"}]}
 payload=json.dumps(doc,ensure_ascii=False,separators=(",",":"))
 hash=hashlib.sha256(payload.encode()).hexdigest()
 return ([["P259-L04",hash,"2","now"]],
         [["P259-L04",hash,"0","1",payload,"now",hash]],hash)
class SourceTests(unittest.TestCase):
 def test_valid_final_and_language(self):
  idx,parts,sha=fixture()
  final=m.verified_english_final("P259-L04",idx,parts)
  output=[["P259-L04",sha,"th","0","สวัสดี","job-1"],
          ["P259-L04",sha,"th","1","เมตตา","job-1"]]
  qa=[["job-1","P259-L04",sha,"th","gemini","3","0","passed","now"]]
  matched=m.verified_translation("P259-L04","th",final,output,qa)
  self.assertEqual([x["id"] for x in matched["segments"]],[0,1])
  self.assertEqual(matched["job_id"],"job-1")
  self.assertEqual(m.verified_translation("P259-L04","en",final,[],[])["job_id"],"human-final")
 def test_duplicate_missing_or_unapproved_blocked(self):
  idx,parts,sha=fixture()
  final=m.verified_english_final("P259-L04",idx,parts)
  data=[["P259-L04",sha,"th","0","สวัสดี","job-1"]]
  receipt=[["job-1","P259-L04",sha,"th","gemini","1","0","passed"]]
  with self.assertRaises(m.SourceNotReady):
   m.verified_translation("P259-L04","th",final,data,receipt)
  data.append(data[0])
  with self.assertRaises(m.SourceNotReady):
   m.verified_translation("P259-L04","th",final,data,receipt)
  self.assertRaises(m.SourceNotReady,m.verified_translation,"P259-L04","th",final,data,[])
 def test_wrong_task_revision_invalid_hash_blocked(self):
  idx,parts,sha=fixture()
  with self.assertRaises(m.SourceNotReady):
   m.verified_english_final("P259-L03",idx,parts)
  parts[0][4]=parts[0][4]+" "
  with self.assertRaisesRegex(m.SourceNotReady,"hash_mismatch"):
   m.verified_english_final("P259-L04",idx,parts)
 def test_old_revision_qa_is_not_reused(self):
  idx,parts,sha=fixture();final=m.verified_english_final("P259-L04",idx,parts)
  data=[["P259-L04",sha,"es","0","Hola","job"] ,
        ["P259-L04",sha,"es","1","Amable","job"]]
  old=[["job","P259-L04","a"*64,"es","gemini",1,0,"passed"]]
  with self.assertRaises(m.SourceNotReady):
   m.verified_translation("P259-L04","es",final,data,old)
if __name__=="__main__":unittest.main()
