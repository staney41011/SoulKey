import argparse
import hashlib
import json
import os
import re
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from google import genai
from google.genai import types

from config import (
    COL,
    GLOSSARY_FULL_RANGE,
    SPREADSHEET_ID,
    TASK_SHEET_RANGE,
)
from gemini_checkpoint import (
    load_persistent_checkpoint,
    save_persistent_checkpoint,
)
from gemini_engine import (
    local_language_issue,
    normalize_segments,
    parse_glossary_rows,
)
from google_io import (
    build_google_services,
    download_drive_file,
    find_file,
    get_secret,
    read_values,
    upload_or_replace_file,
)
from lesson_paths import digits, resolve_lesson_folders


MODEL = os.getenv("GEMINI_SHADOW_MODEL", "gemini-3.1-flash-lite")
LANGS = ["th", "es", "id", "vi", "sd", "ta"]
LANGUAGE_NAMES = {
    "th": "Thai",
    "es": "Spanish",
    "id": "Indonesian",
    "vi": "Vietnamese",
    "sd": "Sindhi",
    "ta": "Tamil",
}
BATCH_SIZE = 12
WAIT_SECONDS = 15
REQUEST_TIMEOUT = 90


TRANSLATION_SCHEMA = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "segment_id": {"type": "integer"},
                    "th": {"type": "string"},
                    "es": {"type": "string"},
                    "id": {"type": "string"},
                    "vi": {"type": "string"},
                    "sd": {"type": "string"},
                    "ta": {"type": "string"},
                },
                "required": [
                    "segment_id",
                    "th",
                    "es",
                    "id",
                    "vi",
                    "sd",
                    "ta",
                ],
            },
        }
    },
    "required": ["segments"],
}


QA_SCHEMA = {
    "type": "object",
    "properties": {
        "failures": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "segment_id": {"type": "integer"},
                    "lang": {"type": "string"},
                    "issue": {"type": "string"},
                },
                "required": ["segment_id", "lang", "issue"],
            },
        }
    },
    "required": ["failures"],
}


class RequestTimeout(RuntimeError):
    pass


def _timeout_handler(signum, frame):
    raise RequestTimeout(f"Gemini request 超過 {REQUEST_TIMEOUT} 秒")


def _pad_row(row, length=20):
    return list(row) + [""] * max(0, length - len(row))


def _task_from_row(raw):
    row = _pad_row(raw, 20)
    return {
        "task_id": str(row[COL["task_id"]] or "").strip(),
        "period": digits(row[COL["period"]]),
        "lesson": str(row[COL["lesson"]] or "").strip(),
    }


def _find_task(sheets, task_id):
    for raw in read_values(sheets, SPREADSHEET_ID, TASK_SHEET_RANGE):
        task = _task_from_row(raw)
        if task["task_id"] == task_id:
            if task["period"] is None or not task["lesson"]:
                raise RuntimeError(f"{task_id} 的 period / lesson 不完整")
            return task
    raise RuntimeError(f"任務佇列找不到 {task_id}")


def _source_fingerprint(segments):
    raw = json.dumps(
        segments,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _glossary_text(rows):
    items = parse_glossary_rows(rows)
    lines = []
    for item in items:
        source = str(item.get("en") or item.get("zh") or "").strip()
        if not source:
            continue
        parts = [f"source={source}"]
        for lang in ("th", "es", "id", "vi"):
            value = str(item.get(lang) or "").strip()
            if value:
                parts.append(f"{lang}={value}")
        if item.get("locked"):
            parts.append("LOCKED")
        lines.append("- " + " | ".join(parts))
    return "\n".join(lines) or "(no glossary entries)"


def _write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def _sdk_client(api_key):
    # One SDK attempt only. Free-tier quota is too small to hide retries.
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=REQUEST_TIMEOUT * 1000,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )


