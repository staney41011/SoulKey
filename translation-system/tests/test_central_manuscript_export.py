"""Regression for verified P259 source → Drive TXT/JSON/SRT delivery."""
import ast
import hashlib
import json
import pathlib
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
tree = ast.parse((ROOT / "central_manuscript_export.py").read_text("utf-8"))
names = {"_srt_timestamp", "manuscript_files", "_same_existing", "upload_verified_file"}
functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
sha = hashlib.sha256
def fake_fingerprint(segments):
    data=json.dumps(segments, sort_keys=True, ensure_ascii=False).encode()
    return sha(data).hexdigest()

def filename(task, name):
    return "P259_" + task["task_id"] + "_" + name

env = {
    "json": json,
    "hashlib": hashlib,
    "Path": pathlib.Path,
    "segments_fingerprint": fake_fingerprint,
    "formal_drive_name": filename,
}
exec(compile(ast.Module(body=functions, type_ignores=[]), "central_manuscript_export", "exec"),env)


class ManuscriptDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.final = {"revision": "abc123", "task_id": "P259-L02"}
        self.segments = [
            {"id": 0, "start": .21, "end": 2.04, "text": "Hello world"},
            {"id": 4, "start": 2.04, "end": 5.42, "text": "Second sentence"},
        ]
        self.english = {"job_id": "human-final", "segments": self.segments}
        self.thai = {"job_id": "qa-proven-001", "segments": [
            {**r,"text": "สวัสดีโลก" if r["id"]==0 else "ประโยคที่สอง"}
            for r in self.segments]}

    def test_english_is_human_final_and_can_be_read(self):
        files=env["manuscript_files"]("P259-L02","en",self.final,self.english)
        self.assertEqual(set(files),{"en.final.json","en.final.txt","en.final.srt"})
        self.assertEqual(files["en.final.txt"].decode(),"Hello world\nSecond sentence\n")
        self.assertIn("00:00:00,210 --> 00:00:02,040",
                      files["en.final.srt"].decode())
        manifest=json.loads(files["en.final.json"])
        self.assertEqual(manifest["en_backup_revision"],"abc123")
        self.assertEqual(manifest["verified_translation_job"],"human-final")
        self.assertEqual([r["id"] for r in manifest["segments"]],[0,4])

    def test_ai_translation_requires_qa_job(self):
        files=env["manuscript_files"]("P259-L02","th",self.final,self.thai)
        self.assertEqual(set(files),{"th.json","th.txt","th.srt"})
        self.assertIn("สวัสดีโลก",files["th.txt"].decode())
        with self.assertRaisesRegex(ValueError,"unverified_ai_translation"):
            env["manuscript_files"]("P259-L02","th",self.final,self.english)

    def test_invalid_segment_does_not_create_manuscript(self):
        dup={**self.english,"segments":self.segments+[self.segments[0]]}
        with self.assertRaisesRegex(ValueError,"invalid_manuscript_segment"):
            env["manuscript_files"]("P259-L02","en",self.final,dup)

    def test_legacy_json_same_text_is_reused_without_overwrite(self):
        files=env["manuscript_files"]("P259-L02","en",self.final,self.english)
        legacy=json.dumps({"kind":"en","segments":self.segments}).encode()
        self.assertTrue(env["_same_existing"]("en.final.json",legacy,files["en.final.json"]))
        altered=[{**self.segments[0],"text":"Wrong lesson"},self.segments[1]]
        bad=json.dumps({"segments":altered}).encode()
        self.assertFalse(env["_same_existing"]("en.final.json",bad,files["en.final.json"]))
        self.assertFalse(env["_same_existing"]("en.final.txt",b"wrong",files["en.final.txt"]))

    def test_conflicting_drive_file_cannot_be_overwritten(self):
        blob=b"correct text\n"
        env["find_file"]=lambda _drive, _folder, _name: {"id":"existing"}
        def dl(_drive,_id,path):
            Path(path).write_bytes(b"WRONG SOURCE")
        env["download_drive_file"]=dl
        def forbidden(*args,**kwargs):
            raise AssertionError("must not call upload_or_replace_file on conflicting file")
        env["upload_or_replace_file"]=forbidden
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(RuntimeError,"drive_manuscript_conflict"):
                env["upload_verified_file"](
                    None,"folder","en.final.txt",blob,
                    {"task_id":"P259-L02"},Path(d)
                )

    def test_new_file_uploaded_with_canonical_name_and_readback(self):
        payload=b"hola\n"
        memory={}
        env["find_file"]=lambda _drive,_folder,_name: None
        def upload(_drive,folder,path,name,display_name):
            memory["blob"]=Path(path).read_bytes()
            memory["name"]=name
            memory["display"]=display_name
            memory["folder"]=folder
            return {"id":"upload-id"}
        def download(_drive,_id,path):
            Path(path).write_bytes(memory["blob"])
        env["upload_or_replace_file"]=upload
        env["download_drive_file"]=download
        with tempfile.TemporaryDirectory() as d:
            result=env["upload_verified_file"](
                None,"folder","es.txt",payload,{"task_id":"P259-L02"},Path(d))
        self.assertEqual(result["id"],"upload-id")
        self.assertEqual(memory["blob"],payload)
        self.assertEqual(memory["name"],"es.txt")
        self.assertEqual(memory["folder"],"folder")
        self.assertEqual(memory["display"],"P259_P259-L02_es.txt")


if __name__=="__main__":
    unittest.main()
