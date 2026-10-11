"""Khmer (km) integration contract without cloud calls or GPU."""
import ast
import pathlib
import sys
import unittest
ROOT=pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"translation-system"))
from natural_tts_config import NATURAL_TTS_PROFILES, EDGE_LANGS, GPU_REQUIRED_LANGS
from drive_naming import formal_drive_name, output_label
from gemini_engine import local_language_issue, LANGUAGE_NAMES, parse_glossary_rows
from config import GLOSSARY_FULL_RANGE

def src(rel):
    return (ROOT/rel).read_text(encoding="utf-8")

class KhmerWorkflowTests(unittest.TestCase):
    def test_khmer_code_script_and_glossary(self):
        self.assertEqual(LANGUAGE_NAMES["km"],"Khmer")
        self.assertEqual(
            local_language_issue("យើងគួរតែធ្វើអំពើល្អ និងគោរពអ្នកដទៃ។",
                "We should practice kindness and respect everyone.", "km"),""
        )
        self.assertEqual(local_language_issue(
            "We should respect every person.",
            "We should respect every person.","km"),"source_text_copied")
        self.assertEqual(local_language_issue(
            "This translation is only English without native Khmer characters.",
            "We should practice kindness to every person.","km"),"missing_target_script")
        self.assertEqual(GLOSSARY_FULL_RANGE,"專有名詞庫!A2:O500")
        row=["修道","","Practice Dao","cultivating the Dao",
             "","","","","TRUE","","","","","","ការអនុវត្តធម៌"]
        glossary=parse_glossary_rows([row])
        self.assertEqual(glossary[0]["km"],"ការអនុវត្តធម៌")
        self.assertTrue(glossary[0]["locked"])

    def test_neural_voice_and_file_label(self):
        self.assertIn("km",EDGE_LANGS)
        self.assertNotIn("km",GPU_REQUIRED_LANGS)
        self.assertEqual(NATURAL_TTS_PROFILES["km"]["engine"],"edge")
        self.assertEqual(NATURAL_TTS_PROFILES["km"]["voice"],"km-KH-PisethNeural")
        self.assertEqual(output_label("km.mp3"),"高棉文TTS音檔.mp3")
        self.assertEqual(
            formal_drive_name({
                "period":257,"lesson":"第4堂","title":"修道保險單 | 賴義鍠"
            },"km.mp3"),
            "第257期_第4堂課_修道保險單_賴義鍠_高棉文TTS音檔.mp3"
        )

    def test_selected_translation_and_full_lesson(self):
        prod=src("translation-system/gemini_multi_production_runner.py")
        shadow=src("translation-system/gemini_full_lesson_shadow.py")
        batch=src("translation-system/batch_full_runner.py")
        for item in (prod,shadow,batch):
            self.assertIn('"km"',item)
        self.assertIn('("km", 14)',prod)
        self.assertIn('"km": {"type": "string"}',prod)
        self.assertIn('"km": row["km"]',shadow)
        self.assertIn("ALL nine target languages",shadow)
        self.assertIn('"km": "Khmer"',prod)
        self.assertIn('default="th,es,id,vi,hi,ta,ja,ko,km"',prod)
        self.assertIn('km Khmer',prod)

        module=ast.parse(prod)
        lang_list=next(n for n in module.body if isinstance(n,ast.Assign)
            and any(isinstance(t,ast.Name) and t.id=="LANGS" for t in n.targets))
        langs=ast.literal_eval(lang_list.value)
        self.assertEqual(langs,["th","es","id","vi","hi","ta","ja","ko","km"])
        selected=next(n for n in module.body if isinstance(n,ast.FunctionDef)
            and n.name=="selected_translation_schema")
        ns={}
        exec(compile(ast.Module(body=[selected],type_ignores=[]),"<schema>","exec"),ns)
        spec=ns["selected_translation_schema"](["km"])
        self.assertEqual(spec["properties"]["segments"]["items"]["required"],
                         ["segment_id","km"])
        self.assertEqual(spec["properties"]["segments"]["items"]["properties"]["km"],
                         {"type":"string"})

    def test_all_ui_and_bridge_paths(self):
        quick=src("studio/review.html")
        app=src("studio/app-20260923-48.js")
        editor=src("studio/review-editor.js")
        bridge=src("bridge/apps-script/Code.gs")
        self.assertEqual(quick.count('data-output-lang="'),10)
        self.assertIn('data-output-lang="km"',quick)
        self.assertIn('km:"ភាសាខ្មែរ"',editor)
        self.assertIn('code:"km"',app)
        self.assertIn('"ja","ko","km"',app)
        self.assertIn('"ja", "ko", "km"',bridge)
        self.assertIn('"km": "高棉文"',bridge)
        self.assertIn('const ccTotal=YOUTUBE_CC_TARGETS.length',app)

if __name__=="__main__":
    unittest.main()
