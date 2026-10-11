"""Test true numeric magnitudes, not matching ASCII glyphs only."""
import ast
import pathlib
import re
import unicodedata
import unittest

path=pathlib.Path(__file__).resolve().parents[1]/"gemini_multi_production_runner.py"
source=path.read_text(encoding="utf-8")
tree=ast.parse(source)
targets={"_ENGLISH_SCALED_NUMBER","_CJK_SCALED_NUMBER",
         "_ENGLISH_UNITS","_CJK_UNITS"}
functions={"normalize_unicode_digits","translated_number_issues","local_failures"}
subset=[]
for node in tree.body:
    if isinstance(node,ast.Assign) and any(
       isinstance(target,ast.Name) and target.id in targets
       for target in node.targets):
        subset.append(node)
    if isinstance(node,ast.FunctionDef) and node.name in functions:
        subset.append(node)
context={"re":re,"unicodedata":unicodedata,
         "local_language_issue":lambda text,src,lang:""}
exec(compile(ast.Module(body=subset,type_ignores=[]),str(path),"exec"),context)
numeric=context["translated_number_issues"]
failures=context["local_failures"]

class LocalizedNumberQATests(unittest.TestCase):
    source="If he refused 2.5 billion, the family later obtained 8 billion."

    def test_correct_east_asian_conversions(self):
        self.assertEqual(numeric(self.source,"25億を拒んで、その後80億を得た。","ja"),[])
        self.assertEqual(numeric(self.source,"25억을 거절하고 나중에 80억을 받았다.","ko"),[])
        batch=[{"id":386,"text":self.source}]
        rows=[{"segment_id":386,"ja":"当時は25億で、後に80億を受け取った。",
               "ko":"당시 25억, 이후 80억을 받았다."}]
        self.assertEqual(failures(batch,rows,["ja","ko"]),[])

    def test_wrong_magnitude_is_not_silently_accepted(self):
        self.assertEqual(
            numeric(self.source,"2.5億を拒んで、その後80億を得た。","ja"),
            ["incorrect_number_scale:2.5 billion"])
        self.assertEqual(
            numeric(self.source,"2.5억을 거절하고 나중에 80억을 받았다.","ko"),
            ["incorrect_number_scale:2.5 billion"])

    def test_missing_scaled_quantity_and_unscaled_number(self):
        self.assertEqual(
            numeric(self.source,"ただ80億の事実だけを述べた。","ja"),
            ["incorrect_number_scale:2.5 billion"])
        self.assertEqual(numeric("He saw 2.5 cases.",
              "彼は2.5例を見た。","ja"),[])
        self.assertEqual(numeric("He saw 2.5 cases.",
              "彼は3例を見た。","ja"),["missing_number:2.5"])

    def test_unchanged_latin_number_check_for_other_languages(self):
        self.assertEqual(numeric(self.source,"2.5 mil millones y 8 mil millones.",
                                 "es"),[])
        self.assertEqual(numeric(self.source,"otras cifras 8","es"),
                         ["missing_number:2.5"])

    def test_kaggle_lightweight_runtime_provides_source_verification_imports(self):
        text=(path.parent/"requirements-gemini.txt").read_text()
        self.assertIn("yt-dlp[default]",text)
        self.assertIn("youtube-transcript-api",text)
        src=(path.parent/"web_job_worker.py").read_text(encoding="utf-8")
        self.assertIn('from youtube_io import download_audio',src)

if __name__=="__main__":
    unittest.main()
