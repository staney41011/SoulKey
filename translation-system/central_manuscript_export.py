#!/usr/bin/env python3
"""Publish source-verified P259 manuscripts to their actual lesson Drive folder.

The central Sheet is the source of truth for human English Finals and for
full-coverage, QA-passed AI translations. TTS previously read these records
without writing any manuscript into 02_翻譯稿; this module repairs that gap.

Safe guarantees:
- Do not translate or edit source text.
- Do not export a partial, stale-revision, or unverified AI language.
- Do not overwrite ANY different pre-existing Drive manuscript.
- Every delivered file is downloaded and byte-checked before logging success.
- Files are named through SoulKey's existing canonical-name metadata.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from drive_naming import formal_drive_name
from google_io import download_drive_file, find_file, upload_or_replace_file
from lesson_paths import resolve_lesson_folders
from tts_fingerprint import segments_fingerprint


def _srt_timestamp(seconds):
    millis = max(0, int(round(float(seconds) * 1000)))
    hours, remainder = divmod(millis, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    secs, milli = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milli:03d}"


def manuscript_files(task_id, lang, final, approved):
    """Pure bytes, safe to test offline. No Drive/Sheets or model calls."""
    source = approved["segments"]
    if not source:
        raise ValueError("source_has_no_segments")
    if lang != "en" and approved["job_id"] == "human-final":
        raise ValueError("unverified_ai_translation")
    seen = set()
    normalized = []
    for row in source:
        sid = int(row["id"])
        start, end = float(row["start"]), float(row["end"])
        text = str(row["text"]).strip()
        if sid in seen or not text or start < 0 or end < start:
            raise ValueError("invalid_manuscript_segment")
        seen.add(sid)
        normalized.append({"id": sid, "start": start, "end": end, "text": text})
    stem = "en.final" if lang == "en" else lang
    sha = segments_fingerprint(normalized)
    payload = {
        "task_id": task_id, "language": lang,
        "kind": "en" if lang == "en" else "translation",
        "source": "human-approved-english" if lang == "en" else "central-passed-qa",
        "en_backup_revision": final["revision"],
        "verified_translation_job": approved["job_id"],
        "source_sha256": sha,
        "segments": normalized,
    }
    transcript = "\n".join(row["text"] for row in normalized) + "\n"
    srt = "\n\n".join(
        f"{i}\n{_srt_timestamp(row['start'])} --> "
        f"{_srt_timestamp(row['end'])}\n{row['text']}"
        for i, row in enumerate(normalized, 1)
    ) + "\n"
    return {
        stem + ".json": json.dumps(
            payload, ensure_ascii=False, indent=2
        ).encode("utf-8"),
        stem + ".txt": transcript.encode("utf-8"),
        stem + ".srt": srt.encode("utf-8"),
    }


def _same_existing(name, actual, expected):
    if actual == expected:
        return True
    if not name.endswith(".json"):
        return False
    # Existing en.final.json may have been authored manually and legitimately
    # use a different JSON layout. It is equivalent only when all source IDs,
    # times and human text match. Never compare by filename alone.
    try:
        old = json.loads(actual)
        new = json.loads(expected)
        if not isinstance(old, dict) or not isinstance(new, dict):
            return False
        def canonical(rows):
            return [
                (int(r["id"]), float(r["start"]), float(r["end"]),
                 str(r["text"]).strip())
                for r in rows
            ]
        if canonical(old.get("segments", [])) != canonical(new["segments"]):
            return False
        old_rev = str(old.get("en_backup_revision") or "")
        if old_rev and old_rev != new["en_backup_revision"]:
            return False
        old_job = str(old.get("verified_translation_job") or "")
        if old_job and old_job != new["verified_translation_job"]:
            return False
        return True
    except (ValueError, KeyError, TypeError, OverflowError):
        return False


def upload_verified_file(drive, folder_id, name, blob, task, workdir):
    """No overwrites of different content. Always read existing/uploaded bytes."""
    workdir.mkdir(parents=True, exist_ok=True)
    expected = workdir / name
    expected.write_bytes(blob)
    existing = find_file(drive, folder_id, name)
    if existing:
        old_path = workdir / ("existing." + name)
        download_drive_file(drive, existing["id"], old_path)
        if not _same_existing(name, old_path.read_bytes(), blob):
            raise RuntimeError("drive_manuscript_conflict:" + name)
        result = {"id": existing["id"]}
        action = "reused"
    else:
        result = upload_or_replace_file(
            drive, folder_id, expected, name,
            display_name=formal_drive_name(task, name)
        )
        action = "created"
    check = workdir / ("readback." + name)
    download_drive_file(drive, result["id"], check)
    if not _same_existing(name, check.read_bytes(), blob):
        raise RuntimeError("drive_manuscript_readback_mismatch:" + name)
    print(
        "CENTRAL_MANUSCRIPT_FILE_VERIFIED", task["task_id"], name,
        action, len(blob), hashlib.sha256(blob).hexdigest(), flush=True,
    )
    return result


def publish_manuscript(drive, sheets, task, lang, final, approved, workdir):
    """Publish 3 native files per approved language to 02_翻譯稿."""
    folders = resolve_lesson_folders(
        drive, sheets, task["period"], task["lesson"]
    )
    destination = folders["translation"]
    files = manuscript_files(task["task_id"], lang, final, approved)
    # Check existing JSON provenance first to fail closed before writing TXT.
    ordered = sorted(files, key=lambda x: (
        0 if x.endswith(".json") else 1 if x.endswith(".txt") else 2
    ))
    for name in ordered:
        upload_verified_file(
            drive, destination, name, files[name], task, workdir
        )
    print(
        "CENTRAL_MANUSCRIPT_DRIVE_VERIFIED",
        task["task_id"], lang, len(files),
        final["revision"], flush=True,
    )
    return len(files)


def main():
    import argparse
    from config import SPREADSHEET_ID, TASK_SHEET_RANGE
    from google_io import build_google_services, read_values
    from central_tts_source import (
        SourceNotReady, verified_english_final, verified_translation
    )
    from central_tts_recovery import approved_plan_rows, ready_tasks

    parser = argparse.ArgumentParser()
    parser.add_argument("--period", type=int, default=259)
    parser.add_argument("--task-id", default="")
    args = parser.parse_args()
    if args.period != 259:
        raise SystemExit("central_export_is_259_only")

    drive, sheets = build_google_services()
    get = lambda name: read_values(sheets, SPREADSHEET_ID, name)
    indexes = get("英文定稿索引!A2:F10000")
    backups = get("英文定稿備存!A2:G10000")
    translations = get("多語翻譯結果!A2:G50000")
    qa = get("翻譯QA紀錄!A2:I5000")
    plans = get("語言任務設定!A2:J5000")
    finished = errors = 0
    for task in ready_tasks(sheets, args.period, args.task_id):
        try:
            final = verified_english_final(
                task["task_id"], indexes, backups
            )
        except SourceNotReady as error:
            print("MANUSCRIPT_SKIP_NO_FINAL", task["task_id"], error, flush=True)
            errors += 1
            continue
        for lang in approved_plan_rows(plans, task["task_id"]):
            # Only export if transcription is enabled, not merely audio.
            plan = next(
                (r for r in plans if len(r) >= 7
                 and r[0] == task["task_id"] and r[1] == lang), []
            )
            if len(plan) < 4 or str(plan[3]).upper() != "TRUE":
                continue
            try:
                approved = verified_translation(
                    task["task_id"], lang, final, translations, qa
                )
            except SourceNotReady as error:
                print("MANUSCRIPT_WAIT_FOR_QA", task["task_id"], lang,
                      error, flush=True)
                continue
            workdir = Path(
                os.environ.get("SOULKEY_MANUSCRIPT_WORKDIR",
                               "./soulkey-manuscripts")
            ) / task["task_id"] / lang
            try:
                publish_manuscript(
                    drive, sheets, task, lang, final, approved, workdir
                )
                finished += 1
            except Exception as error:
                errors += 1
                print("MANUSCRIPT_EXPORT_ERROR", task["task_id"], lang,
                      type(error).__name__, str(error)[:300], flush=True)
    print("CENTRAL_MANUSCRIPT_EXPORT_SUMMARY",
          "verified_languages", finished, "errors", errors, flush=True)
    if errors:
        raise SystemExit("manuscript_export_incomplete")


if __name__ == "__main__":
    main()
