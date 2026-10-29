#!/usr/bin/env python3
"""CPU-only Kaggle entrypoint; captures CC for exactly one canonical video.

Writes machine-readable result to Kaggle output. No Google Drive credentials,
GitHub credentials, Bridge Key or editing permissions are passed to Kaggle.
"""
import json
import re
import time
import subprocess
import sys
from pathlib import Path
# Kaggle runs only the declared code_file as /kaggle/src/script.py.
# Copy the extractor implementation in this file; local helper imports vanish.
LANGS=("en","th","es","id","vi","sd","ta")

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
def blocked_by_youtube(error):
    message=str(error).lower()
    return ("429" in message or "too many requests" in message or
        "confirm you" in message and "bot" in message)

def pull_caption(url,ytdlp,tries=2):
    for attempt in range(tries):
        try:
            resp=ytdlp.urlopen(url)
            content=resp.read(650001)
            if len(content)>650000:raise RuntimeError("Caption too large")
            return content.decode("utf-8-sig","replace")
        except Exception as error:
            # Stop immediately on YouTube throttling; retries on the same
            # egress IP aggravate a 429 response.
            if blocked_by_youtube(error) or attempt+1==tries:raise
            print("CAPTION_RETRY",attempt+1,type(error).__name__,flush=True)
            time.sleep(4*(attempt+1))
def fetch_youtube(video_id,languages,cookiefile=None,on_caption=None):
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
        ordered=list(dict.fromkeys(sorted(languages,key=lambda l:(l!="en",l))))
        for pos,lang in enumerate(ordered):
            source=find_tracks(info,lang)
            if not source:
                missing.append(lang)
                continue
            url,origin,actual_lang=source
            try:
                body=pull_caption(url,yt)
                clean=strip_vtt(body)
            except Exception as exc:
                missing.append(lang)
                if blocked_by_youtube(exc):
                    print("CC_YOUTUBE_RATE_LIMITED_STOP",lang,flush=True)
                    missing.extend(ordered[pos+1:])
                    break
                print("CC_LANGUAGE_UNAVAILABLE",lang,type(exc).__name__,flush=True)
                continue
            label=origin+":"+actual_lang
            captions[lang]=(clean,label)
            if on_caption:on_caption(lang,clean,label)
            print("CC_CAPTURED_VERIFIED_SOURCE",lang,len(clean),flush=True)
        return captions,missing


def main():
    job=globals().get("JOB_PAYLOAD")
    if not isinstance(job,dict):
        raise RuntimeError("kaggle_embedded_cc_job_missing")
    video=str(job["video_id"])
    langs=list(job.get("languages") or LANGS)
    if not langs or any(x not in LANGS for x in langs):
        raise ValueError("invalid_languages")
    subprocess.run([sys.executable,"-m","pip","install","-q","yt-dlp"],
                   check=True,timeout=240)
    # Update Kaggle's output as soon as English arrives. This output
    # remains available if a later language is rate-limited.
    captured={}
    dest=Path("/kaggle/working/cc_capture_result.json")
    def checkpoint(lang,caption,source):
        captured[lang]=(caption,source)
        report={"video_id":video,
                "captions":{code:{"text":text,"source":origin}
                    for code,(text,origin) in captured.items()},
                "missing_languages":[x for x in langs if x not in captured]}
        dest.write_text(json.dumps(report,ensure_ascii=False),encoding="utf-8")
        print("KAGGLE_CC_CHECKPOINT",lang,len(caption),flush=True)
    result,missing=fetch_youtube(video,langs,on_caption=checkpoint)
    if not captured:
        raise RuntimeError("youtube_caption_tracks_unavailable")
    print("CAPTURED_SOURCE_ID",video,"CAPTION_LANGUAGES",list(captured),
          "UNAVAILABLE",missing,flush=True)
if __name__=="__main__":
    main()
