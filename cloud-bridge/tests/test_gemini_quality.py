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
  def api(prompt,schema=None):
   if "FAILED:" in prompt:return {"repairs":[{"id":1,"text":"Se unieron 24 personas."}]}
   return {"failures":[]}
  with self.assertRaisesRegex(ValueError,"unresolved_translation_qa"):
   m.audit_and_repair(source,rows,"es",api,max_rounds=1)
 def test_portuguese_decimal_mismatch_is_never_approved(self):
  self.assertEqual(m.translated_number_issues("2.5 people","12,5 pessoas","pt"),["missing_number:2.5"])
  self.assertEqual(m.translated_number_issues("2.5 people","2,5 pessoas","pt"),[])
  self.assertEqual(m.translated_number_issues("2.5 people","3 pessoas","pt"),["missing_number:2.5"])

 def test_italian_and_portuguese_thousands_grouping(self):
  self.assertEqual(m.translated_number_issues("2500 people","2.500 persone","it"),[])
  self.assertEqual(m.translated_number_issues("2500 people","250 persone","it"),["missing_number:2500"])
  self.assertEqual(m.translated_number_issues("1,200 people","1.200 pessoas","pt"),[])

 def test_wrong_years_are_detected_in_both_languages(self):
  for lang in ["it","pt"]:
   self.assertEqual(m.translated_number_issues("This happened in 2026.","Questo è successo nel 2025.",lang),["missing_number:2026"])
   self.assertEqual(m.translated_number_issues("This happened in 2026.","Questo è successo nel 2026.",lang),[])

if __name__=="__main__":unittest.main()
