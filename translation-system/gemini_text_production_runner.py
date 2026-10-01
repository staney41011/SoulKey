import argparse
import hashlib
import json
import os
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from config import (
    COL,
    GLOSSARY_FULL_RANGE,
    SPREADSHEET_ID,
    TASK_SHEET_RANGE,
    TIMEZONE,
)
from gemini_engine import (
    DEFAULT_TEXT_MODEL,
    GeminiClient,
    normalize_segments,
    parse_glossary_rows,
    semantic_polish_zh,
)
from github_review_cache import publish_review_cache
from drive_naming import formal_drive_name
from google_io import (
    build_google_services,
    download_drive_file,
    find_file,
    get_secret,
    read_values,
    update_cells,
    upload_or_replace_file,
)
from lesson_paths import digits, resolve_lesson_folders
from status_io import new_run_id, mark_done, mark_error, mark_running


TEXT_SCHEMA = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "text": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["id", "text", "notes"],
            },
        }
    },
    "required": ["segments"],
}


def source_fingerprint(segments):
    canonical = [
        {
            "id": int(x.get("id", i)),
            "start": float(x.get("start", 0) or 0),
            "end": float(x.get("end", 0) or 0),
            "text": str(x.get("text") or ""),
        }
        for i, x in enumerate(segments or [])
    ]
    raw = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def now_text():
    return datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")


def pad_row(row, length=20):
    return list(row) + [""] * max(0, length - len(row))


def find_task(sheets, task_id):
    for index, raw in enumerate(
        read_values(sheets, SPREADSHEET_ID, TASK_SHEET_RANGE),
        start=2,
    ):
        row = pad_row(raw, 20)
        if str(row[COL["task_id"]] or "").strip() != task_id:
            continue
        return {
            "sheet_row": index,
            "task_id": task_id,
            "period": digits(row[COL["period"]]),
            "lesson": str(row[COL["lesson"]] or "").strip(),
            "title": str(row[COL["title"]] or "").strip(),
            "lecturer": str(row[COL["lecturer"]] or "").strip(),
        }
    return None


def format_srt_time(seconds):
    ms = max(0, int(round(float(seconds) * 1000)))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, milli = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{milli:03d}"


def plain_time(seconds):
    total = max(0, int(float(seconds)))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def write_result_set(output_dir, stem, segments, extra=None):
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{stem}.json"
    txt_path = output_dir / f"{stem}.txt"
    srt_path = output_dir / f"{stem}.srt"

    payload = dict(extra or {})
    payload["segments"] = segments
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    txt_path.write_text(
        "\n".join(str(x["text"]).strip() for x in segments) + "\n",
        encoding="utf-8",
    )
    blocks = []
    for order, seg in enumerate(segments, start=1):
        blocks.append(
            f"{order}\n"
            f"{format_srt_time(seg['start'])} --> {format_srt_time(seg['end'])}\n"
            f"{seg['text']}"
        )
    srt_path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    return {"json": json_path, "txt": txt_path, "srt": srt_path}


def download_json(drive, folder_id, name, destination):
    item = find_file(drive, folder_id, name)
    if not item:
        return None
    download_drive_file(drive, item["id"], destination)
    return destination


def glossary_for_batch(glossary, batch_text, target=None, limit=80):
    haystack = str(batch_text or "").lower()
    rows = []
    for item in glossary:
        zh = str(item.get("zh") or "").strip()
        en = str(item.get("en") or "").strip()
        if not ((zh and zh.lower() in haystack) or (en and en.lower() in haystack)):
            continue
        source = zh or en
        if target == "en":
            mapped = en
        else:
            mapped = ""
        lock = "LOCKED" if item.get("locked") else "preferred"
        if mapped:
            rows.append(f"- {source} => {mapped} [{lock}]")
        else:
            rows.append(f"- {source} [{lock}]")
        if len(rows) >= limit:
            break
    return "\n".join(rows) or "(no matching glossary entries)"


def validate_ids(batch, returned):
    expected = sorted(int(x["id"]) for x in batch)
    got = sorted(int(x.get("id")) for x in returned if "id" in x)
    if expected != got:
        raise RuntimeError(f"Gemini segment id 不完整：expected={expected}, got={got}")


