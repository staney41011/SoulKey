"""Authoritative SoulKey video-duration evidence; subtitle ends are never video lengths.

Source_info.json from the matched source video is the primary record.
Verified source-video records may fill a missing metadata file; English CC
timestamps and translated text are never permitted as hard video limits.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def youtube_video_id(url):
    parsed = urlparse(str(url or "").strip())
    host = (parsed.hostname or "").lower()
    ident = ""
    if host in ("youtu.be", "www.youtu.be"):
        ident = parsed.path.strip("/").split("/")[0]
    elif host in ("youtube.com", "www.youtube.com", "m.youtube.com"):
        if parsed.path.rstrip("/") == "/watch":
            ident = (parse_qs(parsed.query).get("v") or [""])[0]
        elif parsed.path.startswith(("/shorts/", "/live/", "/embed/")):
            ident = parsed.path.split("/")[2]
    return ident if re.fullmatch(r"[A-Za-z0-9_-]{11}", ident) else ""


def verified_original_duration(youtube_url, source_info=None, registry_path=None):
    """Return (video seconds, evidence label), or (None, missing label).

    Reject source_info for the wrong video; this avoids silently applying an
    earlier lesson's duration. A known verified per-video record is acceptable
    when YouTube metadata could not originally be saved to Google Drive.
    """
    video_id = youtube_video_id(youtube_url)
    if not video_id:
        return None, "missing_youtube_video_id"
    payload = source_info or {}
    if not isinstance(payload, dict):
        raise ValueError("Source metadata must be a JSON object")
    embedded = payload.get("source") or {}
    if not isinstance(embedded, dict):
        embedded = {}
    source_id = str(payload.get("id") or embedded.get("id") or "").strip()
    if source_id and source_id != video_id:
        raise ValueError("Original video ID does not match lesson YouTube URL")
    source_url = str(payload.get("webpage_url") or embedded.get("webpage_url") or "").strip()
    if source_url and youtube_video_id(source_url) not in ("", video_id):
        raise ValueError("Original video source URL does not match lesson")
    try:
        duration = float(payload.get("duration") or embedded.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0
    if math.isfinite(duration) and duration >= 60:
        return duration, "original_video_source_info"
    path = Path(registry_path) if registry_path else Path(__file__).with_name("verified_video_durations.json")
    if path.is_file():
        entries = json.loads(path.read_text(encoding="utf-8"))
        record = entries.get(video_id) or {}
        try:
            duration = float(record.get("duration_seconds") or 0)
        except (TypeError, ValueError):
            duration = 0
        if math.isfinite(duration) and duration >= 60:
            return duration, "verified_original_video_registry"
    return None, "missing_verified_original_video_duration"
