#!/usr/bin/env python3
"""P259 isolated Gemma 4 26B recovery: source Final -> translation -> AI QA/repair -> Edge audio.

Original English and previously approved translations are read from their existing
Google Drive links. No original manuscript is committed to the PUBLIC repository.
This does not modify production Drive/Sheets. Outputs are reviewable GH artifacts
for subsequent authenticated Drive delivery and central QA verification.
"""
from __future__ import annotations
import argparse, asyncio, hashlib, json, os, random, re, subprocess, sys, time
from pathlib import Path
import gdown
from google import genai
from google.genai import types
import edge_tts
import edge_tts.communicate as edge_communicate
from edge_tts.constants import TRUSTED_CLIENT_TOKEN

# Mirror production SoulKey's 2026-10-27 Edge endpoint fix.
edge_communicate.WSS_URL = (
    "wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1"
    "?Ocp-Apim-Subscription-Key=" + TRUSTED_CLIENT_TOKEN
)

MODEL="gemma-4-26b-a4b-it"
SOURCES={
 "L01":dict(id="1EM3T1iZ2N5AJoW0OSawKJTiD5mUCIuyy",title="心念的力量231",speaker="中和老師",folder="1U_papocHhiKndHiqHXsA4qRBipczTGIU"),
 "L02":dict(id="1oHonBUDOKYe95SXkmUPdy8rasSG1Uiy1",title="點燃心中的那盞明燈 上",speaker="康愫玲",folder="1qV4Foo1siYTFNNqU1U1oZJ2DT2-bl-rm"),
 "L03":dict(id="1B4zHH4p2eQ-ApLrMtHBwZkN8xfqOwU-5",title="點燃心中的那盞明燈 下",speaker="康愫玲",folder="1QSvgk-RC5dlQt96Oal5DqKoBb-DXa7NZ"),
 "L04":dict(id="1WVvcJ0HbSKlwRuSCpCQtjbyq9-_7IPuF",title="圓融的思路",speaker="賴義鍠",folder="1wA-we4--FeXcrqX9PRPB4Cug2_GKqis8"),
}
LANGS={
 "km":("Khmer","高棉文","km-KH-PisethNeural"),
 "bn":("Bengali","孟加拉文","bn-BD-PradeepNeural"),
 "ne":("Nepali","尼泊爾文","ne-NP-SagarNeural"),
 "lo":("Lao","寮文","lo-LA-ChanthavongNeural"),
 "it":("Italian","義大利文","it-IT-DiegoNeural"),
 "ta":("Tamil","泰米爾文","ta-IN-ValluvarNeural"),
 "ko":("Korean","韓文","ko-KR-InJoonNeural"),
 "my":("Burmese","緬甸文","my-MM-ThihaNeural"),
 "pt":("Portuguese (Brazil)","葡萄牙文","pt-BR-AntonioNeural"),
 "id":("Indonesian","印尼文","id-ID-ArdiNeural"),
 "vi":("Vietnamese","越南文","vi-VN-NamMinhNeural"),
 "hi":("Hindi","印地語","hi-IN-MadhurNeural"),
 "ja":("Japanese","日文","ja-JP-KeitaNeural"),
}
# Already formally approved manuscripts needing audio only. Retain original translations.
EXISTING={
 ("L01","hi"):"1Yr0b0cMTqR3cPtiRnDYwOmwWEh-lYlhp",
 ("L01","ta"):"1jbc1fMQwrKm7V0QM4Z6gO7Ar7JD9Gver",
 ("L02","hi"):"11qer2TIixVb8B-OszDo-ZbgsMGx4QP1s",
 ("L02","ta"):"1rFnbKw0M9j5aKDm7yF2-hjC7r6uZRs-T",
 ("L03","hi"):"1s1c00ByGZ0IsdEV_lqUPcWFe3c1Kp2F5",
}
SCRIPTS={"km":(0x1780,0x17ff),"bn":(0x0980,0x09ff),"ne":(0x0900,0x097f),"lo":(0x0e80,0x0eff),"ta":(0x0b80,0x0bff),"ko":(0xac00,0xd7af),"my":(0x1000,0x109f),"hi":(0x0900,0x097f),"ja":(0x3040,0x9fff)}
TERMS="""Preserve the terminology, intent and solemn religious tone consistently.
'Heaven' and 'divine' refer to the spiritual tradition's teachings; do not turn them into a different religion.
'Dao temple', 'Dao cultivation', 'Buddhas and sages', 'fellow practitioners', 'spiritual fulfillment', 'blessings', and 'Path of Harmony' must remain accurate and consistently translated.
Use the same rendering of each repeated term within this lecture. Never add commentary, doctrinal corrections, unrelated exposition, paraphrased summaries, or self-identification."""
def stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())
def write_json(p,obj):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
def get_drive_json(fid,destination):
    p=gdown.download(id=fid,output=str(destination),quiet=True)
    if not p or not destination.exists():raise RuntimeError("SOURCE_DRIVE_DOWNLOAD_FAILED")
    obj=json.loads(destination.read_text("utf-8"))
    if not isinstance(obj,dict):raise ValueError("INVALID_SOURCE_JSON")
    return obj