def _structured(client, prompt, schema, label):
    print(f"\n[API] {label}", flush=True)
    print(f"[MODEL] {MODEL}", flush=True)
    started = time.time()

    signal.alarm(REQUEST_TIMEOUT)
    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )
    finally:
        signal.alarm(0)

    elapsed = time.time() - started
    print(f"✅ Response received ({elapsed:.1f}s)", flush=True)

    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, dict):
        return parsed
    if hasattr(parsed, "model_dump"):
        return parsed.model_dump()

    raw = str(response.text or "").strip()
    if not raw:
        raise RuntimeError(f"{label} 回傳空內容")
    return json.loads(raw)


def _translation_prompt(batch, glossary_text):
    source_rows = [
        {
            "segment_id": int(item["id"]),
            "english": item["text"],
        }
        for item in batch
    ]
    return f"""
You are the multilingual translation engine for the SoulKey religious education course.

Translate every approved English segment directly into ALL six target languages:
th = Thai
es = Spanish
id = Indonesian
vi = Vietnamese
sd = Sindhi
ta = Tamil

IMPORTANT:
- segment_id is the source segment number.
- the key id means Indonesian, not a segment number.

Rules:
1. Preserve the complete meaning.
2. Preserve all numbers, names and examples.
3. Do not summarize.
4. Do not add explanations or doctrine.
5. Do not merge, split or reorder segments.
6. Keep segment_id unchanged.
7. Produce all six languages.
8. Translate every language directly from English.
9. Use natural spoken language suitable for TTS.
10. Follow LOCKED glossary mappings when a target mapping exists.

Glossary:
{glossary_text}

SOURCE:
{json.dumps(source_rows, ensure_ascii=False)}
"""


def _qa_prompt(batch, rows):
    by_id = {int(row["segment_id"]): row for row in rows}
    payload = []
    for source in batch:
        sid = int(source["id"])
        row = by_id[sid]
        payload.append({
            "segment_id": sid,
            "en": source["text"],
            "th": row["th"],
            "es": row["es"],
            "id": row["id"],
            "vi": row["vi"],
            "sd": row["sd"],
            "ta": row["ta"],
        })

    return f"""
Audit these translations against the approved English source.

Languages:
th Thai
es Spanish
id Indonesian
vi Vietnamese
sd Sindhi
ta Tamil

Only report genuine translation failures:
- important meaning missing
- materially wrong meaning
- invented content
- wrong target language
- important number changed or missing
- serious glossary violation

Do NOT report stylistic differences, natural wording differences,
accurate non-literal wording, or proper nouns remaining in Latin script.

If everything passes, return an empty failures array.

DATA:
{json.dumps(payload, ensure_ascii=False)}
"""


def _validate_translation(batch, rows):
    expected = sorted(int(x["id"]) for x in batch)
    got = sorted(int(x["segment_id"]) for x in rows)
    if expected != got:
        raise RuntimeError(
            f"Translation segment_id 不完整：expected={expected}, got={got}"
        )

    for row in rows:
        for lang in LANGS:
            if not str(row.get(lang) or "").strip():
                raise RuntimeError(
                    f"segment {row.get('segment_id')} 缺少 {lang}"
                )


def _local_qa(batch, rows):
    by_id = {int(row["segment_id"]): row for row in rows}
    failures = []

    for source in batch:
        sid = int(source["id"])
        english = str(source["text"])
        numbers = re.findall(r"\d+(?:\.\d+)?", english)

        for lang in LANGS:
            target = str(by_id[sid].get(lang) or "").strip()
            issues = []

            issue = local_language_issue(target, english, lang)
            if issue:
                issues.append(issue)

            for number in numbers:
                if number not in target:
                    issues.append(f"missing_number:{number}")

            if issues:
                failures.append({
                    "segment_id": sid,
                    "lang": lang,
                    "issues": issues,
                })

    return failures


def _checkpoint_payload(
    task_id,
    source_hash,
    source_count,
    translations,
    qa_batches,
    seq,
):
    return {
        "version": 1,
        "task_id": task_id,
        "engine": "gemini-six-language-shadow",
        "model": MODEL,
        "source_fingerprint": source_hash,
        "source_segments": source_count,
        "checkpoint_seq": int(seq),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "translations": [
            translations[sid]
            for sid in sorted(translations)
        ],
        "qa_batches": qa_batches,
    }


