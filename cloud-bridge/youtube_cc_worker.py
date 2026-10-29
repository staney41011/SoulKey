#!/usr/bin/env python3
"""GitHub OIDC worker for user-requested public YouTube CC text only.

Preserves original YouTube video ID and never substitutes captions from
another lesson. No video or audio downloads. Uses cookies only if explicitly provided via GitHub Actions secret.
"""
import json
import base64
import os
import re
import sys
import time
import tempfile
from pathlib import Path
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
def bridge(action,fields,_initial_token):
    """Never reuse an expired GitHub OIDC token during slow Kaggle extraction."""
    for attempt in range(2):
        token=oidc_token()
        try:
            return request_json(BASE,{"action":action,**fields},
              headers={"Authorization":"Bearer "+token},timeout=120)
        except HTTPError as error:
            # The bridge intentionally returns a generic error. Log the status
            # and public error code, never print credentials or JWT values.
            detail=""
            try:
                payload=json.loads(error.read(1000))
                detail=str(payload.get("error",""))[:100]
            except Exception:
                pass
            print("SOULKEY_CC_BRIDGE_REJECTED",action,"HTTP",error.code,
                  detail,"attempt",attempt+1,flush=True)
            if error.code!=401 or attempt:raise
    raise RuntimeError("cc_worker_bridge_auth_failed")
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
def temporary_cookiefile(secret,directory):
    """Decode an authorized Netscape cookie export on the ephemeral runner.

    Never print credentials, persist them to GitHub, or pass them to Kaggle.
    """
    raw=str(secret or "").strip()
    if not raw:
        return None
    if raw.startswith("# Netscape HTTP Cookie File") or raw.startswith("# HTTP Cookie File"):
        decoded=raw
    else:
        try:
            decoded=base64.b64decode("".join(raw.split())+"="*(-len("".join(raw.split()))%4),
                validate=True).decode("utf-8-sig")
        except (ValueError,UnicodeError,base64.binascii.Error) as exc:
            raise RuntimeError("YOUTUBE_COOKIES_B64 invalid base64 or cookie format") from None
    entries=[line for line in decoded.splitlines() if line and not line.startswith("# ")]
    if not any(("\tyoutube.com\t" in x or ".youtube.com\t" in x or
                "\tgoogle.com\t" in x or ".google.com\t" in x) for x in entries):
        raise RuntimeError("YOUTUBE_COOKIES_B64 contains no recognizable YouTube cookie entries")
    filename=Path(directory)/"youtube_cookies.txt"
    filename.write_text(decoded,encoding="utf-8")
    filename.chmod(0o600)
    return str(filename)

def fetch_youtube(video_id,languages,cookiefile=None):
    import yt_dlp
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}",video_id):raise RuntimeError("Invalid YouTube video id")
    opts={
      "quiet":True,"no_warnings":True,"skip_download":True,
      "extract_flat":False,"ignoreerrors":False,
      "noplaylist":True,"retries":3,"extractor_retries":3,
      "socket_timeout":40
    }
    if cookiefile:
        opts["cookiefile"]=cookiefile
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
    # Diagnose code/identity drift without disclosing the Bridge Key or JWT.
    try:
        status=request_json(BASE,timeout=20)
        print("CC_BRIDGE_BUILD",str(status.get("build","unknown"))[:50],
              "capabilities",str(status.get("source_capabilities",[]))[:180],
              flush=True)
    except Exception as exc:
        print("CC_BRIDGE_PING_FAILED",type(exc).__name__,flush=True)
    token=oidc_token()
    try:
        claim=json.loads(base64.urlsafe_b64decode(
            token.split(".")[1]+"="*(-len(token.split(".")[1])%4)))
        print("CC_WORKFLOW_IDENTITY",
              str(claim.get("workflow_ref",""))[:140],
              str(claim.get("event_name",""))[:40],flush=True)
    except Exception:print("CC_WORKFLOW_IDENTITY_UNREADABLE",flush=True)
    job_reply=bridge("worker_cc_claim",{},token)
    if not job_reply.get("ok"):raise RuntimeError("CC queue claim failed")
    if not job_reply.get("has_job"):
        print("SOULKEY_CC_NO_PENDING_JOB",flush=True)
        return
    job=job_reply["job"]
    jid=job["id"]
    print("CLAIM_CC",jid,job["task_id"],job["video_id"],flush=True)
    try:
        requested=job.get("languages") or LANGS
        # Prefer the authenticated GitHub path when the owner has explicitly
        # provided an export. The cookie file stays on GitHub's temporary disk.
        # Kaggle never receives browser cookies or the encoded secret.
        cookies=os.environ.get("YOUTUBE_COOKIES_B64","")
        data=None;missing=[]
        if cookies:
            with tempfile.TemporaryDirectory(prefix="soulkey-cc-auth-") as tmp:
                cookiefile=temporary_cookiefile(cookies,tmp)
                print("CC_BACKEND=GITHUB_AUTHENTICATED",flush=True)
                try:
                    data,missing=fetch_youtube(job["video_id"],requested,cookiefile=cookiefile)
                except Exception as error:
                    print("CC_AUTHENTICATED_FETCH_FAILED",
                          type(error).__name__,flush=True)
        if data is None and os.environ.get("KAGGLE_API_TOKEN"):
            from youtube_cc_kaggle_client import capture
            print("CC_BACKEND=KAGGLE_CPU_ANONYMOUS",flush=True)
            try:
                data,missing=capture(job["video_id"],requested)
            except Exception as kaggle_exc:
                print("CC_KAGGLE_FAILED_TRY_GITHUB_CPU",
                      type(kaggle_exc).__name__,flush=True)
                data,missing=fetch_youtube(job["video_id"],requested)
                print("CC_BACKEND=GITHUB_CPU_ANONYMOUS_FALLBACK",flush=True)
        elif data is None:
            print("CC_BACKEND=GITHUB_CPU_ANONYMOUS",flush=True)
            data,missing=fetch_youtube(job["video_id"],requested)
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
