"""Trusted original-video duration for SoulKey Natural TTS.

Read canonical or Chinese-named legacy source metadata. If an authorized
original YouTube URL has no saved metadata, fetch metadata only (no video
download), verify exact YouTube ID, then save canonical source_info.json.
Never infer official duration from English Final timestamps or a preview MP3.
"""
import json
import math
from pathlib import Path
from urllib.parse import parse_qs, urlparse

def video_id(url):
    parsed=urlparse(str(url or "").strip())
    host=(parsed.hostname or "").lower()
    if host in {"youtu.be","www.youtu.be"}:
        ident=parsed.path.strip("/").split("/")[0]
    elif host in {"youtube.com","www.youtube.com","m.youtube.com"}:
        ident=(parse_qs(parsed.query).get("v") or [""])[0]
        if not ident and parsed.path.startswith("/shorts/"):
            ident=parsed.path.split("/")[2]
    else:
        return ""
    return ident if len(ident)==11 and all(c.isalnum() or c in "-_" for c in ident) else ""

def checked_duration(info, expected_id):
    if not isinstance(info, dict) or not expected_id:
        return None
    actual=str(info.get("id") or "").strip()
    source=info.get("source")
    if not actual and isinstance(source,dict):
        actual=str(source.get("id") or "").strip()
    if not actual:
        actual=video_id(info.get("webpage_url") or (
            source.get("webpage_url") if isinstance(source,dict) else ""))
    if actual != expected_id:
        return None
    try:
        duration=float(info.get("duration") or 0)
    except (ValueError, TypeError):
        return None
    if not math.isfinite(duration) or not 1 <= duration <= 86400:
        return None
    return duration

def trusted_video_duration(drive, source_folder, workdir, expected_url):
    """Return (duration, provenance); never mark guessed timestamps official."""
    from google_io import (
        download_drive_file, list_child_files, find_file, upload_or_replace_file
    )
    expected_id=video_id(expected_url)
    if not expected_id:
        print("TTS_SOURCE_DURATION_NO_VALID_VIDEO_ID",flush=True)
        return None,"source_video_id_unavailable"
    workdir=Path(workdir)
    workdir.mkdir(parents=True,exist_ok=True)
    found=list_child_files(drive,source_folder)
    files=[f for f in found if f.get("name")=="source_info.json"
           or str(f.get("name","")).endswith("_來源資訊.json")]
    files.sort(key=lambda f: f.get("name")!="source_info.json")
    for file in files:
        local=workdir/("source_metadata_"+str(file["id"])+".json")
        try:
            download_drive_file(drive,file["id"],local)
            payload=json.loads(local.read_text(encoding="utf-8"))
            duration=checked_duration(payload,expected_id)
        except Exception as exc:
            print("TTS_SOURCE_METADATA_READ_ERROR",type(exc).__name__,flush=True)
            continue
        if duration:
            print("TTS_SOURCE_DURATION_VERIFIED",expected_id,round(duration,2),
                  file["name"],flush=True)
            return duration,("source_info.duration" if file["name"]=="source_info.json"
                             else "legacy_source_info.duration")
        print("TTS_SOURCE_METADATA_ID_OR_DURATION_MISMATCH",file["name"],flush=True)

    # If a source_info.json already exists but conflicts with this YouTube ID,
    # do not overwrite it automatically. A person must resolve the conflict.
    if any(f.get("name")=="source_info.json" for f in files):
        return None,"source_info_conflict"

    try:
        import yt_dlp
        with yt_dlp.YoutubeDL({
            "quiet":True,"no_warnings":True,"skip_download":True,
            "noplaylist":True,"socket_timeout":25,"retries":2,
            "extract_flat":False,
        }) as ydl:
            info=ydl.extract_info(
                "https://www.youtube.com/watch?v="+expected_id,download=False)
        duration=checked_duration(info,expected_id)
    except Exception as exc:
        # Never print the raw YouTube error (it can include URL/cookie data).
        print("TTS_SOURCE_METADATA_FETCH_FAILED",type(exc).__name__,flush=True)
        return None,"youtube_metadata_unavailable"
    if not duration:
        print("TTS_SOURCE_METADATA_UNVERIFIED",expected_id,flush=True)
        return None,"youtube_duration_unverified"

    # Race protection: do not overwrite a file that appeared meanwhile.
    if find_file(drive,source_folder,"source_info.json"):
        return None,"source_info_created_concurrently"
    authoritative={
        "id":expected_id,
        "webpage_url":"https://www.youtube.com/watch?v="+expected_id,
        "duration":duration,
        "title":str(info.get("title") or "")[:500],
        "source_type":"youtube",
        "duration_provenance":"yt_dlp_verified_original_metadata",
    }
    local=workdir/"source_info.json"
    local.write_text(json.dumps(authoritative,ensure_ascii=False,indent=2),
                     encoding="utf-8")
    upload_or_replace_file(drive,source_folder,str(local),
                           drive_name="source_info.json")
    saved=find_file(drive,source_folder,"source_info.json")
    if not saved:
        raise RuntimeError("source_metadata_upload_not_visible")
    roundtrip=workdir/"source_info.verify.json"
    download_drive_file(drive,saved["id"],roundtrip)
    parsed=json.loads(roundtrip.read_text(encoding="utf-8"))
    if checked_duration(parsed,expected_id)!=duration:
        raise RuntimeError("source_metadata_drive_readback_mismatch")
    print("TTS_SOURCE_INFO_CREATED_VERIFIED",expected_id,round(duration,2),
          flush=True)
    return duration,"youtube_verified_source_info.duration"
