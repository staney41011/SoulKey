#!/usr/bin/env python3
"""Google Sheets primary translation -> independent Gemma 4 selective semantic QA.

Input: Human-approved English final + Apps Script LanguageApp exported drafts
+ existing central glossary. Output: per-language QA checkpoints, optionally
corrected approved text and a separate publication gate in the lesson's
translation folder. Does not alter legacy gemini.qa.json, original drafts,
audio, YouTube uploads or existing translation checkpoints.
"""
from __future__ import annotations
import argparse
import json
import os
from datetime import datetime,timezone
from pathlib import Path
from config import SPREADSHEET_ID,TASK_SHEET_RANGE,GLOSSARY_FULL_RANGE
from gemini_engine import GeminiClient,parse_glossary_rows
from google_io import (build_google_services,find_file,download_drive_file,
                       upload_or_replace_file,read_values)
from lesson_paths import resolve_lesson_folders
from tts_runner import row_to_task,segments_fingerprint
from sheets_quality_core import (
    LANG_CODES,QA_VERSION,BATCH_SIZE,QA_SCHEMA,stable_sha,text_sha,
    audit_segment,selected_for_review,review_prompt,parse_model_result,
    check_repair,summarize_language,gate_ready
)

def now():
    return datetime.now(timezone.utc).isoformat()

def load_json(drive,folder,name,working,required=False):
    found=find_file(drive,folder,name)
    if found is None:
        if required: raise RuntimeError(f"Required SoulKey Drive file missing: {name}")
        return None,None
    path=Path(working)/name
    download_drive_file(drive,found["id"],path)
    return json.loads(path.read_text(encoding="utf-8")),found["id"]

def publish_json(drive,folder,name,value,working):
    path=Path(working)/name
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")
    upload_or_replace_file(drive,folder,path,name)
    return path

def task_lookup(sheets,task_id):
    rows=read_values(sheets,SPREADSHEET_ID,TASK_SHEET_RANGE)
    tasks=[row_to_task(row,index) for index,row in enumerate(rows,start=2)
           if row and str(row[0]).strip()==task_id]
    if len(tasks)!=1 or not tasks[0].get("period") or not tasks[0].get("lesson"):
        raise RuntimeError("Task not registered uniquely in central Sheet")
    return tasks[0]

def english_map_from_payload(payload):
    segments=payload.get("segments") or []
    mapping={int(x["id"]):x for x in segments}
    if not segments or len(mapping)!=len(segments):
        raise RuntimeError("Approved English source missing/duplicate segments")
    return mapping

def validated_draft(drive,folder,task_id,lang,work,en_id,en_map):
    draft_name=f"{task_id}-{lang}-google-translate-DRAFT.json"
    data,draft_id=load_json(drive,folder,draft_name,work,True)
    if (data.get("task_id")!=task_id or data.get("language")!=lang or
        data.get("engine")!="LanguageApp.translate" or
        data.get("source_file_id")!=en_id):
        raise RuntimeError("Untrusted Sheets export source or English revision")
    segments=data.get("segments") or []
    if len(segments)!=len(en_map) or len({int(x["id"]) for x in segments})!=len(en_map):
        raise RuntimeError("Sheets draft segment count/IDs inconsistent with English Final")
    mapping={int(x["id"]):x for x in segments}
    if set(mapping)!=set(en_map):
        raise RuntimeError("Sheets draft has missing/extra segment IDs")
    return [mapping[sid] for sid in sorted(mapping)],draft_id

def review_once(client,language,entries):
    response,usage=client.structured(
        review_prompt(language,entries),QA_SCHEMA,
        thinking_level="low")
    return parse_model_result(response,{int(x["id"]) for x in entries}),usage

