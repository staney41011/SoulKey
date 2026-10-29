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
MODEL=os.environ.get("SOULKEY_GEMINI_MODEL","gemini-2.5-flash").strip()
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

def bridge_request(token,action,body=None):
    data=urllib.parse.urlencode({"action":action,**(body or {})}).encode("utf-8")
    req=urllib.request.Request(BASE,method="POST",data=data,
      headers={"Authorization":"Bearer "+token,
               "Content-Type":"application/x-www-form-urlencoded",
               "Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=130) as response:
        return json.loads(response.read().decode("utf-8"))

def gemini(messages):
    if not GEMINI:raise RuntimeError("GEMINI_API_KEY repository secret is missing")
    url="https://generativelanguage.googleapis.com/v1beta/models/"+MODEL+":generateContent"
    payload={
     "contents":[{"role":"user","parts":[{"text":messages}]}],
     "generationConfig":{"temperature":0.2,"responseMimeType":"application/json",
       "maxOutputTokens":14000}
    }
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

def translate(language,segments):
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
          "If a spiritual or religious term is ambiguous, translate conservatively.\n\n"+
          json.dumps({"segments":[{"id":x["id"],"text":x["text"]} for x in chunk]},
                     ensure_ascii=False)
        )
        data=gemini(prompt)
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
        if job.get("chunked_upload"):
            # Keep each upload well below the Cloud Run 1 MB request limit.
            for code in languages:
                translated=translate(code,segments)
                for start in range(0,len(translated),8):
                    result=bridge_request(token,"worker_job_part",{
                     "job_id":jid,"language":code,
                     "input_revision":job["revision"],
                     "segments":json.dumps(translated[start:start+8],ensure_ascii=False)
                    })
                    if not result.get("ok"):
                        raise RuntimeError("Chunk readback not verified for "+code)
                print("SAVED_VERIFIED_CHUNKS",code,len(translated),flush=True)
            result=bridge_request(token,"worker_job_report",{
             "job_id":jid,"status":"done"
            })
        else:
            # Compatibility with the currently deployed pre-chunk Cloud Run.
            translated={code:translate(code,segments) for code in languages}
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
