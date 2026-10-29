"""Read-only, source-verified central Sheet -> legacy Natural TTS adapter.

No text is rewritten here. Only manually approved English Final and complete
QA-approved per-language translations can enter the old production TTS engine.
"""
import hashlib
import json

class SourceNotReady(RuntimeError):
    pass

def _id(value):
    try:
        v=int(value)
        if v<0:raise ValueError()
        return v
    except (ValueError,TypeError):
        raise SourceNotReady("invalid_source_segment_id")

def _segments(rows):
    if not isinstance(rows,list) or not rows:raise SourceNotReady("source_segments_empty")
    result=[];seen=set()
    for row in rows:
        if not isinstance(row,dict):raise SourceNotReady("invalid_source_segment")
        sid=_id(row.get("id"))
        if sid in seen:raise SourceNotReady("duplicate_source_segment_id")
        seen.add(sid)
        try:
            start=float(row["start"]);end=float(row["end"])
        except (ValueError,TypeError,KeyError):
            raise SourceNotReady("source_timeline_invalid")
        text=str(row.get("text") or "").strip()
        if not (0<=start<=end and text):
            raise SourceNotReady("source_timeline_or_text_invalid")
        result.append({"id":sid,"start":start,"end":end,"text":text})
    return result

def verified_english_final(task,index_rows,backup_rows):
    latest=None
    for row in index_rows:
        if len(row)>=3 and row[0]==task and len(str(row[1]))==64:
            latest=row
    if latest is None:raise SourceNotReady("english_final_missing")
    revision=latest[1]
    relevant=[r for r in backup_rows if len(r)>=7 and
              r[0]==task and r[1]==revision and r[6]==revision]
    if not relevant:raise SourceNotReady("english_backup_missing")
    try:count=int(relevant[0][3])
    except (ValueError,TypeError):raise SourceNotReady("english_backup_chunk_count_invalid")
    if count<1 or count>100:raise SourceNotReady("english_backup_chunk_count_invalid")
    chunks={}
    for row in relevant:
        try:idx=int(row[2])
        except (ValueError,TypeError):continue
        if 0<=idx<count and str(row[3])==str(count) and idx not in chunks:
            chunks[idx]=row[4]
    if len(chunks)!=count:raise SourceNotReady("english_backup_incomplete")
    payload="".join(chunks[i] for i in range(count))
    if hashlib.sha256(payload.encode("utf-8")).hexdigest()!=revision:
        raise SourceNotReady("english_backup_hash_mismatch")
    try:data=json.loads(payload)
    except (ValueError,TypeError):raise SourceNotReady("english_backup_json_invalid")
    if data.get("task_id")!=task or data.get("kind")!="en":
        raise SourceNotReady("english_backup_task_mismatch")
    segments=_segments(data.get("segments"))
    if len(segments)!=int(latest[2]):
        raise SourceNotReady("english_backup_segment_count_mismatch")
    return {"revision":revision,"segments":segments,"task_id":task}

def verified_translation(task,lang,final,translation_rows,quality_rows):
    """Accept past jobs only when a matching QA receipt proves entire coverage."""
    if lang=="en":
        return {"segments":final["segments"],"job_id":"human-final",
                "revision":final["revision"]}
    ids=[str(x["id"]) for x in final["segments"]]
    allowed=set(ids);rev=final["revision"]
    receipts=[r for r in quality_rows if len(r)>=8 and r[1]==task and
              r[2]==rev and r[3]==lang and r[7]=="passed"]
    for proof in reversed(receipts):
        job=proof[0]
        selected=[r for r in translation_rows if len(r)>=6 and r[0]==task
                  and r[1]==rev and r[2]==lang and r[5]==job]
        texts={};valid=True
        for row in selected:
            sid=str(row[3]);text=str(row[4]).strip()
            if sid not in allowed or sid in texts or not text:
                valid=False;break
            texts[sid]=text
        if not valid or set(texts)!=allowed:continue
        if all(texts[str(row["id"])]==row["text"] for row in final["segments"]):
            continue # Reject an English-copy "translation".
        return {"revision":rev,"job_id":job,
                "segments":[{**row,"text":texts[str(row["id"])]}
                            for row in final["segments"]]}
    raise SourceNotReady("translation_not_fully_qa_verified:"+lang)
