"""Multilingual manuscript preflight: punctuation-only translations are omitted."""
import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from translation_text_safety import has_spoken_content, filter_nonspoken_segments
from gemini_engine import local_language_issue

def load_pure_writer():
    """Run the production writer in isolation from Google credential imports."""
    module=ast.parse((ROOT/"gemini_multi_production_runner.py").read_text(encoding="utf-8"))
    functions=[n for n in module.body if isinstance(n,ast.FunctionDef) and n.name in
               {"write_language_set","format_srt_time"}]
    assert len(functions)==2,"Production exporter must be testable"
    namespace={
        "json":json,
        "LANGUAGE_NAMES":{"id":"Indonesian","ta":"Tamil","lo":"Lao"},
        "filter_nonspoken_segments":filter_nonspoken_segments,
    }
    exec(compile(ast.Module(body=functions,type_ignores=[]),str(ROOT/"gemini_multi_production_runner.py"),"exec"),namespace)
    return namespace["write_language_set"]

WRITE_LANGUAGE_SET=load_pure_writer()

class ManuscriptFilterTests(unittest.TestCase):
    def test_unicode_and_real_spoken_numbers_preserved(self):
        for value in ["Halo!","தமிழ்","ສະບາຍດີ","ภาษาไทย","ខ្មែរ","你好",
                      "123","２０２６","7.","A","ê"]:
            with self.subTest(value=value):
                self.assertTrue(has_spoken_content(value))
        for value in ["",None," ",".", "。", "．．．", "…", "！","？！",
                      "🇹🇼","—","\"'","\t\n","..."]:
            with self.subTest(value=value):
                self.assertFalse(has_spoken_content(value))

    def test_full_export_omits_punctuation_and_preserves_ids_times(self):
        source=[
            {"id":25,"start":109.5,"end":113.38,"text":"A real sentence."},
            {"id":26,"start":115.88,"end":128.46,"text":"."},
            {"id":28,"start":131.23,"end":175.77,"text":"Another sentence."},
            {"id":29,"start":176.0,"end":177.0,"text":"…"},
        ]
        for lang in ("id","ta","lo"):
            with self.subTest(language=lang), tempfile.TemporaryDirectory() as tmp:
                rows=[
                    {"segment_id":25,lang:"Actual translated words."},
                    {"segment_id":26,lang:"."},
                    {"segment_id":28,lang:{"id":"Ini kalimat.", "ta":"இது ஒரு வாக்கியம்.",
                                            "lo":"ນີ້ແມ່ນປະໂຫຍກ."}[lang]},
                    {"segment_id":29,lang:"…"},
                ]
                artifacts=WRITE_LANGUAGE_SET(
                    Path(tmp),lang,source,rows,"gemini-test",
                    source_sha256="approved-en-source-v1",
                )
                self.assertEqual(len(artifacts),3)
                data=json.loads((Path(tmp)/(lang+".json")).read_text(encoding="utf-8"))
                self.assertEqual([x["id"] for x in data["segments"]],[25,28])
                self.assertEqual([x["id"] for x in data["filtered_nonspoken_segments"]],[26,29])
                self.assertTrue(data["filtered_nonspoken_segments"][0]["source_review_recommended"])
                self.assertFalse(data["filtered_nonspoken_segments"][1]["source_review_recommended"])
                self.assertEqual(data["segments"][1]["start"],131.23)
                self.assertEqual(data["source_sha256"],"approved-en-source-v1")
                txt=(Path(tmp)/(lang+".txt")).read_text(encoding="utf-8")
                self.assertEqual(txt.count("\n"),2)
                self.assertNotIn("\n.\n",txt)
                srt=(Path(tmp)/(lang+".srt")).read_text(encoding="utf-8")
                self.assertIn("00:01:49,500 --> 00:01:53,380",srt)
                self.assertIn("00:02:11,230 --> 00:02:55,770",srt)
                self.assertNotIn("00:01:55,880",srt)
                self.assertEqual(len(srt.split("-->")),3)
                self.assertNotIn("115.88",srt)
                # Translation cache stays untouched; publishing has no destructive edits.
                self.assertEqual(source[1]["text"],".")
                self.assertEqual(rows[1][lang],".")

    def test_qa_flags_missing_speech_but_allows_source_punctuation(self):
        for lang in ("id","ta","lo","es","th"):
            with self.subTest(language=lang):
                self.assertEqual(local_language_issue(".","We teach kindness.",lang),
                                 "translation_has_no_spoken_content")
                self.assertEqual(local_language_issue(".",".",lang),"")
                self.assertEqual(local_language_issue("？！","A full sentence.",lang),
                                 "translation_has_no_spoken_content")
        self.assertEqual(local_language_issue("123","123","id"),"")

    def test_rejects_manuscript_with_no_real_speech(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError,"no pronounceable translated text"):
                WRITE_LANGUAGE_SET(
                    Path(tmp),"id",[{"id":3,"start":0,"end":1,"text":"."}],
                    [{"segment_id":3,"id":"."}],"test",
                )

if __name__=="__main__":
    unittest.main()
