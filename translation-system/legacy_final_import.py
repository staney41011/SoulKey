"""Keep newer human Drive Finals authoritative after retiring the cloud service.

Publish an append-only, SHA-verified Sheet receipt through the original owner's
Apps Script runtime credentials. Never replace the Drive Final or old backups.
"""
import hashlib
import json
from datetime import datetime


def _stamp(value):
    try:
        result=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        if result.tzinfo is None:raise ValueError()
        return result
    except (ValueError,TypeError):
        raise RuntimeError("human_final_revision_time_unverified") from None


def newer_legacy_final(task_id,kind,legacy,central):
    from central_tts_source import _segments
    if not legacy.get("finalized_at"):return None
    if legacy.get("task_id",task_id)!=task_id or legacy.get("kind",kind)!=kind:
        raise RuntimeError("legacy_human_final_identity_mismatch")
    before=_stamp(central.get("central_finalized_at") or central.get("finalized_at"))
    after=_stamp(legacy["finalized_at"])
    if after<before:return None
    if after==before:raise RuntimeError("human_final_same_time_content_conflict")
    return {"task_id":task_id,"kind":kind,"source":"legacy-human-final",
            "finalized_at":legacy["finalized_at"],"segments":_segments(legacy.get("segments"))}


def publish_legacy_final(task_id,kind,payload,prior,sheets,verify_drive_unchanged):
    from config import SPREADSHEET_ID
    from google_io import read_values
    from central_final_sync import central_final
    index_tab="英文定稿索引" if kind=="en" else "中文人工定稿索引"
    backup_tab="英文定稿備存" if kind=="en" else "中文人工定稿備存"
    index_range=index_tab+"!A2:F10000"
    backup_range=backup_tab+"!A2:G15000"
    read=lambda area:read_values(sheets,SPREADSHEET_ID,area)
    text=json.dumps(payload,ensure_ascii=False,separators=(",",":"))
    revision=hashlib.sha256(text.encode("utf-8")).hexdigest()
    chunks=[text[i:i+20000] for i in range(0,len(text),20000)]
    if not 1<=len(chunks)<=100:raise RuntimeError("legacy_final_backup_too_large")
    values=sheets.spreadsheets().values()
    def append(tab,rows):
        # Do not blindly retry append after an uncertain network response.
        # The next run can discover these immutable rows by their source hash.
        result=values.append(spreadsheetId=SPREADSHEET_ID,range="'"+tab+"'!A1",
          valueInputOption="RAW",insertDataOption="INSERT_ROWS",
          body={"values":rows}).execute(num_retries=0)
        area=result.get("updates",{}).get("updatedRange")
        if not area or read(area)!=rows:raise RuntimeError("legacy_final_write_readback_failed")
    existing=read(backup_range)
    missing=[]
    for number,chunk in enumerate(chunks):
        row=[task_id,revision,str(number),str(len(chunks)),chunk,payload["finalized_at"],revision]
        seen=[r for r in existing if len(r)>=7 and r[:3]==row[:3]]
        if any(r!=row for r in seen):raise RuntimeError("legacy_final_backup_conflict")
        if not seen:missing.append(row)
    if missing:append(backup_tab,missing)
    if not verify_drive_unchanged():raise RuntimeError("drive_final_changed_during_import")
    current=central_final(task_id,kind,read(index_range),read(backup_range))
    if current["central_revision"]!=prior["central_revision"]:
        raise RuntimeError("central_final_changed_during_import")
    append(index_tab,[[task_id,revision,str(len(payload["segments"])),
      payload["finalized_at"],"google-sheet","legacy-apps-script-kaggle"]])
    final=central_final(task_id,kind,read(index_range),read(backup_range))
    if final["central_revision"]!=revision:raise RuntimeError("legacy_final_publication_unverified")
    print("LEGACY_HUMAN_FINAL_SHEET_VERIFIED",task_id,kind,revision,flush=True)
    return final
