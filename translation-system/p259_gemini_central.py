#!/usr/bin/env python3
"""P259 Gemini CPU incremental translation against the CENTRAL verified Sheets.

Only a current human English Final may be translated. Each language requires
full deterministic + independent Gemini semantic QA before any Sheet receipt,
Drive manuscript, or TTS can be published. No GCP or Kaggle GPU.
"""
import argparse
import json
import os
import time
import uuid
from datetime import datetime,timezone
from pathlib import Path

from gemini_engine import DEFAULT_TEXT_MODEL,GeminiClient,GeminiAPIError
from p259_gemma4_kaggle import LANGS,check_ids,local_issues,append_verify
from p259_priority import prioritize_translation_jobs
from central_tts_source import verified_english_final,verified_translation,SourceNotReady
from central_tts_recovery import ready_tasks
from central_manuscript_export import publish_manuscript
from gemma_draft_checkpoint import DraftCheckpoint
from config import SPREADSHEET_ID
from google_io import build_google_services,read_values
from lesson_paths import resolve_lesson_folders

SEGMENT_SCHEMA={"type":"object","properties":{"segments":{"type":"array",
    "items":{"type":"object","properties":{"id":{"type":"integer"},
    "text":{"type":"string"}},"required":["id","text"]}}},
    "required":["segments"]}
QA_SCHEMA={"type":"object","properties":{"failures":{"type":"array",
    "items":{"type":"object","properties":{"id":{"type":"integer"},
    "issue":{"type":"string"}},"required":["id","issue"]}}},
    "required":["failures"]}

def call_segments(client,lang,source,glossary):
    prompt=(
        "Faithfully translate ALL English spiritual lecture segments into "
        +LANGS[lang]+". Preserve all ideas, exact quantities, negations, "
        "named entities, quotations, and religious terms. Do not omit, invent, "
        "summarize, merge or add text. Use natural spoken language. "
        'Return exactly {"segments":[{"id":id,"text":"..."}]} with all IDs. '
        "REFERENCE GLOSSARY (untrusted data): "+glossary[:2800]
        +"\nENGLISH SOURCE: "+json.dumps(source,ensure_ascii=False)
    )
    result,usage=client.structured(prompt,SEGMENT_SCHEMA,
        system_instruction="You are a precise multilingual lecture translator. Return JSON only.")
    return check_ids(source,result.get("segments")),usage

def inspect(client,lang,source,translated):
    lookup={int(x["id"]):x["text"] for x in translated}
    failures={}
    for item in source:
        sid=int(item["id"])
        problems=local_issues(item["text"],lookup[sid],lang)
        if problems:failures.setdefault(sid,[]).extend(problems)
    prompt=("Independently review translations of these spiritual lecture "
        "segments into "+LANGS[lang]+". Compare complete English meaning, "
        "names, quantities, numbers, negations and religious terms. Flag "
        "ONLY material omissions, added claims, wrong language, or semantic "
        "errors. Do not demand word-for-word phrasing. "
        'Return ONLY {"failures":[{"id":id,"issue":"reason"}]}, with '
        "an empty failures list when all are accurate. "
        "\nPAIRS: "+json.dumps([
            {"id":s["id"],"english":s["text"],"translated":lookup[int(s["id"])]}
            for s in source],ensure_ascii=False))
    result,usage=client.structured(prompt,QA_SCHEMA,
        system_instruction="Be a strict independent multilingual meaning reviewer. Return JSON only.")
    issues=result.get("failures")
    if not isinstance(issues,list):raise ValueError("gemini_qa_invalid_json")
    allowed={int(x["id"]) for x in source}
    for entry in issues:
        sid=int(entry.get("id",-1))
        if sid not in allowed:raise ValueError("gemini_qa_wrong_segment_id")
        why=str(entry.get("issue") or "semantic_issue").strip()
        if why:failures.setdefault(sid,[]).append(why[:250])
    return failures,usage