def source_hash(segments):
    content=[{"id":int(s["id"]),"start":float(s["start"]),"end":float(s["end"]),"text":str(s["text"])} for s in segments]
    return hashlib.sha256(json.dumps(content,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def extract_obj(text):
    text=str(text or "").strip()
    start=text.find("{");end=text.rfind("}")
    if start<0 or end<start:raise ValueError("MISSING_JSON_OBJECT")
    return json.loads(text[start:end+1])
def call(client,prompt,task,output_tokens=3800):
    last=None
    for attempt in range(1,6):
        try:
            began=time.monotonic()
            result=client.models.generate_content(model=MODEL,contents=prompt,config=types.GenerateContentConfig(
                temperature=0.1,max_output_tokens=output_tokens,
                thinking_config=types.ThinkingConfig(thinking_level="minimal")))
            text=(result.text or "").strip()
            if not text:raise RuntimeError("EMPTY_MODEL_RESPONSE")
            print("GEMMA_RESPONSE",task,"secs",round(time.monotonic()-began,2),"chars",len(text),flush=True)
            return text
        except Exception as exc:
            last=exc
            delay=min(12*attempt*attempt,120)
            print("GEMMA_RETRY",task,"attempt",attempt,"error",type(exc).__name__,str(exc)[:160],"backoff_sec",delay,flush=True)
            if attempt<5:time.sleep(delay)
    raise RuntimeError(f"GEMMA_FAILED_AFTER_RETRIES {task}: {type(last).__name__}:{str(last)[:200]}")
def local_check(english,target,lang):
    target=str(target or "").strip()
    errors=[]
    if not target:errors.append("empty")
    if len(str(english))>90 and len(target)<max(22,int(len(english)*0.12)):errors.append("suspiciously_short")
    if lang in SCRIPTS and target and not any(SCRIPTS[lang][0]<=ord(c)<=SCRIPTS[lang][1] for c in target):errors.append("target_script_missing")
    if target.strip().lower()==str(english).strip().lower():errors.append("untranslated")
    return errors
def translate_batch(client,chunk,lang):
    language=LANGS[lang][0]
    data=[{"id":int(s["id"]),"english":s["text"]} for s in chunk]
    prompt=f"""Translate every given English lecture segment fully and faithfully into {language}.
{TERMS}
Preserve each exact numeric segment ID; preserve repetitions, names, quantities, examples and order.
Return ONLY VALID JSON: {{"translations":[{{"id":NUMBER,"text":"COMPLETE TARGET LANGUAGE TRANSLATION"}}]}}.
Return exactly {len(data)} translations; no omissions and no explanatory text.
DATA:\n{json.dumps(data,ensure_ascii=False)}"""
    obj=extract_obj(call(client,prompt,"translate:"+lang))
    rows=obj.get("translations",[])
    found={int(x.get("id")):str(x.get("text") or "").strip() for x in rows if isinstance(x,dict)}
    wanted={int(x["id"]) for x in chunk}
    if set(found)!=wanted:raise ValueError(f"SEGMENT_IDS_MISMATCH expected={sorted(wanted)} got={sorted(found)}")
    return found
def translate_one(client,seg,lang):
    language=LANGS[lang][0]
    prompt=f"""Translate this entire English lecture segment accurately into {language}, using natural fluent target language. Retain every sentence, repetition and religious term. No summary or notes. {TERMS}
English:\n{seg["text"]}\n\nReturn ONLY the translated text, no headings."""
    return call(client,prompt,"one:"+lang+":"+str(seg["id"]),output_tokens=2200).strip()
def qa_batch(client,chunk,translated,lang):
    language=LANGS[lang][0]
    data=[{"id":int(s["id"]),"english":s["text"],"translated":translated[int(s["id"])]} for s in chunk]
    prompt=f"""You are a multilingual independent QUALITY REVIEWER for {language} lecture translations.
Examine the ENGLISH and TRANSLATED fields of each pair. Flag ONLY substantive errors: omitted sentences,
false doctrinal meaning, wrong names/numbers, obvious non-target text, summary instead of full translation,
or changed repetition. Ignore wording preferences and minor stylistic differences.
Return ONLY VALID JSON with this exact structure:
{{"issues":[{{"id":NUMBER,"reason":"clear concrete issue in English"}}]}}
Return {{"issues":[]}} if every pair preserves its English meaning and no content is missing.
Input:\n{json.dumps(data,ensure_ascii=False)}"""
    obj=extract_obj(call(client,prompt,"audit:"+lang,output_tokens=1800))
    return {int(row["id"]):str(row["reason"])[:250] for row in obj.get("issues",[]) if isinstance(row,dict) and "id" in row}
def repair_one(client,seg,current,lang,issues):
    language=LANGS[lang][0]
    prompt=f"""Repair the {language} translation of this lecture segment. Preserve ALL English meaning and repetition.
{TERMS}
English: {seg["text"]}
Current {language}: {current}
QA issues: {json.dumps(issues,ensure_ascii=False)}
Output ONLY the COMPLETE corrected {language} translation."""
    return call(client,prompt,"repair:"+lang+":"+str(seg["id"]),output_tokens=2200).strip()
def srt_stamp(secs):
    m=max(0,round(float(secs)*1000));h,m=divmod(m,3600000);mi,m=divmod(m,60000);s,m=divmod(m,1000)
    return f"{h:02}:{mi:02}:{s:02},{m:03}"
def source_to_manuscript(src,translated):
    return [{"id":int(s["id"]),"start":float(s["start"]),"end":float(s["end"]),"text":translated[int(s["id"])]} for s in src]
def max_char_chunks(src,size=320):
    raw=" ".join(src.split())
    chunks=[]
    while raw:
        if len(raw)<=size:
            chunks.append(raw);break
        cut=size
        for j in range(size,max(30,size-85),-1):
            if raw[j-1] in ".!?។។。！？؛;، ":
                cut=j;break
        part=raw[:cut].strip()
        if not part:raise ValueError("EMPTY_TTS_CHUNK")
        chunks.append(part);raw=raw[cut:].strip()
    return chunks
def duration(path):
    return float(subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)],text=True).strip())
