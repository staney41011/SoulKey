"""Publish verified central human Finals before the original Drive pipeline.

No central Final means keep the existing legacy Final. A newer central revision
is authoritative only after SHA, task, IDs and timeline checks. Archive and verify
the previous Drive JSON before updating it; never touch ASR or AI drafts.
"""
import hashlib
import json
from pathlib import Path


def central_final(task_id, kind, index, backups):
    from central_tts_source import _segments, SourceNotReady
    latest=next((r for r in reversed(index) if len(r)>=3 and r[0]==task_id),None)
    if latest is None:return None
    revision=str(latest[1])
    rows=[r for r in backups if len(r)>=7 and r[0]==task_id and r[1]==revision]
    try:
        count=int(rows[0][3])
        if not 1<=count<=150:raise ValueError()
        parts={}
        for row in rows:
            i=int(row[2])
            if (0<=i<count and int(row[3])==count and row[6]==revision):
                if i in parts and parts[i]!=row[4]:raise ValueError()
                parts[i]=row[4]
        text="".join(parts[i] for i in range(count))
        if hashlib.sha256(text.encode()).hexdigest()!=revision:raise ValueError()
        data=json.loads(text)
        if data.get("task_id")!=task_id or data.get("kind")!=kind:raise ValueError()
        segments=_segments(data.get("segments"))
        if len(segments)!=int(latest[2]):raise ValueError()
        return {**data,"segments":segments,"central_revision":revision}
    except (IndexError,KeyError,TypeError,ValueError) as error:
        raise SourceNotReady("central_final_invalid:"+task_id+":"+kind) from error


def same_segments(a,b):
    def canonical(data):
        return [{"id":int(x["id"]),"start":float(x["start"]),
                 "end":float(x["end"]),"text":str(x["text"]).strip()}
                for x in data.get("segments",[])]
    return canonical(a)==canonical(b)


def publish_readable_finals(drive,folder,name,final,workdir):
    from google_io import find_file,download_drive_file,upload_or_replace_file
    def timestamp(seconds):
        ms=max(0,round(float(seconds)*1000))
        h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    rows=final["segments"]
    files={"txt":"\n".join(x["text"] for x in rows)+"\n",
           "srt":"\n\n".join(f"{i}\n{timestamp(x['start'])} --> {timestamp(x['end'])}\n{x['text']}"
                                 for i,x in enumerate(rows,1))+"\n"}
    for ext,text in files.items():
        label=name[:-5]+"."+ext
        target=Path(workdir)/label;blob=text.encode("utf-8")
        existing=find_file(drive,folder,label)
        if existing:
            prior=Path(workdir)/(label+".previous")
            download_drive_file(drive,existing["id"],prior)
            if prior.read_bytes()==blob:continue
            digest=hashlib.sha256(prior.read_bytes()).hexdigest()
            archive=label+".revision-"+digest
            saved=upload_or_replace_file(drive,folder,prior,archive)
            check=Path(workdir)/archive
            download_drive_file(drive,saved["id"],check)
            if check.read_bytes()!=prior.read_bytes():raise RuntimeError("readable_final_archive_readback_failed")
            current=Path(workdir)/(label+".latest")
            download_drive_file(drive,existing["id"],current)
            if current.read_bytes()!=prior.read_bytes():raise RuntimeError("readable_final_changed_during_sync")
        target.write_bytes(blob)
        saved=upload_or_replace_file(drive,folder,target,label)
        check=Path(workdir)/(label+".readback")
        download_drive_file(drive,saved["id"],check)
        if check.read_bytes()!=blob:raise RuntimeError("readable_final_readback_failed")


def sync_finals(task_id,kinds,workdir,drive=None,sheets=None):
    from config import SPREADSHEET_ID,TASK_SHEET_RANGE
    from google_io import (build_google_services,read_values,find_file,
                           download_drive_file,upload_or_replace_file)
    from lesson_paths import resolve_lesson_folders
    if drive is None or sheets is None:drive,sheets=build_google_services()
    read=lambda r:read_values(sheets,SPREADSHEET_ID,r)
    tasks=[r for r in read(TASK_SHEET_RANGE) if len(r)>=3 and r[0]==task_id]
    if len(tasks)!=1:raise RuntimeError("central_sync_task_not_unique")
    folders=None
    Path(workdir).mkdir(parents=True,exist_ok=True)
    for kind in kinds:
        tab="英文" if kind=="en" else "中文人工"
        index_range=tab+"定稿索引!A2:F10000"
        backup_range=("英文定稿備存" if kind=="en" else "中文人工定稿備存")+"!A2:G15000"
        try:index=read(index_range)
        except Exception as error:
            # Older installations do not have central Final tabs yet.
            if "Unable to parse range" in str(error):continue
            raise
        if not any(r and r[0]==task_id for r in index):continue
        final=central_final(task_id,kind,index,read(backup_range))
        if folders is None:
            folders=resolve_lesson_folders(drive,sheets,int(tasks[0][1]),str(tasks[0][2]))
        folder=folders["translation" if kind=="en" else "transcript"]
        name="en.final.json" if kind=="en" else "zh-TW.final.json"
        existing=find_file(drive,folder,name)
        target=Path(workdir)/name
        if existing:
            previous=Path(workdir)/(name+".previous")
            download_drive_file(drive,existing["id"],previous)
            old=json.loads(previous.read_text(encoding="utf-8"))
            if old.get("task_id") and old["task_id"]!=task_id:
                raise RuntimeError("drive_final_task_mismatch")
            if same_segments(old,final):
                publish_readable_finals(drive,folder,name,final,workdir)
                continue
            # Human revisions retain the exact source IDs and time anchors.
            a=[(x["id"],float(x["start"]),float(x["end"])) for x in old.get("segments",[])]
            b=[(x["id"],float(x["start"]),float(x["end"])) for x in final["segments"]]
            if kind=="zh" and a!=b:
                raise RuntimeError("central_final_timeline_conflict:"+task_id+":"+kind)
            digest=hashlib.sha256(previous.read_bytes()).hexdigest()
            archive=name[:-5]+".revision-"+digest+".json"
            archived=upload_or_replace_file(drive,folder,previous,archive)
            receipt=Path(workdir)/archive
            download_drive_file(drive,archived["id"],receipt)
            if receipt.read_bytes()!=previous.read_bytes():
                raise RuntimeError("previous_final_archive_readback_failed")
            current=Path(workdir)/(name+".latest")
            download_drive_file(drive,existing["id"],current)
            if current.read_bytes()!=previous.read_bytes():
                raise RuntimeError("drive_final_changed_during_sync")
        # Do not publish a revision that changed while the worker was loading.
        if central_final(task_id,kind,read(index_range),read(backup_range))["central_revision"]!=final["central_revision"]:
            raise RuntimeError("central_final_changed_during_sync")
        target.write_text(json.dumps(final,ensure_ascii=False),encoding="utf-8")
        saved=upload_or_replace_file(drive,folder,target,name)
        receipt=Path(workdir)/(name+".readback")
        download_drive_file(drive,saved["id"],receipt)
        observed=json.loads(receipt.read_text(encoding="utf-8"))
        if not same_segments(observed,final):raise RuntimeError("central_final_drive_readback_failed")
        publish_readable_finals(drive,folder,name,final,workdir)
        print("CENTRAL_HUMAN_FINAL_DRIVE_VERIFIED",task_id,kind,final["central_revision"],flush=True)
