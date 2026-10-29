#!/usr/bin/env python3
"""Restore the OLD production Edge Natural TTS pipeline against verified NEW
central Sheet manuscripts. Does not invoke ASR, Gemini, or overwrite source.
Runs on Kaggle CPU with the original owner Google OAuth Kaggle Secrets.
"""
import argparse,hashlib,json,os,sys,traceback
from pathlib import Path

from config import SPREADSHEET_ID,TASK_SHEET_RANGE
from google_io import build_google_services,read_values,find_file,download_drive_file
from lesson_paths import resolve_lesson_folders
from central_tts_source import verified_english_final,verified_translation,SourceNotReady

def ready_tasks(sheets,period,only_task):
    rows=read_values(sheets,SPREADSHEET_ID,TASK_SHEET_RANGE)
    for row in rows:
        if len(row)<3 or not str(row[0]).startswith("P"):continue
        tid=str(row[0]);p=int(str(row[1]).strip()) if str(row[1]).strip().isdigit() else -1
        if period is not None and p!=period:continue
        if only_task and tid!=only_task:continue
        yield {"task_id":tid,"period":p,"lesson":str(row[2]),
               "title":str(row[3]) if len(row)>3 else ""}

def approved_plan_rows(rows,task):
    result=[]
    for row in rows:
        if len(row)<7 or row[0]!=task or str(row[6]).upper()!="TRUE":continue
        lang=str(row[1]).lower().strip()
        if lang not in result:result.append(lang)
    return result

def verified_existing_audio(drive,folder,lang,source_sha,en_revision,duration,work):
    from tts_runner import verify_uploaded_natural_output,_load_tts_manifest
    manifest=_load_tts_manifest(drive,folder,lang,work)
    if (manifest and manifest.get("en_backup_revision")==en_revision and
        str(manifest.get("source_sha256"))==source_sha):
        return verify_uploaded_natural_output(drive,folder,lang,source_sha,duration,work)
    return "missing"