async def voice_all(segments,lang,output):
    _,_,voice=LANGS[lang]
    chunks=[]
    for seg in segments:
        for text in max_char_chunks(seg["text"],320 if lang in ("km","lo","ta") else 370):
            chunks.append((int(seg["id"]),text))
    if not chunks:raise ValueError("NO_AUDIO_CHUNKS")
    d=output/"parts";d.mkdir(parents=True,exist_ok=True)
    sem=asyncio.Semaphore(3)
    async def single(idx,content):
        target=d/f"{idx:04d}.mp3"
        for trial in range(1,5):
            try:
                async with sem:
                    synth=edge_tts.Communicate(content,voice,rate="-3%",pitch="-1Hz")
                    await asyncio.wait_for(synth.save(str(target)),timeout=85)
                if target.stat().st_size<180:raise RuntimeError("TINY_AUDIO_CHUNK")
                return
            except Exception as e:
                print("EDGE_RETRY",lang,idx,trial,type(e).__name__,str(e)[:90],flush=True)
                if trial==4:raise
                await asyncio.sleep(2*trial)
    await asyncio.gather(*(single(i+1,text) for i,(_,text) in enumerate(chunks)))
    concat=output/"concat.txt"
    concat.write_text("".join(f"file '{(d/f'{i:04d}.mp3').resolve()}'\n" for i in range(1,len(chunks)+1)),encoding="utf-8")
    mp3=output/"audio.mp3"
    subprocess.run(["ffmpeg","-y","-hide_banner","-loglevel","error","-f","concat","-safe","0","-i",str(concat),"-c:a","libmp3lame","-b:a","128k",str(mp3)],check=True)
    audio_sec=round(duration(mp3),2)
    if mp3.stat().st_size<120000 or audio_sec<120:
        raise RuntimeError("INCOMPLETE_AUDIO")
    return dict(duration_seconds=audio_sec,source_end_seconds=float(segments[-1]["end"]),chunks=len(chunks),bytes=mp3.stat().st_size,sha256=hashlib.sha256(mp3.read_bytes()).hexdigest())

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--lesson",required=True,choices=SOURCES.keys())
    parser.add_argument("--lang",required=True,choices=LANGS.keys())
    parser.add_argument("--tts-only",action="store_true")
    args=parser.parse_args()
    lesson=args.lesson;lang=args.lang
    info=SOURCES[lesson]
    out=Path("recovery-output")/lesson/lang
    out.mkdir(parents=True,exist_ok=True)
    report={"lesson":lesson,"task_id":f"P259-{lesson}","language":lang,"started_utc":stamp(),"model":MODEL,"translation_status":"pending","audio_status":"pending"}
    def save():write_json(out/"QA_驗收報告.json",report)
    save()
    src=get_drive_json(info["id"],out/"source.en.final.json")
    original=src.get("segments") or []
    if len(original)<35:raise ValueError("INVALID_SEGMENT_COUNT")
    if src.get("task_id")!=f"P259-{lesson}":raise ValueError("TASK_ID_MISMATCH")
    fingerprint=source_hash(original)
    if fingerprint!=str(src.get("source_sha256")):raise ValueError("ENGLISH_SOURCE_SHA_MISMATCH")
    print("SOURCE_OK",lesson,lang,len(original),fingerprint[:16],flush=True)
    report["source_sha256"]=fingerprint
    if args.tts_only:
        key=(lesson,lang)
        if key not in EXISTING:raise ValueError("NO_FORMALLY_APPROVED_SOURCE")
        approved=get_drive_json(EXISTING[key],out/"approved.json")
        if approved.get("source")!="en.final.json" or approved.get("source_sha256")!=fingerprint:
            print("LEGACY_QA_SOURCE_MISMATCH",lesson,lang,"existing_source",approved.get("source"),"existing_sha_prefix",str(approved.get("source_sha256"))[:12],flush=True)
            report["legacy_approved_drive_id"]=EXISTING[key]
            report["legacy_approved_sha"]=approved.get("source_sha256")
            report["legacy_revision_status"]="needs_review; translating from current English Final with Gemma instead"
            args.tts_only=False
        if args.tts_only:
            manuscript=approved.get("segments") or []
            if not manuscript:raise ValueError("EMPTY_APPROVED_TRANSLATION")
            if {int(s["id"]) for s in manuscript}!={int(s["id"]) for s in original}:raise ValueError("APPROVED_SEGMENT_IDS_MISMATCH")
            report["translation_status"]="existing_approved_no_retranslation"
    if not args.tts_only:
        client=genai.Client(api_key=os.environ["GEMINI_API_KEY"],http_options={"timeout":90000})
        translated={};issue_by_id={};repair_count=0
        for begin in range(0,len(original),4):
            chunk=original[begin:begin+4]
            try:
                result=translate_batch(client,chunk,lang)
            except Exception as exc:
                print("BATCH_FALLBACK",lesson,lang,begin,type(exc).__name__,str(exc)[:160],flush=True)
                result={int(seg["id"]):translate_one(client,seg,lang) for seg in chunk}
            for seg in chunk:
                sid=int(seg["id"])
                errs=local_check(seg["text"],result.get(sid),lang)
                if errs:
                    result[sid]=repair_one(client,seg,result.get(sid,""),lang,errs)
                    repair_count+=1
            try:
                audits=qa_batch(client,chunk,result,lang)
            except Exception as e:
                print("QA_API_RETRY",lesson,lang,type(e).__name__,str(e)[:180],flush=True)
                audits=qa_batch(client,chunk,result,lang)
            for seg in chunk:
                sid=int(seg["id"])
                failures=local_check(seg["text"],result[sid],lang)
                if sid in audits:failures.append(audits[sid])
                if failures:
                    result[sid]=repair_one(client,seg,result[sid],lang,failures)
                    repair_count+=1
                    failures=local_check(seg["text"],result[sid],lang)
                    if failures:issue_by_id[sid]=failures
            translated.update(result)
            report.update(segments_translated=len(translated),semantic_qa_batches=begin//4+1,repairs=repair_count)
            save()
            print("BATCH_COMPLETED",lesson,lang,len(translated),"/",len(original),"unresolved",len(issue_by_id),flush=True)
            write_json(out/"partial_checkpoint.json",{"lesson":lesson,"language":lang,"source_sha256":fingerprint,"translations":translated,"qa_issues":issue_by_id})
            time.sleep(1)
        if len(translated)!=len(original):raise ValueError("TRANSLATION_INCOMPLETE")
        manuscript=source_to_manuscript(original,translated)
        report["translation_status"]="AI_QA_NEEDS_REVIEW" if issue_by_id else "AI_QA_PASS_NOT_HUMAN_REVIEWED"
        report["unresolved"]=issue_by_id
    if args.tts_only:
        # Keep approved formal manuscript exactly, never rewrite its source.
        write_json(out/"original_approved_reference.json",{"drive_file_id":EXISTING[(lesson,lang)],"source_sha256":fingerprint})
    # Preserve original names in output files. Separate QA doesn't falsely assert human approval.
    sname=LANGS[lang][1]
    prefix=f"第259期_第{int(lesson[-2:])}堂課_{info['title']}_{info['speaker']}_{sname}"
    doc={"task_id":f"P259-{lesson}","language":lang,"language_name":LANGS[lang][0],"engine":"gemma4-26b-a4b-it","model":MODEL,"source":"en.final.json","source_sha256":fingerprint,"qa_status":report["translation_status"],"segments":manuscript}
    write_json(out/(prefix+"翻譯稿資料.json"),doc)
    (out/(prefix+"翻譯稿時間軸.txt")).write_text("\n".join(s["text"] for s in manuscript)+"\n",encoding="utf-8")
    (out/(prefix+"翻譯稿字幕.srt")).write_text("\n\n".join(f"{i}\n{srt_stamp(s['start'])} --> {srt_stamp(s['end'])}\n{s['text']}" for i,s in enumerate(manuscript,1))+"\n",encoding="utf-8")
    print("MANUSCRIPT_COMPLETE",lesson,lang,"segments",len(manuscript),"qa",report["translation_status"],flush=True)
    save()
    audio=asyncio.run(voice_all(manuscript,lang,out))
    mp3=out/"audio.mp3";mp3.rename(out/(prefix+"TTS音檔.mp3"))
    ratio=audio["duration_seconds"]/max(1,audio["source_end_seconds"])
    report["audio_status"]="needs_timeline_review" if abs(ratio-1)>0.04 else "audio_generated_timeline_near_source"
    report["audio_duration_ratio"]=round(ratio,3)
    report["audio"]=audio
    report["finished_utc"]=stamp()
    write_json(out/(prefix+"TTS清單.json"),dict(lesson=lesson,language=lang,source_sha256=fingerprint,voice=LANGS[lang][2],review_status=report["audio_status"],translation_status=report["translation_status"],**audio))
    save()
    # Remove bulky intermediate parts and downloaded source from export artifact.
    import shutil
    shutil.rmtree(out/"parts",ignore_errors=True)
    for name in ("source.en.final.json","approved.json","concat.txt","partial_checkpoint.json"):
        (out/name).unlink(missing_ok=True)
    print("GEMMA_DELIVERY_READY",lesson,lang,"text",len(manuscript),"audio_seconds",audio["duration_seconds"],"bytes",audio["bytes"],"status",report["audio_status"],flush=True)
if __name__=="__main__":
    try:main()
    except BaseException as exc:
        print("GEMMA_RECOVERY_FAIL",type(exc).__name__,str(exc)[:500],flush=True)
        raise
