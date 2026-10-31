"""Offline tests: scoped GitHub token mirror + automatic multi resume."""
import ast
import base64
import json
import os
import re
import subprocess
import tempfile
import time
import types
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
def functions(filename, names, ns):
    tree=ast.parse((ROOT/filename).read_text(encoding="utf8"))
    body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    assert len(body)==len(names)
    exec(compile(ast.Module(body=body,type_ignores=[]),filename,"exec"),ns)

class Response:
    def __init__(self,obj,status=200):
        self.status=status
        self.raw=json.dumps(obj).encode()
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def read(self): return self.raw

class MirrorTests(unittest.TestCase):
    def setUp(self):
        self.ctx=dict(base64=base64,json=json,os=os,re=re,time=time,urllib=urllib,Path=Path,
                      GITHUB_OWNER="staney41011",GITHUB_REPO="SoulKey",GITHUB_REF="main",DRIVE_CHECKPOINT_NAME="gemini-shadow-checkpoint.json",
                      _ACTIONS_MIRROR_INTERVAL_SECONDS=600,_actions_last_mirror={})
        functions("translation-system/gemini_checkpoint.py",[
            "_normalize_task_id","github_checkpoint_path",
            "_publish_github_with_actions_token","publish_github_checkpoint"],self.ctx)
        self.requests=[]
        self.token="synthetic-actions-token"
    def fake_api(self,req,timeout=30):
        self.requests.append(req)
        self.assertEqual(req.get_header("Authorization"),"Bearer "+self.token)
        if req.get_method()=="GET":
            raise urllib.error.HTTPError(req.full_url,404,"Missing",{},None)
        body=json.loads(req.data)
        self.assertEqual(body["branch"],"main")
        self.assertEqual(json.loads(base64.b64decode(body["content"]))["task_id"],"P258-L03")
        return Response({"content":{"sha":"created"}},201)
    def publish(self,payload):
        return self.ctx["publish_github_checkpoint"]("P258-L03",payload)
    def test_actions_token_bypasses_old_apps_script_pat(self):
        with patch.dict(os.environ,{"SOULKEY_GITHUB_ACTIONS_TOKEN":self.token,
                                    "SOULKEY_BRIDGE_URL":"https://example.invalid",
                                    "SOULKEY_RUNTIME_NONCE":"dummy"}),\
             patch.object(urllib.request,"urlopen",side_effect=self.fake_api):
            result=self.publish({"task_id":"P258-L03","checkpoint_seq":1})
        self.assertEqual(result["backend"],"actions_token")
        self.assertEqual(len(self.requests),2)
    def test_throttled_batch_and_final_mirror(self):
        clock=[10000]
        with patch.dict(os.environ,{"SOULKEY_GITHUB_ACTIONS_TOKEN":self.token}),\
             patch.object(urllib.request,"urlopen",side_effect=self.fake_api),\
             patch.object(time,"monotonic",side_effect=lambda:clock[0]):
            first=self.publish({"task_id":"P258-L03","checkpoint_seq":1})
            clock[0]+=15
            skipped=self.publish({"task_id":"P258-L03","checkpoint_seq":2})
            final=self.publish({"task_id":"P258-L03","checkpoint_seq":3,"status":"complete"})
        self.assertTrue(first["ok"])
        self.assertEqual(skipped["reason"],"throttled")
        self.assertTrue(final["ok"])
        self.assertEqual(len(self.requests),4)
    def test_403_fails_fast_without_leak(self):
        def deny(req,timeout=30):
            self.requests.append(req)
            if req.get_method()=="GET":return Response({"sha":"old"})
            raise urllib.error.HTTPError(req.full_url,403,"Forbidden",{},None)
        with patch.dict(os.environ,{"SOULKEY_GITHUB_ACTIONS_TOKEN":self.token}),\
             patch.object(urllib.request,"urlopen",side_effect=deny):
            with self.assertRaisesRegex(RuntimeError,"contents: write") as raised:
                self.publish({"task_id":"P258-L03"})
        self.assertEqual(len(self.requests),2)
        self.assertNotIn(self.token,str(raised.exception))
    def test_existing_sha(self):
        def existing(req,timeout=30):
            if req.get_method()=="GET":return Response({"sha":"already"})
            self.assertEqual(json.loads(req.data)["sha"],"already")
            return self.fake_api(req,timeout=timeout)
        with patch.object(urllib.request,"urlopen",side_effect=existing):
            r=self.ctx["_publish_github_with_actions_token"](
                "P258-L03",{"task_id":"P258-L03"},self.token)
        self.assertTrue(r["ok"])
    def test_drive_failure_forces_mirror_even_if_recently_throttled(self):
        functions("translation-system/gemini_checkpoint.py",
                  ["save_persistent_checkpoint"],self.ctx)
        self.ctx["_write_json_atomic"]=lambda path,payload:path
        self.ctx["save_drive_checkpoint"]=lambda *args:(_ for _ in ()).throw(
            ConnectionError("Drive unavailable"))
        self.ctx["_actions_last_mirror"]["P258-L03"]=time.monotonic()
        with patch.dict(os.environ,{"SOULKEY_GITHUB_ACTIONS_TOKEN":self.token}),\
             patch.object(urllib.request,"urlopen",side_effect=self.fake_api):
            with tempfile.TemporaryDirectory() as temp:
                result=self.ctx["save_persistent_checkpoint"](
                    "P258-L03",{"task_id":"P258-L03","checkpoint_seq":22},
                    drive=object(),translation_folder_id="folder",workdir=temp)
        self.assertTrue(result["github"]["ok"])
        self.assertFalse(result["drive"]["ok"])
        self.assertEqual(len(self.requests),2)

    def test_drive_and_github_both_failed_do_not_fake_success(self):
        functions("translation-system/gemini_checkpoint.py",
                  ["save_persistent_checkpoint"],self.ctx)
        self.ctx["_write_json_atomic"]=lambda path,payload:path
        self.ctx["save_drive_checkpoint"]=lambda *args:(_ for _ in ()).throw(
            ConnectionError("Drive unavailable"))
        self.ctx["publish_github_checkpoint"]=lambda *args,**kwargs:(
            _ for _ in ()).throw(RuntimeError("Mirror unavailable"))
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RuntimeError,"均未保存成功"):
                self.ctx["save_persistent_checkpoint"](
                    "P258-L03",{"task_id":"P258-L03"},
                    drive=object(),translation_folder_id="folder",workdir=temp)

    def test_loader_uses_github_during_drive_outage(self):
        functions("translation-system/gemini_checkpoint.py",
                  ["load_persistent_checkpoint"],self.ctx)
        self.ctx["load_github_checkpoint"]=lambda *_:{"task_id":"P258-L03","checkpoint_seq":33}
        self.ctx["load_drive_checkpoint"]=lambda *args:(_ for _ in ()).throw(
            ConnectionError("Drive unavailable"))
        self.ctx["_read_json"]=lambda path:{}
        with tempfile.TemporaryDirectory() as temp:
            checkpoint, origin=self.ctx["load_persistent_checkpoint"](
                "P258-L03",drive=object(),translation_folder_id="folder",
                workdir=temp)
        self.assertEqual(checkpoint["checkpoint_seq"],33)
        self.assertEqual(origin,"github")

    def test_invalid_id_prevents_path_injection(self):
        with self.assertRaises(ValueError):
            self.ctx["publish_github_checkpoint"]("../token",{})
    def test_workflow_uses_short_lived_scoped_token(self):
        y=(ROOT/".github/workflows/kaggle_web_job.yml").read_text(encoding="utf8")
        cpu=y.split("\n  cpu:\n",1)[1]
        self.assertIn("contents: write",cpu)
        self.assertIn("SOULKEY_GITHUB_ACTIONS_TOKEN: __DOLLAR__{{ github.token }}".replace("__DOLLAR__","$"),cpu)

class AutoResumeTests(unittest.TestCase):
    def test_worker_routes_multi_to_checkpoint_resume(self):
        s=(ROOT/"translation-system/web_job_worker.py").read_text(encoding="utf8")
        self.assertIn('if cmd and args.stage=="multi":',s)
        self.assertIn("run_checkpointed_multi([",s)
    def test_credentials_refreshed_only_on_retry(self):
        ns={"subprocess":subprocess,"time":types.SimpleNamespace(sleep=lambda t:None)}
        functions("translation-system/web_job_worker.py",["run_checkpointed_multi"],ns)
        events=[]
        def fake_run(cmd):
            events.append("run")
            if events.count("run")==1:
                raise subprocess.CalledProcessError(1,cmd)
        ns["run"]=fake_run
        ns["run_checkpointed_multi"](["python","multi"],retry_waits=(0,),
            refresh_credentials=lambda:events.append("refresh"))
        self.assertEqual(events,["run","refresh","run"])
if __name__=="__main__":unittest.main()
