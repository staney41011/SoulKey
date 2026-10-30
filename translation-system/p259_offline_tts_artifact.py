#!/usr/bin/env python3
"""Render non-destructive P259 audio PREVIEWS from source-revision-checked manuscripts.

Input comes from current human-finalized English and current-revision QA-passed
Google Sheet rows, copied into the PRIVATE repo by the authorized user workflow.
No Google OAuth, Kaggle GPU, Gemini or hidden keys are required. Previews are
never mislabeled as formally published Drive MP3s.
"""
import argparse,json,shutil,sys,traceback
from pathlib import Path

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--lesson",required=True,choices=[f"P259-L{x:02d}" for x in range(1,5)])
    ap.add_argument("--input",default=str(Path(__file__).with_name("p259_approved_audio_source.json")))
    ap.add_argument("--output",default="/tmp/p259-natural-preview")
    args=ap.parse_args()
    from tts_runner import render_natural_language
    from natural_tts_config import NATURAL_TTS_PROFILES
    p=json.loads(Path(args.input).read_text(encoding="utf-8"))
    if p.get("period")!=259:raise ValueError("input_not_P259")
    targets=[x for x in p["tasks"] if x["task_id"]==args.lesson]
    if not targets:raise ValueError("lesson_missing_from_approved_input")
    dest=Path(args.output)/args.lesson
    dest.mkdir(parents=True,exist_ok=True)
    report={"lesson":args.lesson,"outputs":{},"failures":{},"source":p["source"],
            "publication_status":"preview_only_not_verified_drive_final"}
    for row in targets:
        lang=row["lang"]
        try:
            if lang not in NATURAL_TTS_PROFILES:raise ValueError("unsupported_audio_voice")
            src=row["segments"]
            if len(src)<1 or len({int(x["id"]) for x in src})!=len(src):
                raise ValueError("missing_or_duplicate_segment_ids")
            if any(not str(x["text"]).strip() for x in src):
                raise ValueError("empty_speech_segment")
            source_duration=max(float(x["end"]) for x in src)
            if source_duration<=0:raise ValueError("source_timeline_missing")
            work=dest/lang
            work.mkdir(parents=True,exist_ok=True)
            result=render_natural_language(src,lang,work,
               source_duration=source_duration,
               duration_limit_basis="human_english_final_timeline_unverified_video_duration",
               checkpoint_store=None,smart_fit_pilot=False)
            which=Path(result["preview_mp3"] if result["status"]=="needs_review" else result["mp3"])
            if not which.is_file() or which.stat().st_size<1024:
                raise RuntimeError("tts_mp3_missing_or_empty")
            final=dest/f"{args.lesson}_{lang}_PREVIEW.mp3"
            shutil.copyfile(which,final)
            shutil.copyfile(result["manifest"],dest/f"{args.lesson}_{lang}_preview_manifest.json")
            report["outputs"][lang]={"file":final.name,"size":final.stat().st_size,
                     "engine_result":result["status"],
                     "translation_job":row["job_id"],
                     "english_revision":row["revision"],
                     "official_drive_status":"NOT_VERIFIED_PREVIEW_ONLY"}
            print("P259_PREVIEW_RENDERED",args.lesson,lang,final.stat().st_size,flush=True)
        except Exception as e:
            report["failures"][lang]=type(e).__name__+": "+str(e)[:300]
            print("P259_PREVIEW_FAILED",args.lesson,lang,type(e).__name__,
                  str(e)[:240],flush=True)
        finally:
            (dest/"preview_receipts.json").write_text(
                json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print("P259_PREVIEW_FINISHED",args.lesson,len(report["outputs"]),
          "successful",len(report["failures"]),"failed",flush=True)
    if report["failures"]:raise SystemExit(2)

if __name__=="__main__":main()