def evaluate_language(drive,trans_id,task_id,lang,en_id,en_map,glossary,
                      client,working,model_budget):
    draft_folder=find_file(drive,trans_id,"AppsScript初譯-待QA")
    if not draft_folder:
        raise RuntimeError("Google Sheets export folder missing")
    draft,draft_id=validated_draft(
        drive,draft_folder["id"],task_id,lang,working,en_id,en_map)
    draft_map={int(x["id"]):x for x in draft}
    report_name=f"sheets.qa.{lang}.json"
    digest=stable_sha(draft)
    english_digest=stable_sha([en_map[x] for x in sorted(en_map)])
    glossary_digest=stable_sha(glossary)
    version_key=stable_sha([QA_VERSION,task_id,lang,digest,english_digest,glossary_digest])
    prev,_=load_json(drive,trans_id,report_name,working,False)
    # Revision-aware cache. Never reuse any decision when the English,
    # Sheets translation, glossary, QA algorithm or language changes.
    if prev and prev.get("revision_key")==version_key:
        decisions=dict(prev.get("decisions") or {})
    else:
        decisions={}
    audits=[]
    for item in draft:
        sid=int(item["id"])
        audit=audit_segment(en_map[sid],item,lang,glossary)
        audits.append(audit)
    chosen=selected_for_review(audits,task_id,lang)
    for item in audits:
        item["selected_for_ai"]=item["id"] in chosen
        if item["hard_errors"]:
            decisions.pop(str(item["id"]),None)
    # No shortcuts: a cached B correction must have an independently verified
    # second pass; any cached C or model error must remain review-required.
    todo=[x["id"] for x in audits if x["selected_for_ai"] and
          not x["hard_errors"] and not (
           decisions.get(str(x["id"]),{}).get("grade") in {"A","B_verified","C"})]
    calls=0
    model_errors=[]
    while todo and calls<model_budget:
        ids=todo[:BATCH_SIZE]
        entries=[]
        for sid in ids:
            orig=en_map[sid]
            tar=draft_map[sid]
            audit=next(x for x in audits if x["id"]==sid)
            entries.append({
                "id":sid,"source":orig["text"],"target":tar["text"],
                "risk_flags":audit["risk_flags"],"numbers_in_source":audit["source_numbers"],
                "numbers_in_translation":audit["target_numbers"],
                "glossary":audit["glossary"]
            })
        try:
            reviewed,_=review_once(client,lang,entries)
            calls+=1
        except Exception as exc:
            calls+=1
            model_errors.append(type(exc).__name__+": "+str(exc)[:180])
            print(f"[SHEETS-QA] {task_id}/{lang} model deferred: "
                  f"{type(exc).__name__} {str(exc)[:100]}",flush=True)
            break
        for sid in ids:
            result=reviewed[sid]
            result["reviewed_at"]=now()
            result["source_text_hash"]=text_sha(en_map[sid]["text"])
            result["target_text_hash"]=text_sha(draft_map[sid]["text"])
            if result["grade"]=="B":
                correction=result["corrected_text"].strip()
                audit=next(x for x in audits if x["id"]==sid)
                if not check_repair(draft_map[sid],correction,lang,audit):
                    result["grade"]="C"
                    result["reason"]+="; proposed correction fails deterministic safety"
                elif calls<model_budget:
                    # An independent second semantic pass verifies the actual
                    # proposed corrected text against the same original.
                    verify_entries=[{"id":sid,"source":en_map[sid]["text"],
                                     "target":correction,"risk_flags":[],
                                     "numbers_in_source":audit["source_numbers"],
                                     "glossary":audit["glossary"]}]
                    try:
                        checked,_=review_once(client,lang,verify_entries)
                        calls+=1
                        if checked[sid]["grade"]=="A":
                            result["grade"]="B_verified"
                            result["corrected_text"]=correction
                        else:
                            result["grade"]="C"
                            result["reason"]+="; corrected text failed independent second QA"
                    except Exception as exc:
                        calls+=1
                        result["grade"]="C"
                        result["reason"]+="; independent repair QA unavailable"
                        model_errors.append(type(exc).__name__)
                else:
                    # Recheck in next run rather than auto-publish unverified fix.
                    result["grade"]="B_pending"
            decisions[str(sid)]=result
        todo=[x for x in todo if x not in ids]
        # Incremental checkpoint protects work against quotas/timeouts.
        partial=summarize_language(audits,decisions)
        checkpoint={
            "task_id":task_id,"lang":lang,"engine":"Google Sheets initial + Gemma4 audit",
            "model":client.text_model,"version":QA_VERSION,"revision_key":version_key,
            "source_file_id":en_id,"draft_file_id":draft_id,"draft_sha":digest,
            "english_sha":english_digest,"glossary_sha":glossary_digest,
            "state":partial["state"],"review_scope":partial["review_scope"],
            "decisions":decisions,"audits":audits,"summary":partial,
            "updated_at":now(),"model_errors":model_errors,
        }
        publish_json(drive,trans_id,report_name,checkpoint,working)
    summary=summarize_language(audits,decisions)
    record={
        "task_id":task_id,"lang":lang,"engine":"Google Sheets initial + Gemma4 selective QA",
        "model":client.text_model,"version":QA_VERSION,"revision_key":version_key,
        "source_file_id":en_id,"draft_file_id":draft_id,"draft_sha":digest,
        "english_sha":english_digest,"glossary_sha":glossary_digest,
        "state":summary["state"],"review_scope":summary["review_scope"],
        "summary":summary,"decisions":decisions,"audits":audits,
        "updated_at":now(),"model_errors":model_errors,"api_calls_this_run":calls,
    }
    publish_json(drive,trans_id,report_name,record,working)
    if summary["state"]=="approved_risk_based":
        updated=[]
        for row in draft:
            item=dict(row)
            decision=decisions.get(str(row["id"])) or {}
            if decision.get("grade")=="B_verified":
                item["text"]=decision["corrected_text"]
                item["qa_modified_from_google_sheets"]=True
            updated.append(item)
        approved={
            "task_id":task_id,"language":lang,
            "engine":"Google Sheets with Gemma4 selective QA",
            "status":"approved_risk_based",
            "semantic_qa_scope":"high_risk_plus_reproducible_sample",
            "full_semantic_qa":False,
            "revision_key":version_key,"draft_file_id":draft_id,
            "source_file_id":en_id,
            "source_sha256":segments_fingerprint(updated),
            "segments":updated,
            "corrected_ids":summary["corrected_ids"],
            "qa_report_file":report_name,
        }
        publish_json(drive,trans_id,f"sheets.qa.approved.{lang}.json",
                     approved,working)
    print(f"[SHEETS-QA] {task_id}/{lang}={summary['state']} "
          f"AI={summary['model_reviewed_pass']}/{summary['model_review_required']}"
          f" corrections={len(summary['corrected_ids'])}, api_calls={calls}",
          flush=True)
    return record

