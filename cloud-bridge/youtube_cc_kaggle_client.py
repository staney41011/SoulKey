#!/usr/bin/env python3
"""Run one isolated, CPU-only Kaggle caption extractor and verify its output.

No API keys, Bridge Keys, Google tokens or writable source documents enter
the Kaggle job. GitHub retains the OIDC token and performs all Sheet writes.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

KERNEL=os.environ.get("SOULKEY_CC_KAGGLE_KERNEL","cwlmrcsir/soulkey-cc-reader")
LANGS={"en","th","es","id","vi","sd","ta"}
def command(*args,timeout=180):
    result=subprocess.run(args,text=True,capture_output=True,timeout=timeout)
    if result.returncode!=0:
        error=(result.stderr or result.stdout).strip()
        raise RuntimeError("Kaggle CLI "+args[1]+" failed: "+error[:250])
    return result.stdout
def capture(video_id,languages):
    if not os.environ.get("KAGGLE_API_TOKEN"):
        raise RuntimeError("kaggle_api_token_not_configured")
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}",video_id):
        raise RuntimeError("invalid_youtube_video_id")
    langs=list(dict.fromkeys(languages))
    if not langs or any(x not in LANGS for x in langs):
        raise RuntimeError("invalid_caption_languages")
    owner,name=KERNEL.split("/",1)
    if not re.fullmatch(r"[A-Za-z0-9_-]+",owner) or not re.fullmatch(r"[a-z0-9-]+",name):
        raise RuntimeError("invalid_kaggle_kernel_id")
    current=Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="soulkey-cc-") as base:
        root=Path(base)
        job=root/"job";job.mkdir()
        result_dir=root/"results";result_dir.mkdir()
        shutil.copy(current/"youtube_cc_worker.py",job/"youtube_cc_worker.py")
        shutil.copy(current/"youtube_cc_kaggle.py",job/"youtube_cc_kaggle.py")
        (job/"cc_job.json").write_text(
            json.dumps({"video_id":video_id,"languages":langs},ensure_ascii=False),
            encoding="utf-8"
        )
        (job/"kernel-metadata.json").write_text(json.dumps({
            "id":KERNEL,"title":"SoulKey CC Reader",
            "code_file":"youtube_cc_kaggle.py",
            "language":"python","kernel_type":"script",
            "is_private":True,"enable_internet":True,"enable_gpu":False,
            "enable_tpu":False,"dataset_sources":[],
            "competition_sources":[],"kernel_sources":[],"model_sources":[]
        },indent=2),encoding="utf-8")
        command("kaggle","kernels","push","-p",str(job),"-t","3600",timeout=120)
        completed=False
        for attempt in range(115):
            try:status=command("kaggle","kernels","status",KERNEL,timeout=30).lower()
            except Exception:status=""
            if "complete" in status:
                completed=True;break
            if any(x in status for x in ("error","failed","failure","cancel")):
                try:
                    logs=command("kaggle","kernels","logs",KERNEL,timeout=45)
                    # Source caption scripts never receive any secrets.
                    print("KAGGLE_CC_ERROR_LOG_TAIL",logs[-4500:],flush=True)
                except Exception as diagnostic:
                    print("KAGGLE_CC_LOG_UNAVAILABLE",
                          type(diagnostic).__name__,flush=True)
                raise RuntimeError("kaggle_caption_kernel_failed:"+status[:180])
            if attempt%10==0:
                print("KAGGLE_CC_WAITING",video_id,"poll",attempt,flush=True)
            time.sleep(10)
        if not completed:
            raise RuntimeError("kaggle_caption_kernel_timeout")
        command("kaggle","kernels","output",KERNEL,"-p",str(result_dir),timeout=180)
        hits=list(result_dir.rglob("cc_capture_result.json"))
        if len(hits)!=1:raise RuntimeError("kaggle_cc_output_missing")
        payload=json.loads(hits[0].read_text(encoding="utf-8"))
        if payload.get("video_id")!=video_id:
            raise RuntimeError("kaggle_cc_source_video_mismatch")
        raw=payload.get("captions")
        if not isinstance(raw,dict) or not raw:
            raise RuntimeError("kaggle_cc_no_languages")
        if any(x not in langs for x in raw):
            raise RuntimeError("kaggle_cc_unrequested_language")
        out={}
        for lang,row in raw.items():
            txt=str(row.get("text",""))
            source=str(row.get("source",""))
            if not txt.strip() or len(txt)>700000:
                raise RuntimeError("kaggle_cc_invalid_language_content")
            out[lang]=(txt,source)
        return out,payload.get("missing_languages") or []