def produce(drive,sheets,task,lang,final,approved,workdir):
    from tts_fingerprint import segments_fingerprint
    from tts_runner import (render_natural_language,upload_natural_outputs,
        verify_uploaded_natural_output,load_source_duration_limit,
        local_audio_receipt,LANGUAGE_NAMES)
    from natural_tts_config import NATURAL_TTS_PROFILES
    from natural_tts_planner import build_speech_blocks
    from natural_tts_drive_cache import DriveTTSBlockCache
    from status_io import new_run_id,mark_running,mark_done,mark_needs_review,mark_error
    if lang not in NATURAL_TTS_PROFILES:raise SourceNotReady("voice_not_supported:"+lang)
    folders=resolve_lesson_folders(drive,sheets,task["period"],task["lesson"])
    workdir.mkdir(parents=True,exist_ok=True)
    authoritative_duration,basis=load_source_duration_limit(drive,folders["source"],workdir)
    duration=(float(authoritative_duration) if authoritative_duration
       else max(float(x["end"]) for x in final["segments"]))
    if duration<=0:raise SourceNotReady("original_video_duration_unavailable")
    source=approved["segments"]
    sha=segments_fingerprint(source)
    prior=verified_existing_audio(drive,folders["audio"],lang,sha,
        final["revision"],duration,workdir)
    if prior in ("done","needs_review"):
        print("TTS_REUSE_DRIVE",task["task_id"],lang,prior,flush=True)
        return "reused_"+prior
    run_id=new_run_id(task["task_id"],"tts:"+lang)
    mark_running(task["task_id"],"tts:"+lang,sheets=sheets,
        run_id=run_id,message="中央 QA 已通過；沿用舊版 Natural TTS",progress=0)
    try:
        blocks,_=build_speech_blocks(source,lang)
        cache=DriveTTSBlockCache(drive,folders["audio"],lang,sha,blocks,
            workdir/"drive-checkpoint")
        result=render_natural_language(source,lang,workdir,
            source_duration=duration,
            duration_limit_basis=basis if authoritative_duration else "human_final_time_estimate",
            checkpoint_store=cache,smart_fit_pilot=False)
        manifest_path=Path(result["manifest"])
        manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["task_id"]=task["task_id"]
        manifest["en_backup_revision"]=final["revision"]
        manifest["verified_translation_job"]=approved["job_id"]
        manifest["central_source"]="英文定稿索引 + 多語翻譯結果 + 翻譯QA紀錄"
        if not authoritative_duration and result["status"]=="done":
            # The Final timeline is not authoritative video duration. Deliver a
            # listenable preview, but NEVER mark/upload an official final MP3.
            import shutil
            shutil.copy2(result["mp3"],result["preview_mp3"])
            result["status"]="needs_review"
            manifest["status"]="needs_review"
            manifest["needs_review_reason"]="source_info_duration_missing"
            manifest["audio_receipts"]={"preview_mp3":local_audio_receipt(result["preview_mp3"])}
        manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
        upload_natural_outputs(drive,folders["audio"],result,task)
        confirmed=verify_uploaded_natural_output(drive,folders["audio"],lang,
            sha,duration,workdir)
        if confirmed!=result["status"]:
            raise RuntimeError("tts_drive_readback_mismatch")
        if confirmed=="done":
            mark_done(task["task_id"],"tts:"+lang,sheets=sheets,run_id=run_id,
                message="正式 MP3/WAV 與 manifest 已上傳 Drive 並校驗")
        else:
            mark_needs_review(task["task_id"],"tts:"+lang,sheets=sheets,
                run_id=run_id,message="完整試聽 MP3 已上傳，待原片音長／語音驗收")
        print("TTS_DRIVE_VERIFIED",task["task_id"],lang,confirmed,flush=True)
        return confirmed
    except Exception as error:
        mark_error(task["task_id"],"tts:"+lang,sheets=sheets,
            run_id=run_id,exc=error)
        raise

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--period",type=int,default=259)
    ap.add_argument("--task-id",default="")
    ap.add_argument("--lang",default="")
    ap.add_argument("--max-languages",type=int,default=1)
    args=ap.parse_args()
    if args.max_languages<1 or args.max_languages>4:
        raise SystemExit("max_languages_out_of_bounds")
    drive,sheets=build_google_services()
    get=lambda range_:read_values(sheets,SPREADSHEET_ID,range_)
    index=get("英文定稿索引!A2:F10000")
    backups=get("英文定稿備存!A2:G10000")
    translations=get("多語翻譯結果!A2:G50000")
    qa=get("翻譯QA紀錄!A2:I5000")
    plans=get("語言任務設定!A2:J5000")
    processed=0;ready=0
    for task in ready_tasks(sheets,args.period,args.task_id):
        try:final=verified_english_final(task["task_id"],index,backups)
        except SourceNotReady as error:
            print("TTS_SKIP_NO_FINAL",task["task_id"],str(error),flush=True)
            continue
        for lang in approved_plan_rows(plans,task["task_id"]):
            if args.lang and args.lang!=lang:continue
            try:approved=verified_translation(task["task_id"],lang,final,translations,qa)
            except SourceNotReady as error:
                print("TTS_WAIT_FOR_QA",task["task_id"],lang,str(error),flush=True)
                continue
            ready+=1
            work=Path(os.environ.get("SOULKEY_TTS_WORKDIR", "./soulkey-central-tts"))/task["task_id"]/lang
            state=produce(drive,sheets,task,lang,final,approved,work)
            if state.startswith("reused_"):
                continue  # Old verified output does not consume the per-run production budget.
            if state=="missing":raise RuntimeError("audio_not_delivered")
            if state in ("done","needs_review"):
                processed+=1
                if processed>=args.max_languages:
                    print("TTS_RECOVERY_LIMIT_REACHED",processed,flush=True)
                    return
    print("TTS_RECOVERY_COMPLETE",processed,"ready_sources",ready,flush=True)

if __name__=="__main__":
    main()
