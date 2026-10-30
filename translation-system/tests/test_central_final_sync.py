import hashlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from central_final_sync import central_final,sync_finals

TASK="P260-L01"
SEGMENTS=[{"id":1,"start":0,"end":12,"text":"Human revision"}]


def source(kind="en",segments=None):
    text=json.dumps({"task_id":TASK,"kind":kind,"segments":segments or SEGMENTS},ensure_ascii=False)
    digest=hashlib.sha256(text.encode()).hexdigest()
    return [[TASK,digest,"1"]],[[TASK,digest,"0","1",text,"now",digest]]


class FinalSyncTests(unittest.TestCase):
    def test_hash_and_task_are_required(self):
        index,parts=source()
        self.assertEqual(central_final(TASK,"en",index,parts)["segments"],SEGMENTS)
        parts[0][4]+=" "
        with self.assertRaisesRegex(RuntimeError,"central_final_invalid"):
            central_final(TASK,"en",index,parts)
        self.assertIsNone(central_final("P260-L02","en",index,parts))

    def run_sync(self,old,kind="en",central=True):
        index,parts=source(kind)
        name="en.final.json" if kind=="en" else "zh-TW.final.json"
        files={}
        if old is not None:files[name]=json.dumps(old).encode()
        reads=[]
        def read(_s,_id,area):
            reads.append(area)
            if area=="tasks":return [[TASK,"260","第1堂"]]
            if "索引" in area:return index if central else []
            return parts
        def find(_d,_folder,label):return {"id":label} if label in files else None
        def download(_d,file,path):Path(path).write_bytes(files[file])
        def upload(_d,_folder,path,label):
            files[label]=Path(path).read_bytes();return {"id":label}
        fake_io=types.SimpleNamespace(build_google_services=lambda:("drive","sheets"),read_values=read,
            find_file=find,download_drive_file=download,upload_or_replace_file=upload)
        config=types.SimpleNamespace(SPREADSHEET_ID="sheet",TASK_SHEET_RANGE="tasks")
        folders=types.SimpleNamespace(resolve_lesson_folders=lambda *a:{"translation":"en-folder","transcript":"zh-folder"})
        with patch.dict(sys.modules,{"google_io":fake_io,"config":config,"lesson_paths":folders}):
            with tempfile.TemporaryDirectory() as d:sync_finals(TASK,[kind],d)
        return files,reads

    def test_newer_human_final_archives_previous_before_publish(self):
        old={"task_id":TASK,"kind":"en","segments":[{**SEGMENTS[0],"text":"Previous human version"}]}
        files,_=self.run_sync(old)
        archive=[n for n in files if ".revision-" in n]
        self.assertEqual(len(archive),1)
        self.assertEqual(json.loads(files[archive[0]]),old)
        self.assertEqual(json.loads(files["en.final.json"])["segments"],SEGMENTS)

    def test_legacy_only_final_is_unchanged(self):
        old={"segments":[{**SEGMENTS[0],"text":"Legacy remains"}]}
        files,_=self.run_sync(old,central=False)
        self.assertEqual(list(files),["en.final.json"])
        self.assertEqual(json.loads(files["en.final.json"]),old)

    def test_different_lesson_cannot_be_overwritten(self):
        with self.assertRaisesRegex(RuntimeError,"drive_final_task_mismatch"):
            self.run_sync({"task_id":"P260-L02","segments":SEGMENTS})

    def test_changed_chinese_source_timeline_cannot_be_published(self):
        with self.assertRaisesRegex(RuntimeError,"central_final_timeline_conflict"):
            self.run_sync({"task_id":TASK,"segments":[{**SEGMENTS[0],"start":8}]},kind="zh")


if __name__=="__main__":unittest.main()
