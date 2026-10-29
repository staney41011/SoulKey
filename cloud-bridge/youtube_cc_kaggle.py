#!/usr/bin/env python3
"""CPU-only Kaggle entrypoint; captures CC for exactly one canonical video.

Writes machine-readable result to Kaggle output. No Google Drive credentials,
GitHub credentials, Bridge Key or editing permissions are passed to Kaggle.
"""
import json
from pathlib import Path
from youtube_cc_worker import fetch_youtube,LANGS

def main():
    job=json.loads(Path("cc_job.json").read_text(encoding="utf-8"))
    video=str(job["video_id"])
    langs=list(job.get("languages") or LANGS)
    if not langs or any(x not in LANGS for x in langs):
        raise ValueError("invalid_languages")
    captured,missing=fetch_youtube(video,langs)
    if not captured:
        raise RuntimeError("youtube_caption_tracks_unavailable")
    report={
        "video_id":video,
        "captions":{lang:{"text":value[0],"source":value[1]}
                    for lang,value in captured.items()},
        "missing_languages":missing
    }
    dest=Path("/kaggle/working/cc_capture_result.json")
    dest.write_text(json.dumps(report,ensure_ascii=False),encoding="utf-8")
    print("CAPTURED_SOURCE_ID",video,"CAPTION_LANGUAGES",list(captured),
          "UNAVAILABLE",missing,flush=True)
if __name__=="__main__":
    main()