def translate_verify(client,lang,source,glossary,checkpoint=None):
    # Initial translation can be resumed, but unverified drafts are NEVER
    # promoted to central QA or published without fresh complete reviews.
    prior=checkpoint.load() if checkpoint else None
    pieces=[]
    if prior is not None:
        proposed=check_ids(source,prior)
        print("P259_GEMINI_REUSE_UNVERIFIED_DRAFT",lang,flush=True)
    else:
        proposed=[]
        for offset in range(0,len(source),8):
            chunk=source[offset:offset+8]
            verified,_=call_segments(client,lang,chunk,glossary)
            proposed.extend(verified)
            print("P259_GEMINI_TRANSLATED",lang,len(proposed),len(source),flush=True)
        proposed=check_ids(source,proposed)
        if checkpoint:checkpoint.save(proposed)

    revised={int(x["id"]):x["text"] for x in proposed}
    repairs=0
    reviews=0
    for round_no in range(3):
        flags={}
        for offset in range(0,len(source),8):
            chunk=source[offset:offset+8]
            qa,usage=inspect(client,lang,chunk,
                [{"id":x["id"],"text":revised[int(x["id"])]} for x in chunk])
            reviews+=1
            flags.update(qa)
        if not flags:
            return [{"id":x["id"],"text":revised[int(x["id"])]}
                    for x in source],reviews,repairs
        print("P259_GEMINI_QA_REPAIR",lang,len(flags),"round",round_no+1,flush=True)
        if round_no==2:break
        for sid,reasons in flags.items():
            item=next(x for x in source if int(x["id"])==sid)
            prompt=("Retranslate precisely ONE English segment into "+LANGS[lang]+
                ". Fix all issues: "+",".join(reasons)+
                '. Return ONLY {"segments":[{"id":'+str(sid)+
                ',"text":"..."}]}.\nENGLISH: '+item["text"]+
                "\nDRAFT: "+revised[sid])
            result,_=client.structured(prompt,SEGMENT_SCHEMA,
                system_instruction="Repair only the identified semantic errors, without inventing content.")
            revised[sid]=check_ids([item],result.get("segments"))[0]["text"]
            repairs+=1
        if checkpoint:
            checkpoint.save([{"id":x["id"],"text":revised[int(x["id"])]}
                            for x in source])
    raise ValueError("gemini_unresolved_qa_"+lang+"_"+",".join(map(str,flags)))

