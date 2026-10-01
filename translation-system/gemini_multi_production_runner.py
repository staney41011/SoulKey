import argparse
import hashlib
import json
import os
import re
import sys
import time
import traceback
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from config import COL, GLOSSARY_FULL_RANGE, SPREADSHEET_ID, TASK_SHEET_RANGE
from gemini_checkpoint import load_persistent_checkpoint, save_persistent_checkpoint
from drive_naming import formal_drive_name
from gemini_engine import DEFAULT_TEXT_MODEL, GeminiAPIError, GeminiClient, local_language_issue, normalize_segments
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
from nvidia_translate import NvidiaTranslateClient, SUPPORTED_TARGETS
from status_io import new_run_id, mark_done, mark_error, mark_running


LANGS = ["th", "es", "id", "vi", "sd", "ta"]
LANGUAGE_NAMES = {
    "th": "Thai",
    "es": "Spanish",
    "id": "Indonesian",
    "vi": "Vietnamese",
    "sd": "Sindhi",
    "ta": "Tamil",
}
LEGACY_COLS = {"th": "K", "es": "L", "id": "M", "vi": "N"}
REPAIR_MODEL = os.getenv("GEMINI_REPAIR_MODEL", "gemini-3.8-flash")

MULTI_SCHEMA = {
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
                "required": ["segment_id", "th", "es", "id", "vi", "sd", "ta"],
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

REPAIR_SCHEMA = {
    "type": "object",
    "properties": {
        "repairs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "segment_id": {"type": "integer"},
                    "lang": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["segment_id", "lang", "text"],
            },
        }
    },
    "required": ["repairs"],
}


def pad_row(row, length=20):
    return list(row) + [""] * max(0, length - len(row))


def find_task(sheets, task_id):
    for index, raw in enumerate(read_values(sheets, SPREADSHEET_ID, TASK_SHEET_RANGE), start=2):
        row = pad_row(raw, 20)
        if str(row[COL["task_id"]] or "").strip() == task_id:
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


