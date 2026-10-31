"""Append-only, unverified Gemma drafts in the lesson's existing log folder.

Snapshots never write to formal manuscripts or QA tables. Every resumed draft
must pass the complete current-run QA again; semantic pass caches stay local.
"""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re

def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")

def payload_for(task_id,lang,revision,source_ids,segments):
    if not re.fullmatch(r"P259-L0[1-4]",task_id) or not re.fullmatch(r"[a-z]{2}",lang) or not re.fullmatch(r"[0-9a-f]{64}",revision):
        raise ValueError("invalid_draft_identity")
    ids=[int(sid) for sid in source_ids]
    if not ids or not all(isinstance(row.get("text"),str) for row in segments):
        raise ValueError("invalid_draft_segments")
    rows=[{"id":int(row["id"]),"text":row["text"].strip()} for row in segments]
    if len(set(ids))!=len(ids) or [row["id"] for row in rows]!=ids or not all(row["text"] and len(row["text"])<=15000 for row in rows):
        raise ValueError("invalid_draft_segments")
    payload={"version":1,"status":"needs_review","task_id":task_id,"language":lang,
             "source_revision":revision,"source_ids":ids,"segments":rows}
    payload["sha256"]=hashlib.sha256(canonical(payload)).hexdigest()
    return payload

def checked_payload(payload,task_id,lang,revision,source_ids):
    if not isinstance(payload,dict):raise ValueError("invalid_draft_payload")
    expected=payload_for(task_id,lang,revision,source_ids,payload.get("segments",[]))
    if payload!=expected:raise ValueError("draft_identity_or_integrity_mismatch")
    return expected

def list_snapshots(drive,folder):
    from google_io import list_child_files
    return list_child_files(drive,folder)

def download_snapshot(drive,file_id,destination):
    from google_io import download_drive_file
    download_drive_file(drive,file_id,destination)

def create_snapshot(drive,folder,path,name):
    # Never update a previous draft: a new file preserves every older snapshot
    # and any human changes. Ambiguous creates may duplicate bytes, not erase.
    from googleapiclient.http import MediaFileUpload
    return drive.files().create(
        body={"name":name,"parents":[folder],
              "description":"Unverified translation checkpoint; not a formal manuscript or QA receipt."},
        media_body=MediaFileUpload(str(path),mimetype="application/json",resumable=True),
        fields="id",supportsAllDrives=True).execute(num_retries=3)

class DraftCheckpoint:
    def __init__(self,drive,folder,workdir,task_id,lang,revision,source_ids):
        self.drive,self.folder=drive,folder
        self.workdir=Path(workdir);self.workdir.mkdir(parents=True,exist_ok=True)
        self.task_id,self.lang,self.revision=task_id,lang,revision
        self.source_ids=list(source_ids)
        # Validate every identity before it can be used in a filename.
        payload_for(task_id,lang,revision,self.source_ids,
                    [{"id":sid,"text":"identity check"} for sid in self.source_ids])
        self.prefix="gemma4-draft--"+task_id+"--"+lang+"--"+revision+"--"
        self.last_sha=None

    def load(self):
        files=[item for item in list_snapshots(self.drive,self.folder)
               if str(item.get("name","")).startswith(self.prefix) and str(item.get("name","")).endswith(".json")]
        if not files:return None
        latest=max(files,key=lambda item:(str(item.get("modifiedTime", "")),str(item["name"])))
        path=self.workdir/"resumed-draft.json"
        download_snapshot(self.drive,latest["id"],path)
        try:
            payload=checked_payload(json.loads(path.read_text(encoding="utf-8")),self.task_id,self.lang,self.revision,self.source_ids)
        except (ValueError,TypeError,KeyError):
            # Preserve a modified/corrupt draft for review instead of replacing
            # it with a newly translated candidate or an older snapshot.
            raise RuntimeError("gemma_draft_checkpoint_identity_or_integrity_error") from None
        self.last_sha=payload["sha256"]
        print("GEMMA4_DRAFT_REUSED",self.task_id,self.lang,len(payload["segments"]),flush=True)
        return payload["segments"]

    def save(self,segments):
        payload=payload_for(self.task_id,self.lang,self.revision,self.source_ids,segments)
        if payload["sha256"]==self.last_sha:return
        stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        name=self.prefix+stamp+"-"+payload["sha256"]+".json"
        path=self.workdir/"new-draft.json";blob=canonical(payload);path.write_bytes(blob)
        uploaded=create_snapshot(self.drive,self.folder,path,name)
        check=self.workdir/"readback-draft.json"
        download_snapshot(self.drive,uploaded["id"],check)
        if check.read_bytes()!=blob:raise RuntimeError("gemma_draft_checkpoint_readback_mismatch")
        self.last_sha=payload["sha256"]
        print("GEMMA4_DRAFT_CHECKPOINT_VERIFIED",self.task_id,self.lang,len(segments),flush=True)