def release_gate(drive,folders,task_id,required_languages,work,sheets=None):
    trans=folders["translation"]
    current_english,en_id=load_json(drive,trans,"en.final.json",work,True)
    en_map=english_map_from_payload(current_english)
    english_sha=stable_sha([en_map[x] for x in sorted(en_map)])
    current_glossary_sha=None
    if sheets is not None:
        glossary=parse_glossary_rows(
            read_values(sheets,SPREADSHEET_ID,GLOSSARY_FULL_RANGE))
        current_glossary_sha=stable_sha(glossary)
    draft_folder=find_file(drive,trans,"AppsScript初譯-待QA")
    accepted={}
    audio_blockers=[]
    for lang in required_languages:
        report,_=load_json(drive,trans,f"sheets.qa.{lang}.json",work)
        if not report:
            accepted[lang]={"state":"missing"}
            continue
        approved,_=load_json(drive,trans,f"sheets.qa.approved.{lang}.json",work)
        if not approved or (approved.get("revision_key")!=report.get("revision_key")):
            accepted[lang]={"state":"needs_review"}
            continue
        if report.get("source_file_id")!=en_id or report.get("english_sha")!=english_sha:
            accepted[lang]={"state":"needs_review","reason":"stale_english_final"}
            continue
        if current_glossary_sha and report.get("glossary_sha")!=current_glossary_sha:
            accepted[lang]={"state":"needs_review","reason":"glossary_updated"}
            continue
        if not draft_folder:
            accepted[lang]={"state":"needs_review","reason":"missing_draft_folder"}
            continue
        try:
            current_draft,draft_id=validated_draft(
                drive,draft_folder["id"],task_id,lang,work,en_id,en_map)
            if (draft_id!=report.get("draft_file_id") or
                report.get("draft_sha")!=stable_sha(current_draft)):
                accepted[lang]={"state":"needs_review","reason":"stale_sheets_draft"}
                continue
        except Exception:
            accepted[lang]={"state":"needs_review","reason":"invalid_current_draft"}
            continue
        accepted[lang]={"state":report.get("state"),
                        "review_scope":report.get("review_scope"),
                        "revision_key":report.get("revision_key")}
        if report.get("state")=="approved_risk_based":
            from tts_runner import _load_tts_manifest
            manifest=_load_tts_manifest(drive,folders["audio"],lang,work)
            # A newly corrected text must be re-spoken before publishing.
            if not manifest or manifest.get("status")!="done" or (
                    manifest.get("source_sha256")!=approved.get("source_sha256")):
                audio_blockers.append({"lang":lang,
                   "reason":"approved_text_does_not_match_delivered_audio"})
    text_gate=gate_ready(accepted,required_languages)
    final={
        "task_id":task_id,"updated_at":now(),
        "semantic_review_ready":text_gate["ready"],
        "audio_revision_ready":not audio_blockers,
        "can_release":text_gate["ready"] and not audio_blockers,
        "review_scope":"risk_based_not_full_semantic_review",
        "text_blockers":text_gate["blocked"],
        "audio_blockers":audio_blockers,
        "source":"sheets.qa.<lang>.json + approved segments + TTS SHA receipts"
    }
    publish_json(drive,trans,"sheets.qa.publish_gate.json",final,work)
    return final

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--task-id",required=True)
    parser.add_argument("--langs",default=",".join(LANG_CODES))
    parser.add_argument("--max-model-calls",type=int,default=24,
                        help="Maximum Gemma API calls per execution, not per language")
    parser.add_argument("--gate-only",action="store_true")
    args=parser.parse_args()
    requested=list(dict.fromkeys(x.strip() for x in args.langs.split(",") if x.strip()))
    if not requested or any(x not in LANG_CODES for x in requested):
        parser.error("Unknown target language code")
    if args.max_model_calls<0 or args.max_model_calls>250:
        parser.error("Maximum API calls must be between 0 and 250")
    drive,sheets=build_google_services()
    task=task_lookup(sheets,args.task_id)
    folders=resolve_lesson_folders(drive,sheets,task["period"],task["lesson"])
    work=Path(os.environ.get("SOULKEY_QA_WORKDIR","/tmp/soulkey-qa"))/args.task_id
    work.mkdir(parents=True,exist_ok=True)
    en,en_id=load_json(drive,folders["translation"],"en.final.json",work,True)
    en_map=english_map_from_payload(en)
    if not args.gate_only:
        glossary=parse_glossary_rows(read_values(sheets,SPREADSHEET_ID,GLOSSARY_FULL_RANGE))
        client=GeminiClient(text_model=os.getenv("SOULKEY_TEXT_MODEL","gemma-4-26b-a4b-it"),
                            max_attempts=2,timeout=70)
        remaining=args.max_model_calls
        for lang in requested:
            result=evaluate_language(
                drive,folders["translation"],args.task_id,lang,en_id,en_map,
                glossary,client,work,remaining)
            remaining=max(0,remaining-int(result.get("api_calls_this_run") or 0))
        print("[SHEETS-QA] API budget remaining="+str(remaining),flush=True)
    gate=release_gate(drive,folders,args.task_id,list(LANG_CODES),work,sheets=sheets)
    print("[SHEETS-QA] publication gate="+json.dumps(gate,ensure_ascii=False),flush=True)
    # Partial/blocked text is an expected QA outcome, distinct from API
    # infrastructure failure. The worker reports NEEDS_REVIEW on code 3.
    return 0 if all((load_json(drive,folders["translation"],
                        f"sheets.qa.{lang}.json",work)[0] or {}).get("state")
                     =="approved_risk_based" for lang in requested) else 3

if __name__=="__main__":
    raise SystemExit(main())
