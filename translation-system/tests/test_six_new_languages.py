"""Six additional SoulKey target languages end-to-end static contracts."""
from pathlib import Path
import ast
import json
import re
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"translation-system"))
from config import GLOSSARY_FULL_RANGE
from gemini_engine import (
    LANGUAGE_NAMES,TARGET_SCRIPT_PATTERNS,
    parse_glossary_rows,local_language_issue
)
from natural_tts_config import NATURAL_TTS_PROFILES,EDGE_LANGS,GPU_REQUIRED_LANGS
from drive_naming import output_label,formal_drive_name
# Test selected pure helpers in isolation to keep Windows smoke tests
# independent of optional Kaggle-only Google / yt-dlp packages.
def extract_helpers(filename,function_names,assignment_names=(),namespace=None):
    tree=ast.parse((ROOT/"translation-system"/filename).read_text(encoding="utf-8"))
    nodes=[]
    for node in tree.body:
        if isinstance(node,ast.FunctionDef) and node.name in function_names:
            nodes.append(node)
        elif isinstance(node,ast.Assign):
            if any(isinstance(t,ast.Name) and t.id in assignment_names
                   for t in node.targets):
                nodes.append(node)
    scope=dict(namespace or {})
    exec(compile(ast.Module(body=nodes,type_ignores=[]),filename,"exec"),scope)
    return scope
multi=extract_helpers("gemini_multi_production_runner.py",
    ("selected_translation_schema","selected_translation_prompt","glossary_text"),
    ("LANGS",),{"json":json,"LANGUAGE_NAMES":{
        "bn":"Bengali","ne":"Nepali","lo":"Lao","my":"Burmese",
        "it":"Italian","pt":"Portuguese (Brazil)"}})
LANGS=multi["LANGS"]
selected_translation_schema=multi["selected_translation_schema"]
selected_translation_prompt=multi["selected_translation_prompt"]
glossary_text=multi["glossary_text"]
captions=extract_helpers("youtube_io.py",("_caption_language_candidates",),
                          ("AUTO_CC_TARGETS",))
AUTO_CC_TARGETS=captions["AUTO_CC_TARGETS"]
_caption_language_candidates=captions["_caption_language_candidates"]

EXTRA={
"bn":("Bengali","বাংলা","孟加拉文","bn-BD-PradeepNeural",15),
"ne":("Nepali","नेपाली","尼泊爾文","ne-NP-SagarNeural",16),
"lo":("Lao","ພາສາລາວ","寮文","lo-LA-ChanthavongNeural",17),
"my":("Burmese","မြန်မာဘာသာ","緬甸文","my-MM-ThihaNeural",18),
"it":("Italian","Italiano","義大利文","it-IT-DiegoNeural",19),
"pt":("Portuguese","Português","葡萄牙文","pt-BR-AntonioNeural",20),
}
def src(rel):
    return (ROOT/rel).read_text(encoding="utf-8")
class SixLanguageWorkflow(unittest.TestCase):
 def test_target_codes_and_selected_gemini_schema(self):
    self.assertEqual(len(LANGS),15)
    self.assertEqual(len(NATURAL_TTS_PROFILES),16)
    schema=selected_translation_schema(list(EXTRA))
    seg=schema["properties"]["segments"]["items"]
    self.assertEqual(seg["required"],["segment_id",*EXTRA])
    for code,(name,_,_,_,_) in EXTRA.items():
        self.assertIn(code,LANGS)
        self.assertTrue(LANGUAGE_NAMES[code].startswith(name))
        self.assertEqual(seg["properties"][code],{"type":"string"})
        self.assertIn(code,AUTO_CC_TARGETS)
    prompt=selected_translation_prompt([{"id":2,"text":"We should act with kindness."}],
        "(no glossary entries)",list(EXTRA))
    self.assertIn("Bengali",prompt)
    self.assertIn("Portuguese",prompt)
    self.assertNotIn("Thai",prompt)
 def test_native_script_and_glossary_mapping(self):
    self.assertEqual(GLOSSARY_FULL_RANGE,"專有名詞庫!A2:U500")
    for code in ("bn","ne","lo","my"):
        self.assertIn(code,TARGET_SCRIPT_PATTERNS)
        native=EXTRA[code][1]
        self.assertTrue(TARGET_SCRIPT_PATTERNS[code].search(native))
        issue=local_language_issue(
            "This is an English-only translation without native script.",
            "Kindness and respect are necessary for everyone.",code)
        self.assertIn(issue,{"missing_target_script","source_text_copied"})
    row=["修道","","","practice the Dao",
         "","","","","TRUE","","","","","","",
         *[x[1] for x in EXTRA.values()]]
    parsed=parse_glossary_rows([row])[0]
    gloss=glossary_text([row])
    self.assertTrue(parsed["locked"])
    for code,(_,native,_,_,index) in EXTRA.items():
        self.assertEqual(parsed[code],native)
        self.assertIn(f"{code}={native}",gloss)
 def test_production_edge_voice_and_drive_names(self):
    for code,(_,_,zh,voice,_) in EXTRA.items():
        self.assertIn(code,EDGE_LANGS)
        self.assertNotIn(code,GPU_REQUIRED_LANGS)
        profile=NATURAL_TTS_PROFILES[code]
        self.assertEqual(profile["voice"],voice)
        self.assertEqual(profile["engine"],"edge")
        self.assertEqual(output_label(code+".mp3"),zh+"TTS音檔.mp3")
        self.assertIn(zh,formal_drive_name({
            "period":258,"lesson":"第1堂","title":"修辦人生|王講師"
        },code+".mp3"))
 def test_ui_and_bridge_16_language_contract(self):
    studio=src("studio/app-20260923-48.js")
    quick=src("studio/review.html")
    editor=src("studio/review-editor.js")
    bridge=src("bridge/apps-script/Code.gs")
    self.assertEqual(quick.count('data-output-lang="'),16)
    for code,(_,native,zh,_,_) in EXTRA.items():
        self.assertIn(f'data-output-lang="{code}"',quick)
        self.assertIn(native,quick)
        self.assertIn(zh,quick)
        self.assertIn(f'code:"{code}"',studio)
        self.assertIn(f'{code}:"{native}',editor)
        self.assertIn(f'"{code}": "{zh}"',bridge)
        self.assertIn(f'"{code}": "{zh}"',src("translation-system/drive_naming.py"))
        self.assertEqual(_caption_language_candidates(code)[0],code)
    self.assertIn('"pt-BR"',src("translation-system/youtube_io.py"))
    self.assertIn("16",str(quick.count('data-output-lang="')))
 def test_main_and_shadow_runners_support_15(self):
    for filename in ("gemini_multi_production_runner.py","gemini_full_lesson_shadow.py",
                     "batch_full_runner.py"):
        s=src("translation-system/"+filename)
        for code in EXTRA:
            self.assertIn('"'+code+'"',s)
    self.assertIn('min(args.batch_size, 4) if len(requested)>10',
                  src("translation-system/gemini_multi_production_runner.py"))
    self.assertIn('專有名詞庫!A2:U500',
                  src("translation-system/config.py"))
if __name__=="__main__":
 unittest.main()
