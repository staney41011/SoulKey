import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import gemma_draft_checkpoint as checkpoint
import p259_gemma4_kaggle as gemma

class DraftTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.files=[];self.blobs={};self.created=[]
        def upload(_drive,folder,path,name):
            self.assertEqual(folder,"lesson-log")
            file_id=str(len(self.created)+1);self.created.append(file_id)
            self.blobs[file_id]=Path(path).read_bytes()
            self.files.append({"id":file_id,"name":name,"modifiedTime":f"2026-10-31T00:00:{len(self.created):02d}Z"})
            return {"id":file_id}
        def download(_drive,file_id,path):Path(path).write_bytes(self.blobs[file_id])
        for target,value in [("list_snapshots",lambda *_:self.files),("create_snapshot",upload),("download_snapshot",download)]:
            self.addCleanup(patch.stopall);patch.object(checkpoint,target,side_effect=value).start()
        self.store=checkpoint.DraftCheckpoint(object(),"lesson-log",self.temporary.name,"P259-L01","km","a"*64,[1,2])
        self.rows=[{"id":1,"text":"draft one"},{"id":2,"text":"draft two"}]
        self.output=contextlib.redirect_stdout(io.StringIO());self.output.__enter__();self.addCleanup(self.output.__exit__,None,None,None)

    def test_append_only_round_trip_and_resume_latest(self):
        self.assertIsNone(self.store.load());self.store.save(self.rows);first=self.blobs["1"]
        improved=[{"id":1,"text":"corrected one"},self.rows[1]];self.store.save(improved)
        self.assertEqual(len(self.created),2);self.assertEqual(self.blobs["1"],first)
        self.assertEqual(self.store.load(),improved)
        self.store.save(improved);self.assertEqual(len(self.created),2,"Unchanged rounds must not upload duplicate snapshots")
        payload=json.loads(self.blobs["2"]);self.assertEqual(payload["status"],"needs_review")
        self.assertNotIn("semantic_pass_cache",payload);self.assertNotIn("qa_passed",payload)

    def test_modified_snapshot_is_preserved_and_blocked(self):
        self.store.save(self.rows)
        original=json.loads(self.blobs["1"]);original["segments"][0]["text"]="Human edited draft"
        self.blobs["1"]=json.dumps(original).encode()
        with self.assertRaisesRegex(RuntimeError,"integrity_error"):self.store.load()
        self.assertEqual(len(self.created),1);self.assertIn(b"Human edited draft",self.blobs["1"])

    def test_other_source_revision_or_lesson_is_not_resumed(self):
        self.store.save(self.rows)
        for task,lang,revision in [("P259-L02","km","a"*64),("P259-L01","ko","a"*64),("P259-L01","km","b"*64)]:
            other=checkpoint.DraftCheckpoint(object(),"lesson-log",self.temporary.name,task,lang,revision,[1,2])
            self.assertIsNone(other.load())
        original=json.loads(self.blobs["1"]);original["task_id"]="P259-L02"
        self.blobs["1"]=json.dumps(original).encode()
        with self.assertRaisesRegex(RuntimeError,"integrity_error"):self.store.load()

    def test_incomplete_duplicate_and_empty_ids_are_rejected(self):
        for rows in ([self.rows[0]],[self.rows[0],self.rows[0]],[],[{"id":1,"text":None},self.rows[1]]):
            with self.assertRaises(ValueError):self.store.save(rows)
        self.assertEqual(self.created,[])

    def test_readback_mismatch_is_never_marked_verified(self):
        with patch.object(checkpoint,"download_snapshot",side_effect=lambda _drive,_id,path:Path(path).write_bytes(b"wrong")):
            with self.assertRaisesRegex(RuntimeError,"readback_mismatch"):self.store.save(self.rows)
        self.assertIsNone(self.store.last_sha)

    def test_partial_repair_survives_a_later_model_error(self):
        class Model:
            def __init__(self):self.calls=0
            def json(self,*_args,**_kw):
                self.calls+=1
                if self.calls==1:return {"segments":[{"id":1,"text":"fixed before failure"}]}
                raise RuntimeError("model unavailable")
        source=[{"id":1,"text":"source one"},{"id":2,"text":"source two"}]
        with patch.object(gemma,"qa",return_value={1:["meaning"],2:["meaning"]}):
            with self.assertRaisesRegex(RuntimeError,"model unavailable"):
                gemma.repair(Model(),"km",source,self.rows,checkpoint=self.store.save)
        resumed=self.store.load();self.assertEqual(resumed[0]["text"],"fixed before failure")
        self.assertEqual(resumed[1]["text"],"draft two")

    def test_resumed_draft_still_runs_current_qa_with_empty_semantic_cache(self):
        self.store.save(self.rows);resumed=self.store.load()
        with patch.object(gemma,"qa",return_value={}) as qa:
            rows,_rounds,_repairs=gemma.repair(object(),"km",[{"id":1,"text":"one"},{"id":2,"text":"two"}],resumed)
        self.assertEqual(qa.call_count,1);self.assertEqual(qa.call_args.kwargs["semantic_pass_cache"],set())
        self.assertEqual(rows,self.rows)

if __name__=="__main__":unittest.main(verbosity=2)