def transform_segments(client, source_segments, glossary_rows, mode, chunk_size=12):
    source_segments = normalize_segments({"segments": source_segments})
    glossary = parse_glossary_rows(glossary_rows)
    out = []

    if mode == "vernacular":
        system = (
            "你是「打開心靈的鎖匙」白話文轉寫器。"
            "把人工定稿的繁體中文改寫成清楚自然的現代繁體中文，"
            "但不得摘要、不得新增教義、不得刪除例子、數字、人名或邏輯關係。"
            "佛堂與道場專有名詞要保留正確概念。"
        )
        target = None
    elif mode == "en":
        system = (
            "You are the English translation engine for the SoulKey religious education course. "
            "Translate the approved Traditional Chinese source faithfully into clear natural English. "
            "Preserve every idea, number, name, example and logical relationship. "
            "Do not summarize, omit, embellish or add doctrine. LOCKED glossary mappings are mandatory."
        )
        target = "en"
    else:
        raise ValueError(mode)

    for offset in range(0, len(source_segments), chunk_size):
        batch = source_segments[offset:offset + chunk_size]
        batch_text = "\n".join(x["text"] for x in batch)
        glossary_text = glossary_for_batch(glossary, batch_text, target=target)
        if mode == "vernacular":
            instruction = (
                "逐段轉成現代繁體中文。保留每個 id，不合併、不拆分、不重新排序。"
            )
        else:
            instruction = (
                "Translate every segment into English. Keep every id exactly; do not merge, split or reorder."
            )
        prompt = (
            f"Glossary:\n{glossary_text}\n\n{instruction}\n"
            + json.dumps(
                [{"id": x["id"], "text": x["text"]} for x in batch],
                ensure_ascii=False,
            )
        )
        parsed, _ = client.structured(
            prompt,
            TEXT_SCHEMA,
            system_instruction=system,
            thinking_level="low",
        )
        returned = parsed.get("segments") or []
        validate_ids(batch, returned)
        by_id = {int(x["id"]): x for x in returned}
        for src in batch:
            row = by_id[int(src["id"])]
            text = str(row.get("text") or "").strip()
            if not text:
                raise RuntimeError(f"Gemini 回傳空文字：segment {src['id']}")
            out.append({
                "id": int(src["id"]),
                "start": float(src["start"]),
                "end": float(src["end"]),
                "text": text,
                "notes": str(row.get("notes") or "").strip(),
            })
    return out


def align_english_cc(review_payload, cc_payload):
    cc_segments = cc_payload.get("segments") or []
    for item in review_payload.get("segments") or []:
        start = float(item.get("start") or 0)
        end = float(item.get("end") or start)
        matched = []
        seen = set()
        for cue in cc_segments:
            cue_start = float(cue.get("start") or 0)
            cue_end = float(cue.get("end") or cue_start)
            if cue_end <= start or cue_start >= end:
                continue
            text = re.sub(r"\s+", " ", str(cue.get("text") or "")).strip()
            if text and text not in seen:
                seen.add(text)
                matched.append(text)
        source_en = " ".join(matched).strip()
        item["source_en"] = source_en
        item["en_text"] = source_en
        item["en_confirmed"] = False
    review_payload["english_cc_available"] = bool(cc_segments)
    review_payload["english_cc_language"] = str(cc_payload.get("language") or "en")
    review_payload["english_cc_source"] = (
        "youtube_caption" if cc_segments else ""
    )


