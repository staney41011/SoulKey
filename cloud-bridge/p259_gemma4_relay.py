#!/usr/bin/env python3
"""P259 Cloud Run OIDC <-> private Kaggle Gemma4 relay.

Only source English and glossary are included in the private Kaggle kernel.
GitHub/Kaggle/Google access credentials are NEVER serialized into a notebook.
Cloud Run's existing verified upload and QA endpoints finalize each language.
"""
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from translation_worker import github_oidc,bridge_request

REPO="staney41011/SoulKey"
KERNEL="cwlmrcsir/soulkey-p259-gemma4-relay"
MODEL="google/gemma-4/transformers/gemma-4-12b-it/1"
# Existing deployed Cloud Run requires a gemini-* model identifier. This is an
# EXPLICIT compatibility label, NOT a claim Gemini was used for inference.
# Model provenance must always be documented as Gemma4 local QA.
QA_COMPAT_MODEL="gemini-compat-gemma4-12b-it-localqa"
ALLOWED={"P259-L01","P259-L02","P259-L03","P259-L04"}
LANGUAGES={"th","es","id","vi","km","hi","ta","ja","ko","bn","ne","lo","my","it","pt"}
RESULT_NAME="p259_gemma4_result.json"

KAGGLE_PY=r'''
import base64,json,os,subprocess,sys,time,traceback
from pathlib import Path
root=Path("/kaggle/working/SoulKey")
job=json.loads(base64.b64decode(__JOB_BASE64__).decode("utf-8"))
# The private notebook contains no tokens, OAuth credentials, API keys or cookies.
print("P259_GEMMA4_PRIVATE_INPUT",job["task_id"],
      len(job["segments"]),len(job["langs"]),flush=True)
subprocess.run(["git","clone","--depth","1",
    "https://github.com/staney41011/SoulKey.git",str(root)],check=True)
subprocess.run([sys.executable,"-m","pip","install","-q",
    "-r",str(root/"translation-system/requirements-gemini.txt"),
    "huggingface_hub"],check=True)
sys.path.insert(0,str(root/"translation-system"))
from p259_gemma4_kaggle import Gemma,translate,repair
out={"task_id":job["task_id"],"revision":job["revision"],
     "job_id":job["id"],"source_ids":[int(s["id"]) for s in job["segments"]],
     "model":"gemma-4-12b-it-kaggle-localqa","results":{},"failures":{}}
target=Path("/kaggle/working/p259_gemma4_result.json")
source=[{"id":int(s["id"]),"text":str(s["text"])} for s in job["segments"]]
gemma=Gemma(glossary=job.get("glossary",""))
for lang in job["langs"]:
    if lang in job.get("qa_completed_languages",[]):
        print("GEMMA4_SKIP_EXISTING_QA",job["task_id"],lang,flush=True)
        continue
    try:
        proposed=translate(gemma,lang,source)
        rows,rounds,repairs=repair(gemma,lang,source,proposed)
        out["results"][lang]={"segments":rows,"qa_batches":rounds*((len(source)+5)//6),
            "repair_count":repairs,"unresolved":0,"status":"passed"}
        print("GEMMA4_LOCAL_QA_PASSED",job["task_id"],lang,len(rows),flush=True)
    except Exception as exc:
        out["failures"][lang]=type(exc).__name__+": "+str(exc)[:220]
        print("GEMMA4_NEEDS_REVIEW",job["task_id"],lang,type(exc).__name__,flush=True)
    finally:
        # Checkpoints are saved in the private Kaggle run, never falsely
        # declared uploaded to central Google Sheet before GitHub reads them.
        target.write_text(json.dumps(out,ensure_ascii=False),encoding="utf-8")
print("GEMMA4_PRIVATE_RUN_FINISHED",len(out["results"]),len(out["failures"]),flush=True)
'''

def safe_call(args,**kw):
    print("P259_RELAY_EXEC",args[:3],flush=True)
    return subprocess.run(args,check=True,text=True,**kw)

