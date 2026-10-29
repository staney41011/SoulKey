#!/usr/bin/env python3
"""GitHub OIDC worker for user-requested public YouTube CC text only.

Preserves original YouTube video ID and never substitutes captions from
another lesson. No video or audio downloads. Does not require user cookies.
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from urllib.error import HTTPError

BASE=os.environ.get("SOULKEY_BRIDGE_URL","https://soulkey-bridge-214901732194.asia-east1.run.app").rstrip("/")
AUDIENCE="soulkey-bridge-translation-worker-v1"
LANGS=("en","th","es","id","vi","sd","ta")
def request_json(url,payload=None,headers=None,timeout=90):
    headers={"Accept":"application/json",**(headers or {})}
    data=None
    if payload is not None:
        data=urllib.parse.urlencode(payload).encode("utf-8")
        headers["Content-Type"]="application/x-www-form-urlencoded"
    req=urllib.request.Request(url,data=data,headers=headers,
       method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req,timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))
def oidc_token():
    u=os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL")
    key=os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN")
    if not u or not key:raise RuntimeError("GitHub OIDC permission not available")
    sep="&" if "?" in u else "?"
    resp=request_json(u+sep+urllib.parse.urlencode({"audience":AUDIENCE}),
                      headers={"Authorization":"Bearer "+key})
    if not resp.get("value"):raise RuntimeError("GitHub OIDC token missing")
    return resp["value"]
def bridge(action,fields,token):
    return request_json(BASE,{"action":action,**fields},
      headers={"Authorization":"Bearer "+token},timeout=120)
def strip_vtt(body):
    """Return pure subtitle text without mixing source languages."""
    if not isinstance(body,str):raise RuntimeError("Invalid caption text")
    lines=[];seen=""
    for line in body.replace("\r","").split("\n"):
        line=line.strip()
        if not line or line.startswith(("WEBVTT","NOTE ","STYLE","REGION","Kind:","Language:")):
            continue
        if "-->" in line or re.fullmatch(r"\d+",line):continue
        if re.match(r"^(?:align|position|size|line):",line):continue
        line=re.sub(r"<[^>]+>","",line)
        line=line.replace("&amp;","&").replace("&lt;","<").replace("&gt;",">")
        line=re.sub(r"\{\\an\d+\}","",line).strip()
        if not line or line==seen:continue
        lines.append(line);seen=line
    text="\n".join(lines).strip()
    if not text:raise RuntimeError("No readable caption content")
    return text
def find_tracks(info,language):
    # YouTube auto-translations are allowed only when the target language
    # exists in metadata. Do not fabricate missing subtitles.
    manual=info.get("subtitles") or {}
    auto=info.get("automatic_captions") or {}
    keys=[language]
    keys+=sorted(k for k in set(manual)|set(auto)
                 if k.startswith(language+"-"))
    for sources,origin in ((manual,"manual"),(auto,"automatic")):
        for k in keys:
            options=sources.get(k) or []
            choices=[x for x in options if isinstance(x,dict)
                     and x.get("url") and x.get("ext") in ("vtt","ttml","srv3")]
            if choices:return choices[0]["url"],origin,k
    return None
def pull_caption(url,ytdlp,tries=4):
    for attempt in range(tries):
        try:
            resp=ytdlp.urlopen(url)
            content=resp.read()
            if len(content)>650000:raise RuntimeError("Caption too large")
            return content.decode("utf-8-sig","replace")
        except Exception as error:
            if attempt+1==tries:raise
            print("CAPTION_RETRY",attempt+1,type(error).__name__,flush=True)
            time.sleep(min(35,4*(2**attempt)))
def fetch_youtube(video_id,languages):
    import yt_dlp
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}",video_id):raise RuntimeError("Invalid YouTube video id")
    opts={
      "quiet":True,"no_warnings":True,"skip_download":True,
      "extract_flat":False,"ignoreerrors":False,
      "noplaylist":True,"retries":3,"extractor_retries":3,
      "socket_timeout":40
    }
    with yt_dlp.YoutubeDL(opts) as yt:
        info=yt.extract_info("https://www.youtube.com/watch?v="+video_id,download=False)
        if not isinstance(info,dict) or str(info.get("id"))!=video_id:
            raise RuntimeError("YouTube returned a different video")
        captions={}
        missing=[]
        for lang in languages:
            source=find_tracks(info,lang)
            if not source:
                missing.append(lang)
                continue
            url,origin,actual_lang=source
            body=pull_caption(url,yt)
            clean=strip_vtt(body)
            captions[lang]=(clean,origin+":"+actual_lang)
        return captions,missing
def parts(text,size=17000):
    for i in range(0,len(text),size):
        end=min(i+size,len(text))
        if end<len(text) and 0xD800<=ord(text[end-1])<=0xDBFF:
            end-=1
        yield text[i:end]
def main():
    token=oidc_token()
    job_reply=bridge("worker_cc_claim",{},token)
    if not job_reply.get("ok"):raise RuntimeError("CC queue claim failed")
    if not job_reply.get("has_job"):
        print("SOULKEY_CC_NO_PENDING_JOB",flush=True)
        return
    job=job_reply["job"]
    jid=job["id"]
    print("CLAIM_CC",jid,job["task_id"],job["video_id"],flush=True)
    try:
        data,missing=fetch_youtube(job["video_id"],job.get("languages") or LANGS)
        if not data:
            raise RuntimeError("YouTube did not expose any of the seven requested CC languages")
        complete=[]
        for lang,(caption,source) in data.items():
            chunks=list(parts(caption))
            for i,chunk in enumerate(chunks):
                answer=bridge("worker_cc_part",{
                  "job_id":jid,"language":lang,"part_index":str(i),
                  "part_count":str(len(chunks)),"source":source,"content":chunk
                },token)
                if not answer.get("ok"):raise RuntimeError("CC part was not saved")
            complete.append(lang)
            print("CAPTURED_CC",lang,len(caption),flush=True)
        answer=bridge("worker_cc_finish",{
          "job_id":jid,"status":"done","languages":",".join(complete)
        },token)
        if not answer.get("ok"):raise RuntimeError("CC finish not verified")
        print("CC_DONE",job["task_id"],complete,"NOT_AVAILABLE",missing,flush=True)
    except Exception as error:
        print("CC_FAILED",type(error).__name__,str(error)[:250],flush=True)
        try:
            bridge("worker_cc_finish",{
              "job_id":jid,"status":"error",
              "message":type(error).__name__+": "+str(error)[:240]
            },token)
        except Exception as fallback:
            print("CC_REPORT_FAILED",type(fallback).__name__,flush=True)
        raise
if __name__=="__main__":
    main()
