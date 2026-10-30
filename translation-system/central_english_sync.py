#!/usr/bin/env python3
"""Restore missing legacy Drive en.final.json from the verified central Sheet.

Never overwrite a pre-existing English Final, never regenerate text and never
trust a saved translation without matching the central SHA-256 backed final.
"""
import argparse
import json
from pathlib import Path

from central_tts_source import verified_english_final
from config import SPREADSHEET_ID, TASK_SHEET_RANGE
from google_io import (build_google_services, download_drive_file, find_file,
                       read_values, upload_or_replace_file)
from lesson_paths import resolve_lesson_folders


def canonical(segments):
    return [
        {"id": int(x["id"]), "start": float(x["start"]),
         "end": float(x["end"]), "text": str(x["text"]).strip()}
        for x in segments
    ]


def sync(task_id, workdir):
    drive, sheets = build_google_services()
    rows = read_values(sheets, SPREADSHEET_ID, TASK_SHEET_RANGE)
    candidates = [r for r in rows if len(r) >= 3 and str(r[0]).strip() == task_id]
    if len(candidates) != 1:
        raise RuntimeError("central_english_task_not_unique:" + task_id)
    task = candidates[0]
    index = read_values(sheets, SPREADSHEET_ID, "英文定稿索引!A2:F10000")
    backup = read_values(sheets, SPREADSHEET_ID, "英文定稿備存!A2:G10000")
    final = verified_english_final(task_id, index, backup)
    folders = resolve_lesson_folders(drive, sheets, int(task[1]), str(task[2]))
    folder_id = folders["translation"]
    workdir.mkdir(parents=True, exist_ok=True)
    existing = find_file(drive, folder_id, "en.final.json")
    if existing:
        target = workdir / "en.final.existing.json"
        download_drive_file(drive, existing["id"], target)
        payload = json.loads(target.read_text(encoding="utf-8"))
        if canonical(payload.get("segments") or []) != canonical(final["segments"]):
            raise RuntimeError(
                "drive_english_final_conflicts_with_verified_central_sheet:"
                + task_id
            )
        print("CENTRAL_EN_DRIVE_REUSED", task_id, final["revision"], flush=True)
        return

    payload = {
        "task_id": task_id,
        "kind": "en",
        "segments": final["segments"],
        "verified_source": "central_sheet_english_backup",
        "en_backup_revision": final["revision"]
    }
    target = workdir / "en.final.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    saved = upload_or_replace_file(drive, folder_id, target, "en.final.json")
    check = workdir / "en.final.readback.json"
    download_drive_file(drive, saved["id"], check)
    checked = json.loads(check.read_text(encoding="utf-8"))
    if canonical(checked.get("segments") or []) != canonical(final["segments"]):
        raise RuntimeError("central_english_final_drive_readback_mismatch")
    print("CENTRAL_EN_DRIVE_VERIFIED", task_id, final["revision"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    args = parser.parse_args()
    if args.task_id not in {"P259-L01", "P259-L02", "P259-L03", "P259-L04"}:
        raise SystemExit("Only P259 period is enabled for this recovery")
    sync(args.task_id, Path("/kaggle/working/central-en-sync") / args.task_id)