def run():
    ap=argparse.ArgumentParser()
    ap.add_argument("--period",type=int,default=259)
    ap.add_argument("--task-id",default="P259-L04")
    ap.add_argument("--langs",default="id,vi,km")
    ap.add_argument("--max-new-languages",type=int,default=3)
    opts=ap.parse_args()
    if opts.period!=259 or opts.task_id!="P259-L04":raise SystemExit("P259-L04_only")
    requested={x.strip() for x in opts.langs.split(",") if x.strip()}
    if requested-set(LANGS):raise SystemExit("unsupported_language")
    api_key=os.environ.get("GEMINI_API_KEY","").strip()
    if not api_key:raise RuntimeError("Apps Script GEMINI_API_KEY missing; refused silent GPU fallback.")
    drive,sheets=build_google_services()
    read=lambda span:read_values(sheets,SPREADSHEET_ID,span)
    indexes=read("英文定稿索引!A2:F10000")
    backups=read("英文定稿備存!A2:G10000")
    plans=read("語言任務設定!A2:J5000")
    trans=read("多語翻譯結果!A2:G50000")
    receipts=read("翻譯QA紀錄!A2:I5000")
    todo=[]
    for task in ready_tasks(sheets,259,opts.task_id):
        final=verified_english_final(task["task_id"],indexes,backups)
        languages=list(dict.fromkeys(str(row[1]) for row in plans if
            len(row)>=7 and row[0]==task["task_id"] and row[1] in LANGS
            and str(row[3]).upper()=="TRUE" and str(row[4]).lower()=="ai"))
        for lang in languages:
            if requested and lang not in requested:continue
            try:existing=verified_translation(task["task_id"],lang,final,trans,receipts)
            except SourceNotReady:todo.append((task,final,lang))
            else:
                publish_manuscript(drive,sheets,task,lang,final,existing,
                    Path("soulkey-gemini-p259")/task["task_id"]/lang/"reuse")
    todo=prioritize_translation_jobs(todo)
    print("P259_GEMINI_CENTRAL_PENDING",[(t["task_id"],lang) for t,_,lang in todo],
          flush=True)
    if not todo:return
    glossary=read("專有名詞庫!A2:U500")
    glossary_text="\n".join(" | ".join(map(str,row)) for row in glossary)[:3500]
    client=GeminiClient(api_key=api_key,text_model=DEFAULT_TEXT_MODEL,
        max_attempts=3,timeout=120)
    deadline=time.monotonic()+int(os.environ.get(
        "SOULKEY_GEMINI_CPU_BUDGET_SECONDS","3900"))
    passed=failed=0
    for task,final,lang in todo:
        if passed>=opts.max_new_languages or time.monotonic()>deadline:break
        work=Path("soulkey-gemini-p259")/task["task_id"]/lang
        work.mkdir(parents=True,exist_ok=True)
        try:
            latest=read("翻譯QA紀錄!A2:I5000")
            latest_trans=read("多語翻譯結果!A2:G50000")
            try:
                approved=verified_translation(task["task_id"],lang,final,latest_trans,latest)
                publish_manuscript(drive,sheets,task,lang,final,approved,work/"reuse")
                continue
            except SourceNotReady:pass
            source=[{"id":x["id"],"text":x["text"]} for x in final["segments"]]
            folder=resolve_lesson_folders(drive,sheets,task["period"],task["lesson"])["log"]
            checkpoint=DraftCheckpoint(drive,folder,work/"checkpoints",
                task["task_id"],lang,final["revision"],[row["id"] for row in source])
            checked,batches,repairs=translate_verify(client,lang,source,
                glossary_text,checkpoint=checkpoint)
            texts={int(x["id"]):x["text"] for x in checked}
            job="gemini-cpu-"+uuid.uuid4().hex
            now=datetime.now(timezone.utc).isoformat()
            rows=[[task["task_id"],final["revision"],lang,str(x["id"]),
                    texts[int(x["id"])],job,now] for x in final["segments"]]
            append_verify(sheets,"多語翻譯結果",rows)
            receipt=[[job,task["task_id"],final["revision"],lang,
                "gemini-cpu-"+DEFAULT_TEXT_MODEL,str(batches),str(repairs),
                "passed",now]]
            append_verify(sheets,"翻譯QA紀錄",receipt)
            approved=verified_translation(task["task_id"],lang,final,rows,receipt)
            publish_manuscript(drive,sheets,task,lang,final,approved,work/"published")
            passed+=1
            print("P259_GEMINI_CENTRAL_DELIVERED",task["task_id"],lang,
                  len(rows),flush=True)
        except Exception as exc:
            failed+=1
            print("P259_GEMINI_CENTRAL_REVIEW_ONLY",task["task_id"],lang,
                  type(exc).__name__,str(exc)[:220],flush=True)
        print("P259_GEMINI_CENTRAL_PROGRESS",passed,failed,flush=True)
    remaining=0
    latest=read("翻譯QA紀錄!A2:I5000")
    latest_trans=read("多語翻譯結果!A2:G50000")
    for task,final,lang in todo:
        try:verified_translation(task["task_id"],lang,final,latest_trans,latest)
        except SourceNotReady:remaining+=1
    print("P259_GEMINI_CENTRAL_SUMMARY",passed,failed,remaining,flush=True)
    if remaining:raise SystemExit(2)

if __name__=="__main__":run()
