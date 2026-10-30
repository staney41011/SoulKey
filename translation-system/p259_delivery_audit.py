#!/usr/bin/env python3
"""Read-only P259 acceptance audit: 4 x 16 verified manuscript and MP3 units.

Counts only matching English source revision, complete current QA, all three
Drive manuscript files with byte-equivalent content, and MD5-verified Natural
TTS final MP3/WAV + manifest matching original video duration.
"""
import json,os,sys,tempfile
from datetime import datetime,timezone
from pathlib import Path
from config import SPREADSHEET_ID
from google_io import build_google_services,read_values,find_file,download_drive_file
from central_tts_source import verified_english_final,verified_translation,SourceNotReady
from central_manuscript_export import manuscript_files,_same_existing
from central_tts_recovery import ready_tasks,approved_plan_rows
from lesson_paths import resolve_lesson_folders
from tts_fingerprint import segments_fingerprint
from tts_runner import verify_uploaded_natural_output,load_source_duration_limit

def read_matches(drive,folder,expected,work):
    for name,blob in expected.items():
        item=find_file(drive,folder,name)
        if not item:return False,"missing_"+name
        p=work/name
        download_drive_file(drive,item["id"],p)
        if not _same_existing(name,p.read_bytes(),blob):
            return False,"content_or_revision_conflict_"+name
    return True,"all_three_verified"

def run():
    drive,sheets=build_google_services()
    get=lambda key:read_values(sheets,SPREADSHEET_ID,key)
    index=get("英文定稿索引!A2:F10000")
    backups=get("英文定稿備存!A2:G10000")
    transcripts=get("多語翻譯結果!A2:G50000")
    qa=get("翻譯QA紀錄!A2:I5000")
    plans=get("語言任務設定!A2:J5000")
    report={"period":259,"checked_at":datetime.now(timezone.utc).isoformat(),
            "target":64,"lessons":{},"current_revision_qa_total":0,
            "drive_manuscript_total":0,"drive_formal_audio_total":0}
    with tempfile.TemporaryDirectory(prefix="p259-audit-") as root:
        for task in ready_tasks(sheets,259,None):
            tid=task["task_id"]
            if tid not in {f"P259-L{x:02d}" for x in range(1,5)}:continue
            result={"languages":{},"approved_sources":0,
                    "drive_manuscripts":0,"drive_formal_audio":0}
            report["lessons"][tid]=result
            try:
                final=verified_english_final(tid,index,backups)
                folder=resolve_lesson_folders(drive,sheets,259,task["lesson"])
                source=Path(root)/tid/"original"
                source.mkdir(parents=True,exist_ok=True)
                duration,basis=load_source_duration_limit(drive,folder["source"],source)
                result["source_revision"]=final["revision"]
                result["video_duration_source"]=basis
                selected=approved_plan_rows(plans,tid)
                if len(selected)!=16 or len(set(selected))!=16 or "en" not in selected:
                    raise RuntimeError("language_plan_not_exactly_16")
                for lang in selected:
                    detail={"qa":False,"manuscripts":False,"formal_mp3":False}
                    result["languages"][lang]=detail
                    try:
                        approved=verified_translation(tid,lang,final,transcripts,qa)
                    except SourceNotReady as e:
                        detail["reason"]=str(e);continue
                    detail["qa"]=True
                    result["approved_sources"]+=1
                    report["current_revision_qa_total"]+=1
                    work=Path(root)/tid/lang
                    work.mkdir(parents=True,exist_ok=True)
                    try:
                        expected=manuscript_files(tid,lang,final,approved)
                        valid,why=read_matches(drive,folder["translation"],expected,work)
                        detail["manuscripts"]=valid
                        if valid:
                            result["drive_manuscripts"]+=1
                            report["drive_manuscript_total"]+=1
                        else:detail["manuscript_issue"]=why
                    except Exception as exc:
                        detail["manuscript_issue"]=type(exc).__name__
                    if duration is None:
                        detail["audio_issue"]="original_video_duration_not_verified"
                        continue
                    try:
                        sha=segments_fingerprint(approved["segments"])
                        status=verify_uploaded_natural_output(
                            drive,folder["audio"],lang,sha,float(duration),work
                        )
                        if status=="done":
                            detail["formal_mp3"]=True
                            result["drive_formal_audio"]+=1
                            report["drive_formal_audio_total"]+=1
                        else:detail["audio_issue"]=status
                    except Exception as exc:
                        detail["audio_issue"]=type(exc).__name__
                print("P259_ACCEPTANCE",tid,"qa",result["approved_sources"],
                      "manuscripts",result["drive_manuscripts"],
                      "audio",result["drive_formal_audio"],flush=True)
            except Exception as exc:
                result["blocking_issue"]=type(exc).__name__+": "+str(exc)[:220]
                print("P259_AUDIT_BLOCKED",tid,result["blocking_issue"],flush=True)
    report["all_delivered"]=(len(report["lessons"])==4 and
                             report["current_revision_qa_total"]==64 and
                             report["drive_manuscript_total"]==64 and
                             report["drive_formal_audio_total"]==64)
    out=Path(os.environ.get("P259_AUDIT_OUTPUT","/tmp/p259-delivery-acceptance.json"))
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print("P259_DELIVERY_TOTALS",report["current_revision_qa_total"],
          report["drive_manuscript_total"],report["drive_formal_audio_total"],
          "PASS" if report["all_delivered"] else "INCOMPLETE",flush=True)
    if len(report["lessons"])!=4:raise RuntimeError("P259_lessons_not_all_present")

if __name__=="__main__":run()