def write_language_set(output_dir, lang, source_segments, translations, model, engine="gemini"):
    output_dir.mkdir(parents=True, exist_ok=True)
    by_id = {int(x["segment_id"]): x for x in translations}
    segments = []
    for src in source_segments:
        sid = int(src["id"])
        segments.append({
            "id": sid,
            "start": float(src["start"]),
            "end": float(src["end"]),
            "text": str(by_id[sid][lang]).strip(),
        })

    json_path = output_dir / f"{lang}.json"
    txt_path = output_dir / f"{lang}.txt"
    srt_path = output_dir / f"{lang}.srt"

    json_path.write_text(
        json.dumps(
            {
                "language": lang,
                "language_name": LANGUAGE_NAMES[lang],
                "engine": engine,
                "model": model,
                "source": "en.final.json",
                "segments": segments,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    txt_path.write_text("\n".join(x["text"] for x in segments) + "\n", encoding="utf-8")

    blocks = []
    for order, seg in enumerate(segments, start=1):
        blocks.append(
            f"{order}\n"
            f"{format_srt_time(seg['start'])} --> {format_srt_time(seg['end'])}\n"
            f"{seg['text']}"
        )
    srt_path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    return [json_path, txt_path, srt_path]


def glossary_text(rows):
    lines = []
    for raw in rows or []:
        row = list(raw) + [""] * max(0, 10 - len(raw))
        zh = str(row[0] or "").strip()
        en = str(row[3] or "").strip()
        if not (zh or en):
            continue
        parts = [f"source={en or zh}"]
        for code, idx in [("th", 4), ("es", 5), ("id", 6), ("vi", 7)]:
            value = str(row[idx] or "").strip()
            if value:
                parts.append(f"{code}={value}")
        locked = str(row[8] or "").strip().lower() in {"true", "1", "yes", "y", "是"}
        if locked:
            parts.append("LOCKED")
        lines.append("- " + " | ".join(parts))
    return "\n".join(lines[:120]) or "(no glossary entries)"


def translation_prompt(batch, glossary):
    payload = [{"segment_id": int(x["id"]), "english": x["text"]} for x in batch]
    return f"""
Translate every approved English segment into all six languages:
th Thai, es Spanish, id Indonesian, vi Vietnamese, sd Sindhi, ta Tamil.

Rules:
- segment_id is the source segment number; id is Indonesian.
- Preserve every idea, number, name, example, and logical relationship.
- Do not summarize, merge, split, reorder, or add doctrine.
- Produce natural language suitable for TTS.
- Follow LOCKED glossary mappings when the target mapping exists.
- Return every language for every segment.

Glossary:
{glossary}

SOURCE:
{json.dumps(payload, ensure_ascii=False)}
"""


def qa_prompt(batch, rows, langs):
    by_id = {int(x["segment_id"]): x for x in rows}
    payload = []
    for src in batch:
        sid = int(src["id"])
        row = by_id[sid]
        payload.append({
            "segment_id": sid,
            "en": src["text"],
            **{lang: row[lang] for lang in langs},
        })
    return f"""
Audit only these requested-language translations against the approved English source:
{",".join(langs)}.
Only report real failures: missing important meaning, materially wrong meaning,
invented content, wrong target language, changed/missing important number,
or serious glossary violation.
Judge each item only against the English source shown in DATA. Do not invent
gender, speaker identity, or facts from outside the supplied source. Do not fail
natural non-literal wording, harmless style differences, or a romanized proper
name that is intentionally preserved by the glossary.
If everything passes return failures=[].

DATA:
{json.dumps(payload, ensure_ascii=False)}
"""



TRANSIENT_GEMINI_MARKERS = (
    "HTTP 408",
    "HTTP 409",
    "HTTP 429",
    "HTTP 500",
    "HTTP 502",
    "HTTP 503",
    "HTTP 504",
    "service_unavailable",
    "high demand",
    "rate limit",
    "timeout",
    "temporarily unavailable",
)


def is_transient_gemini_error(exc):
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(marker.lower() in text for marker in TRANSIENT_GEMINI_MARKERS)


def selected_translation_schema(langs):
    langs = [str(x) for x in langs]
    props = {"segment_id": {"type": "integer"}}
    props.update({lang: {"type": "string"} for lang in langs})
    return {
        "type": "object",
        "properties": {
            "segments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": props,
                    "required": ["segment_id", *langs],
                },
            }
        },
        "required": ["segments"],
    }


def selected_translation_prompt(batch, glossary, langs):
    payload = [{"segment_id": int(x["id"]), "english": x["text"]} for x in batch]
    names = ", ".join(f"{lang} {LANGUAGE_NAMES[lang]}" for lang in langs)
    return f"""
Translate every approved English segment into only these languages:
{names}.

Rules:
- Preserve every idea, number, name, example, and logical relationship.
- Do not summarize, merge, split, reorder, or add doctrine.
- Produce natural language suitable for TTS.
- Follow LOCKED glossary mappings when the target mapping exists.
- Return every requested language for every segment.

Glossary:
{glossary}

SOURCE:
{json.dumps(payload, ensure_ascii=False)}
"""


def gemini_translate_with_backoff(client, batch, glossary, langs, waits=(30, 60, 120)):
    last_exc = None
    schema = MULTI_SCHEMA if list(langs) == LANGS else selected_translation_schema(langs)
    prompt = (
        translation_prompt(batch, glossary)
        if list(langs) == LANGS
        else selected_translation_prompt(batch, glossary, langs)
    )

    for attempt in range(1, len(waits) + 2):
        try:
            parsed, _ = client.structured(
                prompt,
                schema,
                system_instruction=(
                    "You are the production multilingual translation engine for SoulKey."
                ),
                thinking_level="low",
            )
            return parsed
        except Exception as exc:
            last_exc = exc
            if not is_transient_gemini_error(exc) or attempt > len(waits):
                raise
            wait_seconds = waits[attempt - 1]
            print(
                f"[GEMINI-FALLBACK] transient failure; retry "
                f"{attempt + 1}/{len(waits)+1} after {wait_seconds}s: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
            time.sleep(wait_seconds)

    raise last_exc


def nvidia_translate_batch(nvidia_client, batch, langs):
    """Translate a batch with Riva for the SoulKey languages it supports."""
    if not nvidia_client:
        raise RuntimeError("NVIDIA fallback client is not available")

    supported = [lang for lang in langs if lang in SUPPORTED_TARGETS]
    if not supported:
        return {}

    rows = {
        int(src["id"]): {"segment_id": int(src["id"])}
        for src in batch
    }
    for src in batch:
        sid = int(src["id"])
        english = str(src["text"] or "").strip()
        for lang in supported:
            candidate = nvidia_client.translate(english, lang).strip()
            issue = local_language_issue(candidate, english, lang)
            if issue:
                raise RuntimeError(
                    f"NVIDIA fallback local QA failed: {sid}/{lang}/{issue}"
                )
            normalized = normalize_unicode_digits(candidate)
            for number in re.findall(r"\d+(?:\.\d+)?", english):
                if number not in normalized:
                    raise RuntimeError(
                        f"NVIDIA fallback missing number: {sid}/{lang}/{number}"
                    )
            rows[sid][lang] = candidate
    return rows


def translate_batch_with_provider_fallback(
    client,
    nvidia_client,
    batch,
    glossary,
    requested,
):
    """Keep Gemini primary; use NVIDIA only after transient Gemini exhaustion.

    NVIDIA Riva v2 covers th/es/id/vi. If sd/ta are requested, a much smaller
    Gemini request is used only for those unsupported targets after NVIDIA has
    already completed the supported languages.
    """
    try:
        parsed = gemini_translate_with_backoff(
            client,
            batch,
            glossary,
            LANGS,
        )
        return parsed.get("segments") or [], "gemini"
    except Exception as exc:
        if not is_transient_gemini_error(exc) or not nvidia_client:
            raise

        supported = [lang for lang in requested if lang in SUPPORTED_TARGETS]
        if not supported:
            raise

        print(
            "[NVIDIA-FALLBACK] Gemini transient retries exhausted; "
            "Riva Translate takes over supported targets: "
            + ",".join(supported),
            flush=True,
        )

        rows_by_id = nvidia_translate_batch(
            nvidia_client,
            batch,
            supported,
        )
        unsupported = [lang for lang in requested if lang not in SUPPORTED_TARGETS]

        if unsupported:
            print(
                "[NVIDIA-FALLBACK] Riva does not support "
                + ",".join(unsupported)
                + "; retrying Gemini only for those targets.",
                flush=True,
            )
            parsed = gemini_translate_with_backoff(
                client,
                batch,
                glossary,
                unsupported,
                waits=(60, 120, 300),
            )
            for item in parsed.get("segments") or []:
                sid = int(item["segment_id"])
                rows_by_id.setdefault(sid, {"segment_id": sid})
                for lang in unsupported:
                    rows_by_id[sid][lang] = str(item.get(lang) or "").strip()

        rows = [rows_by_id[int(src["id"])] for src in batch]
        return rows, "nvidia-riva-fallback"

def normalize_unicode_digits(text):
    out = []
    for ch in str(text or ""):
        try:
            if ch.isdigit():
                out.append(str(unicodedata.digit(ch)))
            else:
                out.append(ch)
        except (TypeError, ValueError):
            out.append(ch)
    return "".join(out)


def local_failures(batch, rows, langs):
    by_id = {int(x["segment_id"]): x for x in rows}
    failures = []
    for src in batch:
        sid = int(src["id"])
        english = str(src["text"])
        numbers = re.findall(r"\d+(?:\.\d+)?", english)
        for lang in langs:
            target = str(by_id[sid].get(lang) or "").strip()
            target_for_numbers = normalize_unicode_digits(target)
            issues = []
            issue = local_language_issue(target, english, lang)
            if issue:
                issues.append(issue)
            for number in numbers:
                if number not in target_for_numbers:
                    issues.append(f"missing_number:{number}")
            if issues:
                failures.append({"segment_id": sid, "lang": lang, "issues": issues})
    return failures


def combine_failures(local_rows, semantic_rows, langs):
    combined = {}
    for item in local_rows:
        key = (int(item["segment_id"]), str(item["lang"]))
        combined.setdefault(key, [])
        for issue in item.get("issues") or []:
            if issue not in combined[key]:
                combined[key].append(str(issue))
    for item in semantic_rows:
        lang = str(item.get("lang") or "").strip()
        if lang not in langs:
            continue
        key = (int(item["segment_id"]), lang)
        combined.setdefault(key, [])
        issue = str(item.get("issue") or "semantic_qa_fail")
        if issue not in combined[key]:
            combined[key].append(issue)
    return combined


def repair_failed_pairs(client, source_map, translations, failures, glossary):
    if not failures:
        return [], REPAIR_MODEL

    repair_input = []
    for (sid, lang), issues in sorted(failures.items()):
        repair_input.append({
            "segment_id": sid,
            "lang": lang,
            "language": LANGUAGE_NAMES[lang],
            "english": source_map[sid]["text"],
            "current_translation": translations[sid][lang],
            "issues": issues,
        })

    prompt = f"""
Repair only the listed failed translations.
Preserve all English meaning, names, numbers, examples, and doctrine.
Fix EVERY stated QA issue visibly and completely. Do not explain.
Keep segment_id and lang unchanged.
For th write normal prose in Thai script; for sd write normal prose in Sindhi
Arabic-derived script; for ta write normal prose in Tamil script. Proper names
or LOCKED glossary forms such as Qianxian may remain romanized when appropriate.
Do not add filler merely to satisfy a script check.
Return only the requested repaired target-language text.

Glossary:
{glossary}

FAILED PAIRS:
{json.dumps(repair_input, ensure_ascii=False)}
"""

    model_used = REPAIR_MODEL
    try:
        parsed, _ = client.structured(
            prompt,
            REPAIR_SCHEMA,
            system_instruction="You are a precise multilingual translation repair engine.",
            model=REPAIR_MODEL,
            thinking_level="low",
        )
    except Exception as exc:
        print(
            f"[REPAIR] {REPAIR_MODEL} 失敗，改用 {client.text_model}: {type(exc).__name__}: {exc}",
            flush=True,
        )
        model_used = client.text_model
        parsed, _ = client.structured(
            prompt,
            REPAIR_SCHEMA,
            system_instruction="You are a precise multilingual translation repair engine.",
            model=client.text_model,
            thinking_level="low",
        )

    repairs = parsed.get("repairs") or []
    expected = {(x["segment_id"], x["lang"]) for x in repair_input}
    got = {(int(x["segment_id"]), str(x["lang"])) for x in repairs}
    if expected != got:
        raise RuntimeError(f"Repair 回傳不完整：expected={expected}, got={got}")

    for item in repairs:
        sid = int(item["segment_id"])
        lang = str(item["lang"])
        text = str(item["text"] or "").strip()
        if not text:
            raise RuntimeError(f"Repair 回傳空文字：{sid}/{lang}")
        translations[sid][lang] = text

    return repairs, model_used


def audit_batch(client, batch, translations, langs, wait_seconds=0):
    rows = [translations[int(src["id"])] for src in batch]
    local = local_failures(batch, rows, langs)
    if wait_seconds:
        time.sleep(wait_seconds)

    prompt = qa_prompt(batch, rows, langs)
    qa = None
    waits = [30, 60, 120]
    for attempt in range(1, len(waits) + 2):
        try:
            qa, _ = client.structured(
                prompt,
                QA_SCHEMA,
                system_instruction=(
                    "Verify translation meaning only from the supplied English DATA. "
                    "Do not infer facts from outside the batch."
                ),
                thinking_level="low",
            )
            break
        except Exception as exc:
            if not is_transient_gemini_error(exc) or attempt > len(waits):
                raise
            wait_seconds_retry = waits[attempt - 1]
            print(
                f"[QA-AUTO-RESUME] Gemini QA transient failure; retry "
                f"{attempt + 1}/{len(waits)+1} after {wait_seconds_retry}s: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
            time.sleep(wait_seconds_retry)

    semantic = (qa or {}).get("failures") or []
    failures = combine_failures(local, semantic, langs)
    return failures, local, semantic


def nvidia_repair_failed_pairs(
    nvidia_client,
    source_map,
    translations,
    failures,
):
    """Try NVIDIA only for th/es/id/vi pairs already rejected by Gemini QA."""
    if not nvidia_client or not failures:
        return []

    repairs = []
    for (sid, lang), issues in sorted(failures.items()):
        if lang not in SUPPORTED_TARGETS:
            continue

        english = str(source_map[sid]["text"])
        try:
            candidate = nvidia_client.translate(english, lang).strip()
        except Exception as exc:
            print(
                f"[NVIDIA] {sid}/{lang} second opinion unavailable: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
            continue

        local_issues = []
        issue = local_language_issue(candidate, english, lang)
        if issue:
            local_issues.append(issue)

        normalized = normalize_unicode_digits(candidate)
        for number in re.findall(r"\d+(?:\.\d+)?", english):
            if number not in normalized:
                local_issues.append(f"missing_number:{number}")

        if local_issues:
            print(
                f"[NVIDIA] {sid}/{lang} candidate rejected locally: "
                + ",".join(local_issues),
                flush=True,
            )
            continue

        translations[sid][lang] = candidate
        repairs.append({
            "segment_id": sid,
            "lang": lang,
            "text": candidate,
            "engine": "nvidia-riva",
            "model": nvidia_client.model,
            "issues": list(issues or []),
        })
        print(
            f"[NVIDIA] {sid}/{lang} candidate accepted for Gemini re-audit.",
            flush=True,
        )

    return repairs


def repair_batch_until_clean(
    client,
    batch,
    translations,
    source_map,
    glossary,
    langs,
    *,
    wait_seconds=0,
    initial_failures=None,
    max_rounds=4,
    nvidia_client=None,
):
    if initial_failures is None:
        failures, local, semantic = audit_batch(
            client, batch, translations, langs, wait_seconds=wait_seconds
        )
    else:
        failures = dict(initial_failures)
        local = []
        semantic = []

    repair_history = []
    models = []

    # NVIDIA is also used as a QA second opinion for the languages Riva
    # officially supports. Primary translation fallback is handled earlier.
    if failures and nvidia_client:
        nvidia_repairs = nvidia_repair_failed_pairs(
            nvidia_client,
            source_map,
            translations,
            failures,
        )
        if nvidia_repairs:
            for item in nvidia_repairs:
                repair_history.append({**item, "repair_round": 0})
            models.append(nvidia_client.model)
            failures, local, semantic = audit_batch(
                client,
                batch,
                translations,
                langs,
                wait_seconds=wait_seconds,
            )
            print(
                f"[NVIDIA] Gemini re-audit complete; "
                f"unresolved={len(failures)}",
                flush=True,
            )

    for round_no in range(1, max_rounds + 1):
        if not failures:
            break
        if wait_seconds:
            time.sleep(wait_seconds)

        repairs, model_used = repair_failed_pairs(
            client,
            source_map,
            translations,
            failures,
            glossary,
        )
        models.append(model_used)
        for item in repairs:
            repair_history.append({
                **item,
                "repair_round": round_no,
                "engine": "gemini",
                "model": model_used,
            })

        failures, local, semantic = audit_batch(
            client,
            batch,
            translations,
            langs,
            wait_seconds=wait_seconds,
        )
        print(
            f"[REPAIR] round={round_no}/{max_rounds}; "
            f"unresolved={len(failures)}",
            flush=True,
        )

    return failures, local, semantic, repair_history, models


def source_fingerprint(source_segments):
    canonical = [
        {
            "id": int(x["id"]),
            "start": float(x["start"]),
            "end": float(x["end"]),
            "text": str(x["text"]),
        }
        for x in source_segments
    ]
    raw = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def checkpoint_payload(
    task_id,
    source_count,
    translations,
    qa_batches,
    seq,
    source_sha256="",
):
    return {
        "version": 3,
        "task_id": task_id,
        "engine": "gemini-production-multi",
        "model": DEFAULT_TEXT_MODEL,
        "source_segments": source_count,
        "source_sha256": source_sha256,
        "checkpoint_seq": seq,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "translations": [translations[k] for k in sorted(translations)],
        "qa_batches": qa_batches,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--langs", default="th,es,id,vi,sd,ta")
    parser.add_argument("--batch-size", type=int, default=12)
    parser.add_argument("--wait-seconds", type=int, default=15)
    parser.add_argument("--reset-checkpoint", action="store_true")
    args = parser.parse_args()

    requested = [x.strip() for x in args.langs.split(",") if x.strip()]
    unknown = [x for x in requested if x not in LANGS]
    if unknown:
        raise RuntimeError("不支援的 Gemini 翻譯語言：" + ",".join(unknown))
    requested = [x for x in LANGS if x in set(requested)]
    if not requested:
        raise RuntimeError("Gemini production multi 沒有指定任何目標語言")

    # Keep one six-language inference/checkpoint for compatibility, but QA,
    # repair, publishing, and completion are scoped to Studio's requested
    # languages so an unselected language cannot block the job.

    drive, sheets = build_google_services()
    task = find_task(sheets, args.task_id)
    if not task:
        raise RuntimeError(f"找不到任務：{args.task_id}")
    if task["period"] is None or not task["lesson"]:
        raise RuntimeError("任務缺少期數或堂次")

    folders = resolve_lesson_folders(drive, sheets, int(task["period"]), task["lesson"])
    workdir = Path("/kaggle/working/gemini-multi") / args.task_id
    workdir.mkdir(parents=True, exist_ok=True)

    source_item = find_file(drive, folders["translation"], "en.final.json")
    if not source_item:
        raise RuntimeError("找不到 en.final.json；六語正式翻譯只接受 English Final")

    source_path = workdir / "en.final.json"
    download_drive_file(drive, source_item["id"], source_path)
    source_segments = normalize_segments(json.loads(source_path.read_text(encoding="utf-8")))
    source_map = {int(x["id"]): x for x in source_segments}
    source_sha256 = source_fingerprint(source_segments)
    glossary = glossary_text(read_values(sheets, SPREADSHEET_ID, GLOSSARY_FULL_RANGE))

    api_key = str(os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        api_key = get_secret("GEMINI_API_KEY")
    client = GeminiClient(
        api_key=api_key,
        text_model=DEFAULT_TEXT_MODEL,
        max_attempts=4,
        timeout=120,
    )

    nvidia_api_key = str(os.environ.get("NVIDIA_API_KEY") or "").strip()
    if not nvidia_api_key:
        nvidia_api_key = get_secret("NVIDIA_API_KEY", required=False)

    nvidia_client = None
    if nvidia_api_key:
        try:
            nvidia_client = NvidiaTranslateClient(
                api_key=nvidia_api_key,
                timeout=90,
                max_attempts=3,
            )
            print(
                "[NVIDIA] Riva Translate v2 enabled as translation fallback "
                "and QA second opinion for th/es/id/vi.",
                flush=True,
            )
        except Exception as exc:
            print(
                f"[NVIDIA] optional client disabled: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
    else:
        print(
            "[NVIDIA] NVIDIA_API_KEY not configured; Gemini-only QA continues.",
            flush=True,
        )

    run_id = new_run_id(args.task_id, "multi")
    mark_running(
        args.task_id,
        "multi",
        sheets=sheets,
        run_id=run_id,
        message="Gemini 六語翻譯 + QA 執行中",
        progress=5,
    )

    try:
        translations = {}
        qa_batches = {}
        seq = 0

        if not args.reset_checkpoint:
            checkpoint, source = load_persistent_checkpoint(
                args.task_id,
                drive=drive,
                translation_folder_id=folders["translation"],
                workdir=workdir,
            )
            if checkpoint and checkpoint.get("engine") == "gemini-production-multi":
                checkpoint_sha = str(checkpoint.get("source_sha256") or "").strip()
                if checkpoint_sha != source_sha256:
                    reason = (
                        "缺少 source fingerprint"
                        if not checkpoint_sha
                        else "English Final 已變更"
                    )
                    print(
                        f"[CHECKPOINT] {reason}；"
                        "忽略舊 Gemini multi checkpoint，避免沿用無法驗證的翻譯。",
                        flush=True,
                    )
                    checkpoint = None
                else:
                    for row in checkpoint.get("translations") or []:
                        translations[int(row["segment_id"])] = row
                    qa_batches = dict(checkpoint.get("qa_batches") or {})
                    seq = int(checkpoint.get("checkpoint_seq") or 0)
                    print(
                        f"[RESUME] {source}; translations={len(translations)}; "
                        f"qa={len(qa_batches)}; "
                        f"source_sha256={source_sha256[:12]}",
                        flush=True,
                    )

        # Repair unresolved QA from a previous interrupted run before
        # translating new segments. This is the key checkpoint-resume path:
        # never restart an already translated batch merely because one QA pair
        # remained unresolved.
        for key, data in list(qa_batches.items()):
            unresolved_rows = [
                item for item in (data.get("unresolved") or [])
                if str(item.get("lang") or "") in requested
            ]
            if not unresolved_rows:
                continue

            ids = [int(x) for x in (data.get("segment_ids") or [])]
            if not ids or any(sid not in translations for sid in ids):
                continue

            print(
                f"[RESUME-QA] {key}: unresolved={len(unresolved_rows)}",
                flush=True,
            )
            batch = [source_map[sid] for sid in ids]
            initial = {}
            for item in unresolved_rows:
                initial[(int(item["segment_id"]), str(item["lang"]))] = list(
                    item.get("issues") or []
                )

            failures, local, semantic, repairs, models = repair_batch_until_clean(
                client,
                batch,
                translations,
                source_map,
                glossary,
                requested,
                wait_seconds=args.wait_seconds,
                initial_failures=initial,
                max_rounds=4,
                nvidia_client=nvidia_client,
            )
            data["local_failures"] = local
            data["semantic_failures"] = semantic
            data.setdefault("repairs", []).extend(repairs)
            data["repair_model"] = ",".join(x for x in models if x)
            data["unresolved"] = [
                {"segment_id": sid, "lang": lang, "issues": issues}
                for (sid, lang), issues in sorted(failures.items())
            ]
            qa_batches[key] = data

            seq += 1
            save_persistent_checkpoint(
                args.task_id,
                checkpoint_payload(
                    args.task_id,
                    len(source_segments),
                    translations,
                    qa_batches,
                    seq,
                    source_sha256,
                ),
                drive=drive,
                translation_folder_id=folders["translation"],
                workdir=workdir,
                require_persistent=True,
            )
            print(
                f"[RESUME-QA] {key} saved; unresolved={len(failures)}",
                flush=True,
            )

            if failures:
                raise RuntimeError(
                    "Checkpoint Targeted Repair 仍有 QA failure：" +
                    json.dumps(data["unresolved"], ensure_ascii=False)
                )

        remaining = [x for x in source_segments if int(x["id"]) not in translations]
        batches = [
            remaining[i:i + args.batch_size]
            for i in range(0, len(remaining), args.batch_size)
        ]

        for batch_no, batch in enumerate(batches, start=1):
            ids = [int(x["id"]) for x in batch]
            key = f"{ids[0]}-{ids[-1]}"
            print(f"\n[BATCH {batch_no}/{len(batches)}] {ids[0]} -> {ids[-1]}", flush=True)

            rows, translation_engine = translate_batch_with_provider_fallback(
                client,
                nvidia_client,
                batch,
                glossary,
                requested,
            )
            expected = sorted(ids)
            got = sorted(int(x["segment_id"]) for x in rows)
            if expected != got:
                raise RuntimeError(f"Translation ids 不完整：expected={expected}, got={got}")

            for row in rows:
                sid = int(row["segment_id"])
                for lang in requested:
                    if not str(row.get(lang) or "").strip():
                        raise RuntimeError(f"segment {sid} 缺少 {lang}")
                translations[sid] = row

            seq += 1
            save_persistent_checkpoint(
                args.task_id,
                checkpoint_payload(
                    args.task_id,
                    len(source_segments),
                    translations,
                    qa_batches,
                    seq,
                    source_sha256,
                ),
                drive=drive,
                translation_folder_id=folders["translation"],
                workdir=workdir,
                require_persistent=True,
            )
            print("✅ Translation persistent checkpoint saved", flush=True)

            failures, local, semantic, repairs, repair_models = (
                repair_batch_until_clean(
                    client,
                    batch,
                    translations,
                    source_map,
                    glossary,
                    requested,
                    wait_seconds=args.wait_seconds,
                    max_rounds=4,
                    nvidia_client=nvidia_client,
                )
            )

            qa_batches[key] = {
                "segment_ids": ids,
                "translation_engine": translation_engine,
                "local_failures": local,
                "semantic_failures": semantic,
                "repairs": repairs,
                "repair_model": ",".join(x for x in repair_models if x),
                "unresolved": [
                    {"segment_id": sid, "lang": lang, "issues": issues}
                    for (sid, lang), issues in sorted(failures.items())
                ],
            }

            seq += 1
            save_persistent_checkpoint(
                args.task_id,
                checkpoint_payload(
                    args.task_id,
                    len(source_segments),
                    translations,
                    qa_batches,
                    seq,
                    source_sha256,
                ),
                drive=drive,
                translation_folder_id=folders["translation"],
                workdir=workdir,
                require_persistent=True,
            )
            print(
                f"✅ QA checkpoint saved; unresolved={len(failures)}",
                flush=True,
            )

            if failures:
                raise RuntimeError(
                    "Targeted Repair 後仍有翻譯 QA failure：" +
                    json.dumps(qa_batches[key]["unresolved"], ensure_ascii=False)
                )

            if batch_no < len(batches) and args.wait_seconds:
                time.sleep(args.wait_seconds)

        missing = [int(x["id"]) for x in source_segments if int(x["id"]) not in translations]
        if missing:
            raise RuntimeError(f"仍有未翻譯 segments：{missing}")

        unresolved = []
        for data in qa_batches.values():
            unresolved.extend(data.get("unresolved") or [])
        if unresolved:
            raise RuntimeError("既有 checkpoint 仍有 unresolved QA failure")

        rows = [translations[int(x["id"])] for x in source_segments]
        nvidia_repair_used = any(
            str(repair.get("engine") or "") == "nvidia-riva"
            for data in qa_batches.values()
            for repair in (data.get("repairs") or [])
        )
        nvidia_fallback_used = any(
            str(data.get("translation_engine") or "") == "nvidia-riva-fallback"
            for data in qa_batches.values()
        )
        if nvidia_fallback_used:
            output_engine = "gemini+nvidia-riva-fallback"
        elif nvidia_repair_used:
            output_engine = "gemini+nvidia-second-opinion"
        else:
            output_engine = "gemini"

        outdir = workdir / "final"
        outdir.mkdir(parents=True, exist_ok=True)
        for lang in requested:
            for path in write_language_set(
                outdir,
                lang,
                source_segments,
                rows,
                DEFAULT_TEXT_MODEL,
                engine=output_engine,
            ):
                upload_or_replace_file(
                    drive,
                    folders["translation"],
                    path,
                    path.name,
                    display_name=formal_drive_name(task, path.name),
                )

        qa_path = outdir / "gemini.qa.json"
        qa_path.write_text(
            json.dumps(
                {
                    "task_id": args.task_id,
                    "engine": output_engine,
                    "model": DEFAULT_TEXT_MODEL,
                    "nvidia_second_opinion_used": nvidia_used,
                    "qa_batches": qa_batches,
                    "unresolved": [],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        upload_or_replace_file(
            drive,
            folders["translation"],
            qa_path,
            qa_path.name,
            display_name=formal_drive_name(task, qa_path.name),
        )

        updates = {
            f"任務佇列!S{task['sheet_row']}": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            f"任務佇列!T{task['sheet_row']}": (
                "Gemini翻譯+QA完成；語言=" + ",".join(requested)
                + f"；{len(source_segments)}段；QA unresolved=0"
                + ("；NVIDIA second-opinion=used" if nvidia_used else "")
            ),
        }
        for lang, col in LEGACY_COLS.items():
            if lang in requested:
                updates[f"任務佇列!{col}{task['sheet_row']}"] = "完成"
        update_cells(sheets, SPREADSHEET_ID, updates)

        final_cp = checkpoint_payload(
            args.task_id,
            len(source_segments),
            translations,
            qa_batches,
            seq + 1,
            source_sha256,
        )
        final_cp["status"] = "complete"
        save_persistent_checkpoint(
            args.task_id,
            final_cp,
            drive=drive,
            translation_folder_id=folders["translation"],
            workdir=workdir,
            require_persistent=True,
        )

        mark_done(
            args.task_id,
            "multi",
            sheets=sheets,
            run_id=run_id,
            message=(
                "Gemini 翻譯 + QA 完成；langs=" + ",".join(requested)
                + "；unresolved=0"
                + ("；NVIDIA=second-opinion" if nvidia_used else "")
            ),
        )
        print(
            "[DONE] Gemini 正式翻譯完成；langs="
            + ",".join(requested)
            + "；QA unresolved=0",
            flush=True,
        )
        return 0

    except Exception as exc:
        mark_error(
            args.task_id,
            "multi",
            sheets=sheets,
            run_id=run_id,
            exc=exc,
        )
        print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