def _save_checkpoint(
    task_id,
    source_hash,
    source_count,
    translations,
    qa_batches,
    seq,
    drive,
    translation_folder,
    workdir,
):
    payload = _checkpoint_payload(
        task_id,
        source_hash,
        source_count,
        translations,
        qa_batches,
        seq,
    )
    result = save_persistent_checkpoint(
        task_id,
        payload,
        drive=drive,
        translation_folder_id=translation_folder,
        workdir=workdir,
        require_persistent=True,
    )
    backends = ["drive"]
    if result.get("github") and result["github"].get("ok"):
        backends.append("github")
    print(
        "✅ Persistent checkpoint saved: " + " + ".join(backends),
        flush=True,
    )
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--wait-seconds", type=int, default=WAIT_SECONDS)
    parser.add_argument(
        "--reset-checkpoint",
        action="store_true",
        help="忽略既有 checkpoint，從頭建立新的 Shadow checkpoint",
    )
    args = parser.parse_args()

    signal.signal(signal.SIGALRM, _timeout_handler)

    api_key = get_secret("GEMINI_API_KEY")
    print("GEMINI_API_KEY: OK", flush=True)

    drive, sheets = build_google_services()
    task = _find_task(sheets, args.task_id)
    folders = resolve_lesson_folders(
        drive,
        sheets,
        int(task["period"]),
        task["lesson"],
    )

    workdir = Path("/kaggle/working") / f"gemini-shadow-{args.task_id}"
    workdir.mkdir(parents=True, exist_ok=True)

    source_item = find_file(
        drive,
        folders["translation"],
        "en.final.json",
    )
    if not source_item:
        raise RuntimeError(
            f"{args.task_id} 找不到 02_翻譯稿/en.final.json；"
            "Gemini 六語 Shadow 只接受 English Final。"
        )

    source_path = workdir / "en.final.json"
    download_drive_file(drive, source_item["id"], source_path)
    source_payload = json.loads(source_path.read_text(encoding="utf-8"))
    source_segments = normalize_segments(source_payload)
    source_hash = _source_fingerprint(source_segments)

    glossary_rows = read_values(
        sheets,
        SPREADSHEET_ID,
        GLOSSARY_FULL_RANGE,
    )
    glossary_text = _glossary_text(glossary_rows)

    checkpoint = None
    checkpoint_source = None
    if not args.reset_checkpoint:
        checkpoint, checkpoint_source = load_persistent_checkpoint(
            args.task_id,
            drive=drive,
            translation_folder_id=folders["translation"],
            workdir=workdir,
        )

    translations = {}
    qa_batches = {}
    checkpoint_seq = 0

    if checkpoint:
        if str(checkpoint.get("source_fingerprint") or "") != source_hash:
            raise RuntimeError(
                "既有 checkpoint 的 English Final fingerprint 已改變。"
                "若確認要重新測試，請加 --reset-checkpoint。"
            )

        for row in checkpoint.get("translations") or []:
            translations[int(row["segment_id"])] = row
        qa_batches = dict(checkpoint.get("qa_batches") or {})
        checkpoint_seq = int(checkpoint.get("checkpoint_seq") or 0)

        print(
            f"✅ Resume checkpoint: {checkpoint_source}; "
            f"translations={len(translations)}; qa_batches={len(qa_batches)}",
            flush=True,
        )
    else:
        print("Checkpoint: none", flush=True)

    client = _sdk_client(api_key)

    remaining = [
        item for item in source_segments
        if int(item["id"]) not in translations
    ]

    batches = [
        remaining[i:i + args.batch_size]
        for i in range(0, len(remaining), args.batch_size)
    ]

    print("=" * 72, flush=True)
    print("SoulKey Gemini FULL LESSON Persistent Shadow", flush=True)
    print("=" * 72, flush=True)
    print(f"Task: {args.task_id}", flush=True)
    print(f"Model: {MODEL}", flush=True)
    print(f"English Final: {len(source_segments)}", flush=True)
    print(f"Cached translations: {len(translations)}", flush=True)
    print(f"Remaining: {len(remaining)}", flush=True)
    print(f"Batches: {len(batches)}", flush=True)

    for batch_no, batch in enumerate(batches, start=1):
        ids = [int(item["id"]) for item in batch]
        batch_key = f"{ids[0]}-{ids[-1]}"

        print("\n" + "=" * 72, flush=True)
        print(
            f"BATCH {batch_no}/{len(batches)} | "
            f"segments {ids[0]} → {ids[-1]}",
            flush=True,
        )
        print("=" * 72, flush=True)

        payload = _structured(
            client,
            _translation_prompt(batch, glossary_text),
            TRANSLATION_SCHEMA,
            "MULTI TRANSLATION",
        )
        rows = payload.get("segments") or []
        _validate_translation(batch, rows)
        print("✅ Translation structure PASS", flush=True)

        for row in rows:
            translations[int(row["segment_id"])] = row

        checkpoint_seq += 1
        _save_checkpoint(
            args.task_id,
            source_hash,
            len(source_segments),
            translations,
            qa_batches,
            checkpoint_seq,
            drive,
            folders["translation"],
            workdir,
        )

        local_failures = _local_qa(batch, rows)
        print(f"Local failures: {len(local_failures)}", flush=True)

        print(f"等待 {args.wait_seconds} 秒後 QA...", flush=True)
        time.sleep(args.wait_seconds)

        qa_payload = _structured(
            client,
            _qa_prompt(batch, rows),
            QA_SCHEMA,
            "SEMANTIC QA",
        )
        semantic_failures = qa_payload.get("failures") or []
        print(
            f"Semantic failures: {len(semantic_failures)}",
            flush=True,
        )

        qa_batches[batch_key] = {
            "segment_ids": ids,
            "local_failures": local_failures,
            "semantic_failures": semantic_failures,
        }

        checkpoint_seq += 1
        _save_checkpoint(
            args.task_id,
            source_hash,
            len(source_segments),
            translations,
            qa_batches,
            checkpoint_seq,
            drive,
            folders["translation"],
            workdir,
        )

        if batch_no < len(batches):
            print(
                f"等待 {args.wait_seconds} 秒再進下一批...",
                flush=True,
            )
            time.sleep(args.wait_seconds)

    missing_ids = [
        int(item["id"])
        for item in source_segments
        if int(item["id"]) not in translations
    ]
    if missing_ids:
        raise RuntimeError(f"仍有未翻譯 segments：{missing_ids}")

    # A resumed run may already have translations but lack QA for one cached batch.
    # Verify every source segment is covered by some QA batch before declaring done.
    qa_covered = set()
    for data in qa_batches.values():
        qa_covered.update(int(x) for x in data.get("segment_ids") or [])

    unqaed = [
        item for item in source_segments
        if int(item["id"]) not in qa_covered
    ]
    if unqaed:
        print(
            f"[RESUME] 尚有 {len(unqaed)} 個已翻譯 segment 缺 QA，補做 QA。",
            flush=True,
        )
        qa_only_batches = [
            unqaed[i:i + args.batch_size]
            for i in range(0, len(unqaed), args.batch_size)
        ]
        for batch in qa_only_batches:
            ids = [int(item["id"]) for item in batch]
            batch_key = f"{ids[0]}-{ids[-1]}"
            rows = [translations[sid] for sid in ids]
            local_failures = _local_qa(batch, rows)
            if args.wait_seconds:
                time.sleep(args.wait_seconds)
            qa_payload = _structured(
                client,
                _qa_prompt(batch, rows),
                QA_SCHEMA,
                "RESUME SEMANTIC QA",
            )
            semantic_failures = qa_payload.get("failures") or []
            qa_batches[batch_key] = {
                "segment_ids": ids,
                "local_failures": local_failures,
                "semantic_failures": semantic_failures,
            }
            checkpoint_seq += 1
            _save_checkpoint(
                args.task_id,
                source_hash,
                len(source_segments),
                translations,
                qa_batches,
                checkpoint_seq,
                drive,
                folders["translation"],
                workdir,
            )

    local_all = []
    semantic_all = []
    for data in qa_batches.values():
        local_all.extend(data.get("local_failures") or [])
        semantic_all.extend(data.get("semantic_failures") or [])

    failure_map = {}

    def add_failure(sid, lang, issue):
        key = (int(sid), str(lang))
        failure_map.setdefault(key, [])
        if issue and issue not in failure_map[key]:
            failure_map[key].append(str(issue))

    for item in local_all:
        for issue in item.get("issues") or []:
            add_failure(item["segment_id"], item["lang"], issue)

    for item in semantic_all:
        lang = str(item.get("lang") or "").strip()
        if lang in LANGS:
            add_failure(
                item["segment_id"],
                lang,
                item.get("issue") or "semantic_qa_fail",
            )

    summary = {}
    for lang in LANGS:
        failed_ids = sorted({
            sid for (sid, code) in failure_map
            if code == lang
        })
        summary[lang] = {
            "pass": len(source_segments) - len(failed_ids),
            "fail": len(failed_ids),
            "failed_ids": failed_ids,
        }

    final_rows = [
        translations[int(item["id"])]
        for item in source_segments
    ]

    translations_path = _write_json(
        workdir / "gemini-shadow-translations.full.json",
        {
            "task_id": args.task_id,
            "model": MODEL,
            "source_fingerprint": source_hash,
            "segments": final_rows,
        },
    )
    qa_path = _write_json(
        workdir / "gemini-shadow-qa.full.json",
        {
            "task_id": args.task_id,
            "local_failures": local_all,
            "semantic_failures": semantic_all,
            "combined_failures": [
                {
                    "segment_id": sid,
                    "lang": lang,
                    "issues": issues,
                }
                for (sid, lang), issues in failure_map.items()
            ],
        },
    )
    summary_path = _write_json(
        workdir / "gemini-shadow-summary.full.json",
        {
            "task_id": args.task_id,
            "model": MODEL,
            "segments": len(source_segments),
            "languages": summary,
        },
    )

    for path in (translations_path, qa_path, summary_path):
        upload_or_replace_file(
            drive,
            folders["translation"],
            str(path),
            Path(path).name,
        )

    checkpoint_seq += 1
    final_checkpoint = _checkpoint_payload(
        args.task_id,
        source_hash,
        len(source_segments),
        translations,
        qa_batches,
        checkpoint_seq,
    )
    final_checkpoint["status"] = "complete"
    final_checkpoint["summary"] = summary
    save_persistent_checkpoint(
        args.task_id,
        final_checkpoint,
        drive=drive,
        translation_folder_id=folders["translation"],
        workdir=workdir,
        require_persistent=True,
    )

    print("\n" + "=" * 72, flush=True)
    print("SoulKey Persistent Shadow Summary", flush=True)
    print("=" * 72, flush=True)
    print(f"Task: {args.task_id}", flush=True)
    print(f"Model: {MODEL}", flush=True)
    print(f"Segments: {len(source_segments)}", flush=True)
    for lang in LANGS:
        row = summary[lang]
        status = "PASS" if row["fail"] == 0 else "CHECK"
        print(
            f"{lang:>3} | {status:<5} | "
            f"PASS {row['pass']:>3} | FAIL {row['fail']:>3}",
            flush=True,
        )

    print("\n✅ final output 已寫入 Drive/02_翻譯稿", flush=True)
    print("✅ checkpoint 不再依賴 /kaggle/working", flush=True)
    print("✅ runtime 重啟後可從 Drive / GitHub 固定路徑續跑", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