def private_kernel(job):
    encoded=base64.b64encode(json.dumps(job,ensure_ascii=False).encode("utf-8")).decode("ascii")
    root=Path(tempfile.mkdtemp(prefix="p259-gemma-private-"))
    metadata={"id":KERNEL,"title":"Soulkey P259 Gemma4 Relay",
        "code_file":"p259_gemma_private.py",
        "language":"python","kernel_type":"script","is_private":True,
        "enable_gpu":True,"enable_internet":True,
        "kernel_sources":["cwlmrcsir/translate-system"],
        "model_sources":[]}
    (root/"kernel-metadata.json").write_text(json.dumps(metadata,indent=2),encoding="utf-8")
    (root/"p259_gemma_private.py").write_text(KAGGLE_PY.replace("__JOB_BASE64__",repr(encoded)),encoding="utf-8")
    return root

def run_kernel(job):
    root=private_kernel(job)
    try:
        safe_call(["kaggle","kernels","push","-p",str(root),
                   "--accelerator","NvidiaTeslaT4","-t","14400"],timeout=150)
        deadline=time.monotonic()+14440
        status="QUEUED"
        while time.monotonic()<deadline:
            check=subprocess.run(["kaggle","kernels","status",KERNEL],
                text=True,capture_output=True,timeout=45)
            value=(check.stdout+"\n"+check.stderr).upper()
            if check.returncode!=0 or "CANNOT ACCESS KERNEL" in value:
                raise RuntimeError("Kaggle relay slug or kernel access invalid: "+
                                   value[-350:])
            if "COMPLETE" in value:
                status="COMPLETE";break
            if any(word in value for word in ("ERROR","FAILED","CANCELLED")):
                status="ERROR";break
            time.sleep(15)
        print("P259_GEMMA4_REMOTE_KERNEL_STATUS",status,flush=True)
        if status!="COMPLETE":
            subprocess.run(["kaggle","kernels","logs",KERNEL],timeout=100)
            raise RuntimeError("Kaggle private Gemma4 run status "+status)
        output=Path(os.environ.get("RUNNER_TEMP","/tmp"))/"p259-gemma-results"
        output.mkdir(parents=True,exist_ok=True)
        # The working directory also contains the GGUF weights and cloned
        # repository. Download only the validated result, never gigabytes of
        # model cache just to read a few kilobytes of translation/QA receipts.
        safe_call(["kaggle","kernels","output",KERNEL,"-p",str(output),
                   "--file-pattern",r"(^|/)p259_gemma4_result\.json$"],timeout=180)
        matches=list(output.rglob(RESULT_NAME))
        if len(matches)!=1:raise RuntimeError("Kaggle result JSON missing or duplicated")
        return json.loads(matches[0].read_text(encoding="utf-8"))
    finally:
        # Kaggle source persists as a PRIVATE kernel version on owner account.
        # The GitHub runner's temporary generated source is deleted.
        import shutil
        shutil.rmtree(root,ignore_errors=True)

def safe_failure_summary(raw, language):
    """Only print allowlisted QA IDs or exception class; never lecture text.

    Full Kaggle error strings can contain model output or private excerpts.
    This summary is suitable for ordinary GitHub Actions log retention.
    """
    value=str(raw or "")
    match=re.fullmatch(
        r"ValueError: gemma4_unresolved_qa_([a-z]{2})_([0-9]+(?:,[0-9]+)*)",
        value)
    if match and match.group(1)==language:
        return "unresolved_segment_ids="+match.group(2)
    cls=value.partition(":")[0].strip()
    allowed={"ValueError","RuntimeError","TimeoutError","HTTPError",
             "KeyError","TypeError","ConnectionError"}
    return "failure_class="+(cls if cls in allowed else "unclassified")


def checked_output(job,data):
    if data.get("job_id")!=job["id"] or data.get("task_id")!=job["task_id"] or data.get("revision")!=job["revision"]:
        raise RuntimeError("remote_result_job_or_revision_mismatch")
    source=[int(x["id"]) for x in job["segments"]]
    if source!=data.get("source_ids"):
        raise RuntimeError("remote_result_source_ids_mismatch")
    done=set(job.get("qa_completed_languages",[]))
    for language,item in data.get("results",{}).items():
        if language not in job["langs"] or language in done:
            raise RuntimeError("remote_result_unrequested_or_already_approved")
        rows=item.get("segments",[])
        actual=[int(x.get("id",-1)) for x in rows]
        if actual!=source or not all(str(x.get("text","")).strip() for x in rows):
            raise RuntimeError("remote_result_invalid_segments_"+language)
        if item.get("status")!="passed" or item.get("unresolved")!=0:
            raise RuntimeError("remote_result_qa_not_passed_"+language)
        done.add(language)
    return done

