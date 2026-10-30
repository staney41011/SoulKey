#!/usr/bin/env python3
"""Recover missing P259-L04 source_info.json from the exact registered YouTube ID.

Never overwrite a valid existing source_info.json, invent a video duration or
mark a lesson formally time-verified from English timestamps alone.
"""
import json
import re
import sys
import tempfile
from datetime import datetime,timezone
from pathlib import Path

from config import SPREADSHEET_ID,TASK_SHEET_RANGE
from google_io import (
    build_google_services,read_values,find_file,download_drive_file,
    upload_or_replace_file
)
from lesson_paths import resolve_lesson_folders

TARGET="P259-L04"

def source_video_id(url):
    match=re.search(r"(?:youtu\\.be/|[?&]v=)([A-Za-z0-9_-]{11})",str(url))
    return match.group(1) if match else ""

def run():
    drive,sheets=build_google_services()
    tasks=read_values(sheets,SPREADSHEET_ID,TASK_SHEET_RANGE)
    rows=[r for r in tasks if len(r)>4 and r[0]==TARGET]
    if len(rows)!=1:raise RuntimeError("P259-L04 central source task not unique")
    url=rows[0][4]
    video_id=source_video_id(url)
    if not video_id:raise RuntimeError("P259-L04 source YouTube video id missing")
    folder=resolve_lesson_folders(drive,sheets,259,rows[0][2])["source"]
    with tempfile.TemporaryDirectory(prefix="p259-l04-duration-") as work:
        base=Path(work)
        prior=find_file(drive,folder,"source_info.json")
        if prior:
            existing=base/"existing.json"
            download_drive_file(drive,prior["id"],existing)
            data=json.loads(existing.read_text(encoding="utf-8"))
            old_url=str(data.get("youtube_url") or data.get("url") or "")
            old_id=str(data.get("youtube_video_id") or data.get("video_id") or "")
            old_id=old_id or source_video_id(old_url)
            if old_id and old_id!=video_id:
                raise RuntimeError("existing_source_metadata_different_video")
            if 0<float(data.get("duration") or 0)<24*60*60:
                print("P259_L04_SOURCE_DURATION_ALREADY_VERIFIED",flush=True)
                return
            raise RuntimeError("existing_source_metadata_without_valid_duration_recheck_manually")
        import yt_dlp
        opts={"quiet":True,"skip_download":True,"no_warnings":True,
              "extract_flat":False,"noplaylist":True,"socket_timeout":30}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info=ydl.extract_info("https://www.youtube.com/watch?v="+video_id,download=False)
        if str(info.get("id") or "")!=video_id:
            raise RuntimeError("yt_dlp_video_identity_does_not_match_central_task")
        duration=float(info.get("duration") or 0)
        if not (60<=duration<24*60*60):
            raise RuntimeError("yt_dlp_did_not_verify_original_video_duration")
        payload={"task_id":TARGET,"youtube_url":url,"youtube_video_id":video_id,
                 "duration":duration,"duration_source":"yt_dlp_verified_youtube_metadata",
                 "verified_at":datetime.now(timezone.utc).isoformat()}
        src=base/"source_info.json"
        src.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
        uploaded=upload_or_replace_file(drive,folder,src,"source_info.json")
        obj=find_file(drive,folder,"source_info.json")
        if not obj or obj["id"]!=uploaded["id"]:
            raise RuntimeError("source_info_drive_upload_readback_missing")
        readback=base/"readback.json"
        download_drive_file(drive,obj["id"],readback)
        check=json.loads(readback.read_text(encoding="utf-8"))
        if check.get("youtube_video_id")!=video_id or float(check.get("duration") or 0)!=duration:
            raise RuntimeError("source_info_drive_readback_duration_mismatch")
        print("P259_L04_SOURCE_DURATION_DRIVE_VERIFIED",video_id,duration,flush=True)

if __name__=="__main__":
    run()
