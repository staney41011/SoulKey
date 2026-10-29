#!/usr/bin/env python3
"""SoulKey authenticated GitHub CPU multi-language translator.

No Bridge Key or Google OAuth user credentials are needed in GitHub Actions.
This workflow presents GitHub's short-lived OIDC identity to Cloud Run; the
Cloud Run service reads and writes the existing Google Sheet on its own.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from urllib.error import HTTPError, URLError

BASE=os.environ.get("SOULKEY_BRIDGE_URL","https://soulkey-bridge-214901732194.asia-east1.run.app").rstrip("/")
AUDIENCE="soulkey-bridge-translation-worker-v1"
GEMINI=os.environ.get("GEMINI_API_KEY","").strip()
_NLLB_RUNNER=None
MODEL=os.environ.get("SOULKEY_GEMINI_MODEL","gemini-3.5-flash-lite").strip()
LANGS={
 "th":"Thai","es":"Spanish","id":"Indonesian","vi":"Vietnamese",
 "km":"Khmer","hi":"Hindi","ta":"Tamil","ja":"Japanese",
 "ko":"Korean","bn":"Bengali","ne":"Nepali","lo":"Lao",
 "my":"Burmese","it":"Italian","pt":"Brazilian Portuguese"
}
def json_http(url,payload=None,headers=None,timeout=90):
    h={"Accept":"application/json"}
    if headers:h.update(headers)
    if payload is None:
        req=urllib.request.Request(url,headers=h)
    else:
        data=json.dumps(payload,ensure_ascii=False).encode("utf-8")
        h["Content-Type"]="application/json"
        req=urllib.request.Request(url,data=data,headers=h,method="POST")
    with urllib.request.urlopen(req,timeout=timeout) as response:
        raw=response.read().decode("utf-8")
        return json.loads(raw)

def github_oidc():
    url=os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL","").strip()
    auth=os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN","").strip()
    if not url or not auth:
        raise RuntimeError("GitHub OIDC token permission unavailable")
    target=url+("&" if "?" in url else "?")+urllib.parse.urlencode({"audience":AUDIENCE})
    reply=json_http(target,headers={"Authorization":"Bearer "+auth})
    token=reply.get("value","")
    if not token:raise RuntimeError("GitHub OIDC token response was empty")
    return token

def bridge_request(_initial_token,action,body=None):
    """Obtain a fresh GitHub OIDC JWT for every server operation.

    GitHub's OIDC JWT is short lived. A single five-language CPU job can
    take far longer than its lifetime; reusing the initial token makes
    result upload and even failure reporting return HTTP 401.
    """
    data=urllib.parse.urlencode({"action":action,**(body or {})}).encode("utf-8")
    def send():
        token=github_oidc()
        req=urllib.request.Request(BASE,method="POST",data=data,
          headers={"Authorization":"Bearer "+token,
                   "Content-Type":"application/x-www-form-urlencoded",
                   "Accept":"application/json"})
        with urllib.request.urlopen(req,timeout=130) as response:
            return json.loads(response.read().decode("utf-8"))
    try:
        return send()
    except HTTPError as error:
        if error.code!=401:
            raise
        # One fresh-token retry, not an unbounded authorization loop.
        return send()

def gemini(messages,schema=None):
    if not GEMINI:raise RuntimeError("GEMINI_API_KEY repository secret is missing")
    url="https://generativelanguage.googleapis.com/v1beta/models/"+MODEL+":generateContent"
    config={"responseMimeType":"application/json","maxOutputTokens":14000}
    if schema is not None:
        config["responseJsonSchema"]=schema
    payload={"contents":[{"role":"user","parts":[{"text":messages}]}],
      "generationConfig":config}
    last=None
    for attempt in range(5):
        try:
            r=json_http(url,payload,{"x-goog-api-key":GEMINI},timeout=170)
            parts=r["candidates"][0]["content"]["parts"]
            text="".join(x.get("text","") for x in parts)
            if not text:raise RuntimeError("Gemini produced no text")
            return json.loads(text)
        except HTTPError as exc:
            last=RuntimeError("Gemini HTTP "+str(exc.code))
            if exc.code not in (429,500,502,503,504):break
        except (KeyError,ValueError,RuntimeError,URLError) as exc:
            last=exc
        if attempt<4:time.sleep(min(45,5*(2**attempt)))
    raise RuntimeError("Gemini translation failed: "+str(last)[:160])

def translate(language,segments,glossary=""):
    global _NLLB_RUNNER
    if not GEMINI:
        if _NLLB_RUNNER is None:
            from nllb_cpu import NllbCPU
            _NLLB_RUNNER=NllbCPU()
        return _NLLB_RUNNER.translate(language,segments)
    name=LANGS[language]
    all_rows=[]
    for start in range(0,len(segments),8):
        chunk=segments[start:start+8]
        prompt=(
          "Translate each item from an English manually reviewed spiritual lecture "
          "into natural, accurate "+name+". Keep all meaning, terminology, names "
          "and tone. Do not summarize, merge, omit, or introduce content. "
          "Return only JSON object with array 'segments', each with the identical "
          "integer 'id' and its translated 'text'. Exactly one translated "
          "item per source item. Preserve segment IDs and order. "
          "If a spiritual or religious term is ambiguous, translate conservatively. "
          "Respect the following source-grounded glossary and any LOCKED target "
          "terms. Do not invent translations when glossary targets are blank.\n"
          "GLOSSARY:\n"+str(glossary)[:12000]+"\n\n"+
          json.dumps({"segments":[{"id":x["id"],"text":x["text"]} for x in chunk]},
                     ensure_ascii=False)
        )
        schema={"type":"object","properties":{"segments":{"type":"array","items":{
          "type":"object","properties":{"id":{"type":"integer"},
            "text":{"type":"string"}},"required":["id","text"]}}},"required":["segments"]}
        data=gemini(prompt,schema)
        rows=data.get("segments") if isinstance(data,dict) else data
        if not isinstance(rows,list) or len(rows)!=len(chunk):
            raise RuntimeError("Translated segment count mismatch for "+language)
        mapping={}
        for item in rows:
            if not isinstance(item,dict):raise RuntimeError("Invalid item")
            sid=int(item.get("id",-1))
            txt=str(item.get("text","")).strip()
            if sid in mapping or not txt or len(txt)>16000:
                raise RuntimeError("Invalid or duplicate translation for "+language)
            mapping[sid]=txt
        if set(mapping)!=set(x["id"] for x in chunk):
            raise RuntimeError("Translation IDs do not match source for "+language)
        all_rows.extend({"id":x["id"],"text":mapping[x["id"]]} for x in chunk)
        print("Translated",language,len(all_rows),"/",len(segments),flush=True)
    return all_rows

def main():
    token=github_oidc()
    claimed=bridge_request(token,"worker_job_claim")
    if not claimed.get("ok"):raise RuntimeError("Could not claim queue task")
    if not claimed.get("has_job"):
        print("SoulKey translation queue: no work pending",flush=True)
        return
    job=claimed["job"]
    jid=job["id"]; print("CLAIMED JOB",jid,job["task_id"],job["langs"],flush=True)
    try:
        if job.get("stage")!="multi":raise RuntimeError("Unsupported stage")
        segments=job.get("segments") or []
        if not segments or len(segments)>2000:raise RuntimeError("Invalid input manuscript")
        languages=job.get("langs") or []
        if not languages or any(x not in LANGS for x in languages):
            raise RuntimeError("Invalid language list")
        glossary=str(job.get("glossary") or "")
        from gemini_quality import audit_and_repair
        if job.get("chunked_upload"):
            # QA BEFORE publication: failed or unrepairable translations never
            # enter the central output table as completed content.
            for code in languages:
                translated=translate(code,segments,glossary)
                if GEMINI:
                    translated,quality=audit_and_repair(
                        segments,translated,code,gemini,glossary=glossary)
                    print("GEMINI_QA_PASSED",code,quality["qa_batches"],
                          "repair_count",quality["repairs"],flush=True)
                elif job.get("qa_required"):
                    raise RuntimeError("Gemini required for production QA")
                for start in range(0,len(translated),8):
                    result=bridge_request(token,"worker_job_part",{
                     "job_id":jid,"language":code,
                     "input_revision":job["revision"],
                     "segments":json.dumps(translated[start:start+8],ensure_ascii=False)
                    })
                    if not result.get("ok"):
                        raise RuntimeError("Chunk readback not verified for "+code)
                print("SAVED_VERIFIED_CHUNKS",code,len(translated),flush=True)
                if job.get("qa_required"):
                    receipt=bridge_request(token,"worker_job_quality",{
                        "job_id":jid,"language":code,
                        "input_revision":job["revision"],"status":"passed",
                        "unresolved":"0","model":MODEL,
                        "qa_batches":str(quality["qa_batches"]),
                        "repair_count":str(quality["repairs"])
                    })
                    if not receipt.get("qa_passed"):
                        raise RuntimeError("Central Gemini QA receipt not verified")
            result=bridge_request(token,"worker_job_report",{
             "job_id":jid,"status":"done"
            })
        else:
            # Compatibility with the currently deployed pre-chunk Cloud Run.
            translated={}
            for code in languages:
                rows=translate(code,segments,glossary)
                if GEMINI:
                    rows,quality=audit_and_repair(
                        segments,rows,code,gemini,glossary=glossary)
                    print("GEMINI_QA_PASSED",code,quality["qa_batches"],flush=True)
                translated[code]=rows
            result=bridge_request(token,"worker_job_report",{
             "job_id":jid,"status":"done",
             "translations":json.dumps(translated,ensure_ascii=False)
            })
        if not result.get("ok"):
            raise RuntimeError("Bridge did not confirm translation readback")
        print("VERIFIED",jid,result.get("language_count"),
              result.get("segment_count"),flush=True)
    except Exception as error:
        print("ERROR",type(error).__name__,str(error)[:240],flush=True)
        try:
            bridge_request(token,"worker_job_report",{
             "job_id":jid,"status":"error",
             "message":type(error).__name__+": "+str(error)[:230]
            })
        except Exception as feedback:
            print("FAILED TO REPORT",type(feedback).__name__,flush=True)
        raise

if __name__=="__main__":
    main()