def main():
    def continuation(available):
        output=os.environ.get("GITHUB_OUTPUT")
        if output:
            with open(output,"a",encoding="utf-8") as stream:
                stream.write("has_job="+("true" if available else "false")+"\n")
    continuation(False)
    if not os.getenv("KAGGLE_API_TOKEN"):
        raise RuntimeError("KAGGLE_API_TOKEN missing in protected GitHub Actions secrets")
    oidc=github_oidc()
    claim=bridge_request(oidc,"worker_job_claim")
    if not claim.get("ok"):
        raise RuntimeError("Cloud Run rejected authenticated worker claim")
    if not claim.get("has_job"):
        continuation(bool(claim.get("recovery_queued")))
        print("P259_GEMMA4_NO_QUEUED_JOB",flush=True)
        return 0
    job=claim["job"]
    continuation(True)
    jid=job["id"]
    print("P259_GEMMA4_JOB_CLAIMED",jid,job["task_id"],job["langs"],flush=True)
    try:
        if job["task_id"] not in ALLOWED or job.get("stage")!="multi":
            raise RuntimeError("P259_GEMMA4_RELAY_REJECTS_NON_P259_JOB")
        if not job.get("chunked_upload") or not job.get("qa_required"):
            raise RuntimeError("Cloud Run verified per-language QA capability required")
        if any(lang not in LANGUAGES for lang in job.get("langs",[])):
            raise RuntimeError("Unsupported Gemma4 language")
        # Cloud Run has already verified complete source IDs and QA receipts
        # across jobs. Do not start a new 12B GPU kernel when all requested
        # languages are already present for the exact Final revision.
        if set(job["langs"]).issubset(set(job.get("qa_completed_languages",[]))):
            receipt=bridge_request(oidc,"worker_job_report",{
                "job_id":jid,"status":"done"})
            if not receipt.get("ok"):
                raise RuntimeError("Previously approved P259 source not marked done")
            print("GEMMA4_CROSS_JOB_QA_REUSED_NO_GPU",job["task_id"],
                  ",".join(job["langs"]),flush=True)
            return 0
        result=run_kernel(job)
        for language in job["langs"]:
            if language in result.get("failures",{}):
                print("P259_GEMMA4_LANGUAGE_REVIEW_REQUIRED",job["task_id"],language,
                      safe_failure_summary(result["failures"][language],language),flush=True)
        approved=checked_output(job,result)
        for lang,entry in result.get("results",{}).items():
            saved=bridge_request(oidc,"worker_job_part",{
                "job_id":jid,"language":lang,"input_revision":job["revision"],
                "segments":json.dumps(entry["segments"],ensure_ascii=False)})
            if not saved.get("ok"):
                raise RuntimeError("Cloud Run segment upload unverified for "+lang)
            receipt=bridge_request(oidc,"worker_job_quality",{
                "job_id":jid,"language":lang,
                "input_revision":job["revision"],"status":"passed",
                "unresolved":"0","model":QA_COMPAT_MODEL,
                "qa_batches":str(entry["qa_batches"]),
                "repair_count":str(entry["repair_count"])})
            if not receipt.get("qa_passed") and not receipt.get("duplicate"):
                raise RuntimeError("Cloud Run local Gemma4 QA receipt failed for "+lang)
            print("GEMMA4_CENTRAL_QA_VERIFIED",job["task_id"],lang,flush=True)
        if set(job["langs"])!=approved:
            raise RuntimeError("Some languages need review, not marking queue done: "+
                ",".join(sorted(set(job["langs"])-approved)))
        confirmed=bridge_request(oidc,"worker_job_report",{"job_id":jid,"status":"done"})
        if not confirmed.get("ok"):
            raise RuntimeError("Cloud Run did not acknowledge all-language job completion")
        print("GEMMA4_P259_JOB_CENTRALLY_DONE",job["task_id"],len(approved),flush=True)
        return 0
    except Exception as exc:
        print("GEMMA4_P259_RELAY_FAILED",type(exc).__name__,str(exc)[:300],flush=True)
        try:
            bridge_request(oidc,"worker_job_report",{
                "job_id":jid,"status":"error",
                "message":type(exc).__name__+": "+str(exc)[:200]})
        except Exception as update_exc:
            print("GEMMA4_RELAY_ERROR_REPORT_UNCONFIRMED",type(update_exc).__name__,flush=True)
        raise

if __name__=="__main__":
    sys.exit(main())
