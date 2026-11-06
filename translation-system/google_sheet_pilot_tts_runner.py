#!/usr/bin/env python3
"""Approved Google Sheets translations -> official SoulKey Natural TTS.

Owner requested acceptance of Google Sheets translations as formal speech
source for P260-L01, L02 and L04, without pretending Gemma4 semantic QA passed.
Preserve all existing technically approved official audio and all translation
files. A test/audit trail records exact draft ids and English revision hashes.
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from google_io import build_google_services, find_file, download_drive_file, upload_or_replace_file, read_values
from lesson_paths import resolve_lesson_folders
from config import SPREADSHEET_ID, TASK_SHEET_RANGE
from status_io import new_run_id, mark_running, mark_done, mark_needs_review, mark_error
from tts_runner import (LANGUAGE_NAMES, row_to_task, load_source_duration_limit,
                        render_natural_language, segments_fingerprint,
                        upload_natural_outputs, existing_natural_output,
                        verify_uploaded_natural_output, _load_tts_manifest)

ALLOWED={"P260-L01":58,"P260-L02":36,"P260-L03":50,"P260-L04":48}
LANGS="th,es,id,vi,hi,ta,ja,ko,km,bn,ne,lo,my,it,pt"

def sha(text):
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()

def draft_source(drive, folder, task_id, language, work, english_file, english_map, expected):
    name=f"{task_id}-{language}-google-translate-DRAFT.json"
    item=find_file(drive,folder,name)
    if not item:
        raise RuntimeError("Missing Google Sheets export: "+name)
    fp=work/name
    download_drive_file(drive,item["id"],fp)
    value=json.loads(fp.read_text(encoding="utf-8"))
    if (value.get("task_id")!=task_id or value.get("language")!=language
        or value.get("engine")!="LanguageApp.translate"
        or value.get("status")!="pending_Gemma4_QA"
        or value.get("source_file_id")!=english_file):
        raise RuntimeError("Unexpected translation source or revision metadata")
    segments=value.get("segments") or []
    if len(segments)!=expected or len(english_map)!=expected:
        raise RuntimeError(f"Translation/English source count mismatch: {len(segments)}/{len(english_map)} expected {expected}")
    if {int(v["id"]) for v in segments} != set(english_map):
        raise RuntimeError("Segment ids differ from approved English final")
    for row in segments:
        en=english_map[int(row["id"])]
        if not str(row.get("text") or "").strip():
            raise RuntimeError("Empty translated segment")
        if sha(en.get("text")) != str(row.get("source_hash") or ""):
            raise RuntimeError(f"English Final changed for segment {row['id']}")
        if abs(float(row.get("start") or 0)-float(en.get("start") or 0))>0.06:
            raise RuntimeError("Changed timestamp start for "+str(row["id"]))
        if abs(float(row.get("end") or 0)-float(en.get("end") or 0))>0.06:
            raise RuntimeError("Changed timestamp end for "+str(row["id"]))
        if float(row["end"])<=float(row["start"]):
            raise RuntimeError("Malformed translation timestamp")
    return segments,item["id"]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--task-id",required=True,choices=sorted(ALLOWED))
    ap.add_argument("--langs",required=True)
    a=ap.parse_args()
    task_id=a.task_id
    langs=list(dict.fromkeys(x.strip() for x in a.langs.split(",") if x.strip()))
    if not langs or len(langs)>15 or any(x not in LANGS.split(",") for x in langs):
        ap.error("Selection must be subset of 15 supported Google Sheets translations")
    drive,sheets=build_google_services()
    matching=[row_to_task(raw,i) for i,raw in enumerate(
        read_values(sheets,SPREADSHEET_ID,TASK_SHEET_RANGE),start=2)
        if raw and str(raw[0] or "")==task_id]
    if len(matching)!=1:
        raise RuntimeError("Task is not uniquely registered")
    task=matching[0]
    folders=resolve_lesson_folders(drive,sheets,task["period"],task["lesson"])
    english=find_file(drive,folders["translation"],"en.final.json")
    if not english:
        raise RuntimeError("Approved English Final is missing")
    draft_folder=find_file(drive,folders["translation"],"AppsScript初譯-待QA")
    if not draft_folder or draft_folder.get("mimeType")!="application/vnd.google-apps.folder":
        raise RuntimeError("Google Sheets export folder missing")
    work=Path(os.environ.get("SOULKEY_TTS_WORKDIR","/tmp/soulkey-tts"))/(task_id+"-SHEET-FORMAL")
    work.mkdir(parents=True,exist_ok=True)
    english_file=work/"en.final.json"
    download_drive_file(drive,english["id"],english_file)
    english_payload=json.loads(english_file.read_text(encoding="utf-8"))
    english_segments=english_payload.get("segments") or []
    english_map={int(x["id"]):x for x in english_segments}
    if len(english_map)!=ALLOWED[task_id]:
        raise RuntimeError("Current English final does not match initial draft revision")
    video_duration,basis=load_source_duration_limit(drive,folders["source"],work)
    if not video_duration:
        raise RuntimeError("Missing original video duration")
    audio_folder=folders["audio"]
    print("[SHEETS-FORMAL] task=%s langs=%s original_limit=%.2fs"%
          (task_id,",".join(langs),video_duration),flush=True)
    results=[]
    for lang in langs:
        run_id=new_run_id(task_id,"tts:"+lang)
        try:
            segments,draft_id=draft_source(
                drive,draft_folder["id"],task_id,lang,work,english["id"],
                english_map,ALLOWED[task_id])
            fingerprint=segments_fingerprint(segments)
            per_language_work=work/lang
            per_language_work.mkdir(parents=True,exist_ok=True)
            # IMPORTANT: preserve any already-passed production audio even if
            # it came from another translated text revision/provider.
            old=_load_tts_manifest(drive,audio_folder,lang,per_language_work)
            if old and old.get("status")=="done":
                official_state=verify_uploaded_natural_output(
                    drive,audio_folder,lang,str(old.get("source_sha256") or ""),
                    video_duration,per_language_work)
                if official_state=="done":
                    print("[SHEETS-FORMAL] %s existing approved audio retained"%lang,flush=True)
                    results.append({"lang":lang,"state":"existing_formal_preserved"})
                    continue
            mark_running(task_id,"tts:"+lang,sheets=sheets,run_id=run_id,
                         message="Google Sheets approved source -> formal Natural TTS generating")
            result=render_natural_language(
                segments,lang,per_language_work,
                source_duration=video_duration,duration_limit_basis=basis,
                smart_fit_pilot=False,
            )
            manifest_path=Path(result["manifest"])
            manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["translation_source"]="Google Sheets LanguageApp.translate"
            manifest["translation_source_drive_id"]=draft_id
            manifest["english_final_drive_id"]=english["id"]
            manifest["english_final_segments_sha256"]=segments_fingerprint(english_segments)
            manifest["translation_semantic_qa"]="not_passed_through_Gemma4"
            manifest["formal_audio_source_authorization"]="user_requested_2026-11-05"
            manifest["note"]="Official audio only when technical timing and Drive binary validation pass. Translation source: Google Sheets unreviewed draft."
            manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
            # Only normal official audio folder. Over-length stays clearly
            # needs_review as *.preview.mp3, not a published *.mp3.
            upload_natural_outputs(drive,audio_folder,result,task)
            verified=verify_uploaded_natural_output(
                drive,audio_folder,lang,fingerprint,video_duration,per_language_work)
            if verified != result["status"]:
                raise RuntimeError("Drive binary/timing validation mismatch: "+verified)
            timeline=result["timeline"]
            if verified=="done":
                mark_done(task_id,"tts:"+lang,sheets=sheets,run_id=run_id,
                    message=("Google Sheets 來源正式音檔完成（未做 Gemma4 文字QA）；"
                             f"時長={timeline.get('final_duration',0):.1f}s；"
                             f"影片上限={video_duration:.1f}s；"
                             f"語速={timeline.get('applied_speedup',1):.3f}x"))
            else:
                mark_needs_review(task_id,"tts:"+lang,sheets=sheets,run_id=run_id,
                    message="Google Sheets來源試聽音檔已生成，因超過影片時長仍未驗收為正式 MP3")
            results.append({
                "lang":lang,"state":verified,"source":"GoogleSheets",
                "draft_id":draft_id,
                "duration_seconds":round(float(timeline.get("final_duration") or 0),1),
                "required_speedup":float(timeline.get("required_speedup") or 1)
            })
            print("[SHEETS-FORMAL] %s=%s"% (lang,verified),flush=True)
        except Exception as exc:
            print("[SHEETS-FORMAL] %s failed %s: %s"%(
                lang,type(exc).__name__,str(exc)[:200]),file=sys.stderr,flush=True)
            try: mark_error(task_id,"tts:"+lang,sheets=sheets,run_id=run_id,exc=exc)
            except Exception: pass
            results.append({"lang":lang,"state":"error","error":str(exc)[:260]})
    status_path=work/("GoogleSheets正式音檔來源紀錄-"+task_id+".json")
    status_path.write_text(json.dumps({
        "task_id":task_id,"formal_audio":True,
        "translation_source":"Google Sheets LanguageApp.translate",
        "translation_semantic_QA":"Gemma4 QA not done for these sourced texts",
        "provenance":"English source segment SHA256 verified against current approved English Final",
        "results":results
    },ensure_ascii=False,indent=2),encoding="utf-8")
    upload_or_replace_file(drive,audio_folder,status_path,status_path.name)
    print("[SHEETS-FORMAL] results "+json.dumps(results,ensure_ascii=False),flush=True)
    return 2 if all(x["state"]=="error" for x in results) else 0

if __name__=="__main__":
    raise SystemExit(main())
