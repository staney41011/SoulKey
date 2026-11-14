import ast,json,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def target():
    file=ROOT/"translation-system/google_sheet_pilot_tts_runner.py"
    syntax=ast.parse(file.read_text(encoding="utf-8"))
    definition=next(x for x in syntax.body if isinstance(x,ast.FunctionDef) and x.name=="recover_duration_from_english_cc")
    env={"Path":Path,"json":json,"re":__import__("re")}
    exec(compile(ast.Module(body=[definition],type_ignores=[]),str(file),"exec"),env)
    return env["recover_duration_from_english_cc"],env

class SheetsSourceDurationTests(unittest.TestCase):
    def test_english_cc_restores_missing_video_duration_without_fabrication(self):
        func,env=target()
        with tempfile.TemporaryDirectory() as folder:
            env["find_file"]=lambda *a:{"id":"ccfile"}
            def download(drive,id,path):
                value={"video_id":"4l1T2MlQYUI","language":"en","segments":[{"start":i*60+0.1,"end":i*60+59.6} for i in range(31)]+[{"start":1860,"end":1896.837}]}
                path.write_text(json.dumps(value),encoding="utf-8")
            env["download_drive_file"]=download
            result=func(None,"lesson_source",Path(folder),"https://youtu.be/4l1T2MlQYUI")
            self.assertEqual(result,1896.0)
    def test_wrong_video_is_never_treated_as_own_duration(self):
        func,env=target()
        with tempfile.TemporaryDirectory() as folder:
            env["find_file"]=lambda *a:{"id":"wrong"}
            env["download_drive_file"]=lambda drive,id,path:path.write_text(json.dumps({"video_id":"WRONG_VIDEO","language":"en","segments":[{"start":i,"end":i+1}for i in range(100)]}),encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError,"video ID"):
                func(None,"lesson_source",Path(folder),"https://youtu.be/4l1T2MlQYUI")
    def test_no_english_track_returns_none(self):
        func,env=target()
        env["find_file"]=lambda *a:None
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(func(None,"lesson_source",Path(folder),"https://youtu.be/4l1T2MlQYUI"))

if __name__=="__main__":
    unittest.main()