def stage_polish(client, drive, sheets, task, folders, glossary_rows, workdir):
    src = workdir / "segments.json"
    if not download_json(drive, folders["transcript"], "segments.json", src):
        raise RuntimeError("找不到 01_中文逐字稿/segments.json")

    source_payload = json.loads(src.read_text(encoding="utf-8"))
    source_segments = normalize_segments(source_payload)
    result = semantic_polish_zh(
        client,
        source_segments,
        glossary_rows=glossary_rows,
        chunk_size=12,
    )

    polished = [
        {
            "id": int(x["id"]),
            "start": float(x["start"]),
            "end": float(x["end"]),
            "text": str(x["text"]),
        }
        for x in result["segments"]
    ]

    output = write_result_set(
        workdir / "polish",
        "zh-TW.polished",
        polished,
        {
            "engine": "gemini",
            "model": client.text_model,
            "transcript_source": source_payload.get("transcript_source") or "unknown",
            "source": "segments.json",
            "source_sha256": source_fingerprint(source_segments),
        },
    )
    for key, name in [
        ("json", "zh-TW.polished.json"),
        ("txt", "zh-TW.polished.txt"),
        ("srt", "zh-TW.polished.srt"),
    ]:
        upload_or_replace_file(
            drive,
            folders["transcript"],
            output[key],
            name,
            display_name=formal_drive_name(task, name),
        )

    report_path = workdir / "polish" / "polish_report.json"
    report_path.write_text(
        json.dumps(
            {
                "engine": "gemini",
                "model": client.text_model,
                "changed_count": result["changed_count"],
                "term_candidates": result["term_candidates"],
                "source": "segments.json",
                "source_sha256": source_fingerprint(source_segments),
                "segments": polished,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    upload_or_replace_file(
        drive,
        folders["transcript"],
        report_path,
        "polish_report.json",
        display_name=formal_drive_name(task, "polish_report.json"),
    )

    by_id = {int(x["id"]): x for x in result["segments"]}
    review_payload = {
        "version": 5,
        "generated_at": now_text(),
        "total_segments": len(source_segments),
        "segments": [],
    }
    for src_seg in source_segments:
        sid = int(src_seg["id"])
        polished_row = by_id[sid]
        changed = str(polished_row["text"]) != str(src_seg["text"])
        review_payload["segments"].append({
            "id": sid,
            "start": float(src_seg["start"]),
            "end": float(src_seg["end"]),
            "time": plain_time(src_seg["start"]),
            "raw": str(src_seg["text"]),
            "text": str(polished_row["text"]),
            "flags": ["changed"] if changed else [],
            "source_en": "",
            "en_text": "",
            "en_confirmed": False,
        })

    cc_path = workdir / "youtube.en.json"
    if download_json(drive, folders["source"], "youtube.en.json", cc_path):
        try:
            align_english_cc(
                review_payload,
                json.loads(cc_path.read_text(encoding="utf-8")),
            )
        except Exception as exc:
            print(f"[CC ALIGN] 略過：{type(exc).__name__}: {exc}", flush=True)

    review_path = workdir / "polish" / "zh-TW.review-cache.json"
    review_path.write_text(
        json.dumps(review_payload, ensure_ascii=False),
        encoding="utf-8",
    )
    review_publish = publish_review_cache(task["task_id"], review_path)
    review_cache_ready = not (
        isinstance(review_publish, dict)
        and review_publish.get("ok") is False
    )
    if review_publish is None:
        review_cache_ready = False

    update_cells(
        sheets,
        SPREADSHEET_ID,
        {
            f"任務佇列!I{task['sheet_row']}": "完成",
            f"任務佇列!S{task['sheet_row']}": now_text(),
            f"任務佇列!T{task['sheet_row']}": (
                f"Gemini中文校稿完成；修改{result['changed_count']}段；"
                + (
                    "GitHub人工定稿快取已建立；待人工中文定稿"
                    if review_cache_ready
                    else "GitHub人工定稿快取未建立，Studio將改由Drive直接載入"
                )
            ),
        },
    )
    return (
        f"Gemini中文校稿完成；修改{result['changed_count']}段；"
        + ("review_cache=ready" if review_cache_ready else "review_cache=drive_fallback")
    )


def stage_vernacular(client, drive, sheets, task, folders, glossary_rows, workdir):
    src = workdir / "zh-TW.final.json"
    if not download_json(drive, folders["transcript"], "zh-TW.final.json", src):
        raise RuntimeError("找不到 zh-TW.final.json；請先完成人工中文定稿")
    payload = json.loads(src.read_text(encoding="utf-8"))
    source_segments = payload.get("segments") or []
    rows = transform_segments(
        client,
        source_segments,
        glossary_rows,
        "vernacular",
    )
    output = write_result_set(
        workdir / "vernacular",
        "zh-TW.vernacular",
        rows,
        {
            "engine": "gemini",
            "model": client.text_model,
            "source": "zh-TW.final.json",
            "source_sha256": source_fingerprint(source_segments),
        },
    )
    for key in ("json", "txt", "srt"):
        canonical_name = Path(output[key]).name
        upload_or_replace_file(
            drive,
            folders["translation"],
            output[key],
            canonical_name,
            display_name=formal_drive_name(task, canonical_name),
        )
    update_cells(
        sheets,
        SPREADSHEET_ID,
        {
            f"任務佇列!S{task['sheet_row']}": now_text(),
            f"任務佇列!T{task['sheet_row']}": (
                "Gemini白話文完成；待人工白話文定稿"
            ),
        },
    )
    return "Gemini白話文完成；待人工白話文定稿"


def stage_en(client, drive, sheets, task, folders, glossary_rows, workdir):
    candidates = [
        (folders["translation"], "zh-TW.vernacular.final.json"),
        (folders["transcript"], "zh-TW.final.json"),
    ]
    source_path = None
    source_name = None
    for folder, name in candidates:
        candidate = workdir / name
        if download_json(drive, folder, name, candidate):
            source_path = candidate
            source_name = name
            break
    if not source_path:
        raise RuntimeError(
            "找不到 zh-TW.vernacular.final.json 或 zh-TW.final.json"
        )

    payload = json.loads(source_path.read_text(encoding="utf-8"))
    rows = transform_segments(
        client,
        payload.get("segments") or [],
        glossary_rows,
        "en",
    )
    output = write_result_set(
        workdir / "en",
        "en",
        rows,
        {
            "engine": "gemini",
            "model": client.text_model,
            "source": source_name,
            "source_sha256": source_fingerprint(payload.get("segments") or []),
        },
    )
    for key in ("json", "txt", "srt"):
        canonical_name = Path(output[key]).name
        upload_or_replace_file(
            drive,
            folders["translation"],
            output[key],
            canonical_name,
            display_name=formal_drive_name(task, canonical_name),
        )
    update_cells(
        sheets,
        SPREADSHEET_ID,
        {
            f"任務佇列!J{task['sheet_row']}": "完成",
            f"任務佇列!S{task['sheet_row']}": now_text(),
            f"任務佇列!T{task['sheet_row']}": (
                f"Gemini英文完成；來源={source_name}；待人工English Final"
            ),
        },
    )
    return f"Gemini英文完成；來源={source_name}；待人工English Final"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    parser.add_argument(
        "--stage",
        required=True,
        choices=["polish", "vernacular", "en"],
    )
    args = parser.parse_args()

    drive, sheets = build_google_services()
    task = find_task(sheets, args.task_id)
    if not task:
        raise RuntimeError(f"找不到任務：{args.task_id}")
    if task["period"] is None or not task["lesson"]:
        raise RuntimeError("任務缺少期數或堂次")

    folders = resolve_lesson_folders(
        drive,
        sheets,
        int(task["period"]),
        task["lesson"],
    )
    workdir = Path("/kaggle/working/gemini-text") / args.task_id
    workdir.mkdir(parents=True, exist_ok=True)
    glossary_rows = read_values(
        sheets,
        SPREADSHEET_ID,
        GLOSSARY_FULL_RANGE,
    )

    api_key = str(os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        api_key = get_secret("GEMINI_API_KEY")
    client = GeminiClient(
        api_key=api_key,
        text_model=DEFAULT_TEXT_MODEL,
        max_attempts=4,
        timeout=120,
    )

    run_id = new_run_id(args.task_id, args.stage)
    mark_running(
        args.task_id,
        args.stage,
        sheets=sheets,
        run_id=run_id,
        message=f"Gemini {args.stage} 執行中",
        progress=5,
    )

    try:
        if args.stage == "polish":
            message = stage_polish(
                client, drive, sheets, task, folders, glossary_rows, workdir
            )
        elif args.stage == "vernacular":
            message = stage_vernacular(
                client, drive, sheets, task, folders, glossary_rows, workdir
            )
        else:
            message = stage_en(
                client, drive, sheets, task, folders, glossary_rows, workdir
            )

        mark_done(
            args.task_id,
            args.stage,
            sheets=sheets,
            run_id=run_id,
            message=message,
        )
        print(f"[DONE] {message}")
        return 0

    except Exception as exc:
        mark_error(
            args.task_id,
            args.stage,
            sheets=sheets,
            run_id=run_id,
            exc=exc,
        )
        print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
