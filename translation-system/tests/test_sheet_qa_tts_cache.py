import ast
import hashlib
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/"natural_tts_drive_cache.py"
CLASS=[node for node in ast.parse(SRC.read_text(encoding="utf8")).body
       if isinstance(node,ast.ClassDef) and node.name=="DriveTTSBlockCache"]
assert len(CLASS)==1

class Block:
    def __init__(self,index,text):
        self.index=index
        self.text_sha256=hashlib.sha256(text.encode()).hexdigest()

def load_class(remote_zip):
    def find(drive,folder,name):
        return {"id":"zip","name":name}
    def download(drive,file_id,dest):
        Path(dest).write_bytes(Path(remote_zip).read_bytes())
    globals={
        "Path":Path, "hashlib":hashlib, "json":json, "os":os, "zipfile":zipfile,
        "GROUP_SIZE":8,"MAX_BLOCK_BYTES":12*1024*1024,
        "NATURAL_TTS_PROFILES":{"es":{"voice":"fake","rate":"0%","pitch":"0Hz"}},
        "NATURAL_TTS_PROFILE_REVISION":"test-v1",
        "find_file":find,"download_drive_file":download,
        "upload_or_replace_file":lambda *args,**kw:None,
        "print":lambda *args,**kw:None
    }
    exec(compile(ast.Module(body=CLASS,type_ignores=[]),str(SRC),"exec"),globals)
    return globals["DriveTTSBlockCache"]

class ChangedAudioReuseTests(unittest.TestCase):
    def test_unmodified_blocks_reused_when_one_sentence_changes(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)
            archived=p/"archive.zip"
            old_1=Block(1,"unchanged sentence")
            old_2=Block(2,"old sentence")
            new_2=Block(2,"Gemma corrected sentence")
            old_bytes={1:b"A"*1700,2:b"B"*1800}
            records=[]
            for i,block in [(1,old_1),(2,old_2)]:
                value=old_bytes[i]
                records.append({
                    "block_index":i,"text_sha256":block.text_sha256,
                    "duration":1.2,"size":len(value),
                    "sha256":hashlib.sha256(value).hexdigest()})
            with zipfile.ZipFile(archived,"w") as zip:
                zip.writestr("manifest.json",json.dumps({
                    "lang":"es","source_sha256":"OLD_WHOLE_LESSON",
                    "profile_revision":"test-v1","voice":"fake",
                    "rate":"0%","pitch":"0Hz","group":0,"blocks":records}))
                for i,value in old_bytes.items():
                    zip.writestr(f"blocks/{i:04d}.mp3",value)
            Cache=load_class(archived)
            c=Cache(None,"folder","es","NEW_WHOLE_LESSON",
                    [old_1,new_2],p/"scratch")
            count=c.restore(p/"output")
            self.assertEqual(count,1)
            self.assertEqual((p/"output/blocks/0001.mp3").read_bytes(),old_bytes[1])
            self.assertFalse((p/"output/blocks/0002.mp3").exists())
            self.assertNotIn(0,c.restored_groups,
                            "Partial groups must be re-archived after regeneration")
            checkpoint=json.loads((p/"output/es.tts_checkpoint.json").read_text())
            self.assertEqual(len(checkpoint["blocks"]),1)
            self.assertEqual(checkpoint["blocks"][0]["text_sha256"],old_1.text_sha256)

if __name__=="__main__":
    unittest.main()
