"""Source-bound QA unit checks for the SoulKey translation worker."""
import importlib.util, pathlib, unittest
p=pathlib.Path(__file__).resolve().parents[1]/"gemini_quality.py"
spec=importlib.util.spec_from_file_location("gemini_quality",p)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
class TestQuality(unittest.TestCase):
 def test_clean(self):
  source=[{"id":1,"text":"Welcome to the lecture."}]
  rows=[{"id":1,"text":"Bienvenidos a la conferencia."}]
  output,stats=m.audit_and_repair(source,rows,"es",lambda _,schema=None:{"failures":[]})
  self.assertEqual(output,rows)
  self.assertEqual(stats["repairs"],0)
 def test_number_repair(self):
  source=[{"id":1,"text":"42 people joined."}]
  rows=[{"id":1,"text":"Se unieron 24 personas."}]
  def api(prompt,schema=None):
   if "FAILED:" in prompt:return {"repairs":[{"id":1,"text":"Se unieron 42 personas."}]}
   return {"failures":[]}
  output,stats=m.audit_and_repair(source,rows,"es",api)
  self.assertEqual(output[0]["text"],"Se unieron 42 personas.")
  self.assertEqual(stats["repairs"],1)
 def test_no_fake_success(self):
  source=[{"id":1,"text":"42 people joined."}]
  rows=[{"id":1,"text":"Se unieron 24 personas."}]
  def api(prompt):
   if "FAILED:" in prompt:return {"repairs":[{"id":1,"text":"Se unieron 24 personas."}]}
   return {"failures":[]}
  with self.assertRaisesRegex(ValueError,"unresolved_translation_qa"):
   m.audit_and_repair(source,rows,"es",api,max_rounds=1)
if __name__=="__main__":unittest.main()
