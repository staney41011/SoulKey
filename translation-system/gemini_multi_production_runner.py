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
from decimal import Decimal, InvalidOperation
from pathlib import Path

# Windows production runners may inherit a CP950 console. Force UTF-8 so
# multilingual logs (including Hindi/Tamil and status symbols) can never
# abort the actual translation/TTS job.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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
from translation_text_safety import filter_nonspoken_segments
from nvidia_translate import NvidiaTranslateClient, SUPPORTED_TARGETS_V2 as SUPPORTED_TARGETS
from status_io import new_run_id, mark_done, mark_error, mark_running, mark_needs_review


LANGS = ["th", "es", "id", "vi", "hi", "ta", "ja", "ko", "km", "bn", "ne", "lo", "my", "it", "pt"]
LANGUAGE_NAMES = {
    "th": "Thai",
    "es": "Spanish",
    "id": "Indonesian",
    "vi": "Vietnamese",
    "hi": "Hindi",
    "ta": "Tamil",
    "ja": "Japanese",
    "ko": "Korean",
    "km": "Khmer",
    "bn": "Bengali",
    "ne": "Nepali",
    "lo": "Lao",
    "my": "Burmese",
    "it": "Italian",
    "pt": "Portuguese (Brazil)",
}
LEGACY_COLS = {"th": "K", "es": "L", "id": "M", "vi": "N"}
REPAIR_MODEL = os.getenv("SOULKEY_REPAIR_MODEL", DEFAULT_TEXT_MODEL)
CHECKPOINT_SCHEMA_VERSION = 4

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
                    "hi": {"type": "string"},
                    "ta": {"type": "string"},
                    "ja": {"type": "string"},
                    "ko": {"type": "string"},
                    "km": {"type": "string"},
                    "bn": {"type": "string"},
                    "ne": {"type": "string"},
                    "lo": {"type": "string"},
                    "my": {"type": "string"},
                    "it": {"type": "string"},
                    "pt": {"type": "string"},
                },
                "required": ["segment_id", "th", "es", "id", "vi", "hi", "ta", "ja", "ko", "km", "bn", "ne", "lo", "my", "it", "pt"],
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


def write_language_set(
    output_dir,
    lang,
    source_segments,
    translations,
    model,
    engine="gemma4",
    source_sha256="",
):
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

    # Final manuscript hygiene: keep speech-bearing translations, omit
    # punctuation-only/empty subtitles before exporting JSON, TXT and SRT.
    # Do not renumber other segments or change their original timestamps.
    segments, nonspoken = filter_nonspoken_segments(segments)
    if not segments:
        raise RuntimeError(f"{lang} has no pronounceable translated text")
    if nonspoken:
        print(
            f"[MULTI:SPEECH-SAFETY] {lang}: omitted {len(nonspoken)} "
            "punctuation-only subtitle segment(s) from manuscript and TTS",
            flush=True,
        )
        long_gaps = [str(x["id"]) for x in nonspoken
                     if x.get("source_review_recommended")]
        if long_gaps:
            print(
                f"[MULTI:SOURCE-REVIEW] {lang}: nonspoken source windows "
                f">=3s at segments {','.join(long_gaps)}; source audio may "
                "need transcription QA; no lecture content invented",
                flush=True,
            )
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
                "source_sha256": str(source_sha256 or ""),
                "segments": segments,
                "filtered_nonspoken_segments": nonspoken,
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
        row = list(raw) + [""] * max(0, 21 - len(raw))
        zh = str(row[0] or "").strip()
        en = str(row[3] or "").strip()
        if not (zh or en):
            continue
        parts = [f"source={en or zh}"]
        for code, idx in [("th", 4), ("es", 5), ("id", 6), ("vi", 7),
                          ("hi", 10), ("ta", 11), ("ja", 12), ("ko", 13), ("km", 14),
                          ("bn", 15), ("ne", 16), ("lo", 17), ("my", 18), ("it", 19), ("pt", 20)]:
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
Translate every approved English segment into all fifteen target languages:
th Thai, es Spanish, id Indonesian, vi Vietnamese, hi Hindi, ta Tamil, ja Japanese, ko Korean, km Khmer,
bn Bengali, ne Nepali, lo Lao, my Burmese, it Italian, pt Portuguese (Brazil).

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
Compare numeric QUANTITIES rather than literal numeral glyphs:
English 2.5 billion = Japanese 25億 = Korean 25억, and English
8 billion = Japanese 80億 = Korean 80억. In contrast 2.5億/2.5억
is 250 million, not 2.5 billion. Accept correct localized units;
reject changes in the actual mathematical value.
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
    # Hosted Gemma may emit two JSON objects / truncated JSON under load.
    # Retry with a smaller prompt rather than publishing malformed text.
    "structured output invalid json",
    "structured output empty",
)


def is_transient_gemini_error(exc):
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(marker.lower() in text for marker in TRANSIENT_GEMINI_MARKERS)


def is_hard_quota_error(exc):
    """A daily/RPD ceiling cannot be fixed with a seconds-long retry."""
    message = str(exc).lower()
    return "http 429" in message and any(
        phrase in message for phrase in (
            "requests per day", "per day", "retry in", "daily quota",
        )
    )


class TranslationFailoverClient:
    """Retry hosted Gemma 4 before trying an independent model.

    Every language subgroup starts with Gemma 4, including subgroups following
    a fallback success. This avoids a persistent breaker silently switching
    most of a course to the free-tier Gemini fallback.

    A daily rate-limit error is not resolved by an immediate retry: in that
    case stop retrying the exhausted model and try the configured fallback.
    Successful translations are still checkpointed by the calling runner.
    """

    def __init__(
        self,
        client,
        fallback_model=None,
        cooldown_seconds=600,
        primary_attempts=None,
    ):
        self.client = client
        self.text_model = client.text_model
        self.fallback_model = str(
            fallback_model if fallback_model is not None
            else os.getenv("SOULKEY_GEMMA4_FAILOVER_MODEL", "gemini-3.5-flash")
        ).strip()
        raw_attempts = (
            primary_attempts if primary_attempts is not None
            else os.getenv("SOULKEY_GEMMA4_PRIMARY_ATTEMPTS", "3")
        )
        self.primary_attempts = max(1, min(5, int(raw_attempts)))
        # Kept for compatibility with previously exposed status fields.
        # Never use the old cooldown to skip Gemma 4 on future subgroups.
        self.cooldown_seconds = cooldown_seconds
        self.cooldown_until = 0.0
        self.fallback_used = False
        self.models_used = set()

    def structured(self, prompt, schema, **kwargs):
        requested_model = str(kwargs.get("model") or self.text_model)
        fallback_allowed = bool(
            requested_model == self.text_model
            and self.fallback_model
            and self.fallback_model.lower() not in {"none", "off", "false"}
            and requested_model != self.fallback_model
        )
        primary_attempts = (
            self.primary_attempts
            if requested_model.startswith("gemma-4-")
            else 1
        )
        last_primary_error = None

        for attempt in range(1, primary_attempts + 1):
            try:
                result = self.client.structured(prompt, schema, **kwargs)
                self.models_used.add(requested_model)
                if attempt > 1:
                    print(
                        f"[GEMMA4-RECOVERED] primary succeeded on "
                        f"attempt {attempt}/{primary_attempts}",
                        flush=True,
                    )
                return result
            except Exception as exc:
                last_primary_error = exc
                if not is_transient_gemini_error(exc):
                    raise
                if is_hard_quota_error(exc):
                    # Do not waste same-day quota on repeated requests.
                    print(
                        "[GEMMA4-QUOTA] skipping identical immediate retries",
                        flush=True,
                    )
                    break
                if attempt >= primary_attempts:
                    break
                wait = min(2 ** attempt, 8)
                print(
                    f"[GEMMA4-RETRY] {requested_model} temporary failure "
                    f"{attempt}/{primary_attempts}; retry in {wait}s: "
                    f"{type(exc).__name__}",
                    flush=True,
                )
                time.sleep(wait)

        if not fallback_allowed:
            raise last_primary_error

        print(
            f"[MODEL-FAILOVER] {requested_model} exhausted "
            f"{attempt}/{primary_attempts} primary attempts; "
            f"using {self.fallback_model}",
            flush=True,
        )
        fallback_kwargs = dict(kwargs)
        fallback_kwargs["model"] = self.fallback_model
        try:
            result = self.client.structured(prompt, schema, **fallback_kwargs)
        except Exception as exc:
            # On the next subgroup/retry Gemma 4 must be tried again.
            self.cooldown_until = 0.0
            print(
                f"[MODEL-FAILOVER] {self.fallback_model} also failed: "
                f"{type(exc).__name__}: {str(exc)[:240]}",
                flush=True,
            )
            raise
        self.fallback_used = True
        self.models_used.add(self.fallback_model)
        return result

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


def selected_glossary_text(glossary, langs):
    """Remove unrelated target-language columns from the 120-row glossary."""
    wanted = set(langs)
    output = []
    for line in str(glossary or "").splitlines():
        parts = [part.strip() for part in line.split("|")]
        relevant = [
            part for part in parts
            if part.startswith("- source=") or part == "LOCKED" or
            part.split("=", 1)[0] in wanted
        ]
        if len(relevant) > 1:
            output.append(" | ".join(relevant))
    return "\n".join(output) or "(no applicable glossary entries)"


def selected_translation_prompt(batch, glossary, langs):
    glossary = selected_glossary_text(glossary, langs)
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


def gemini_translate_with_backoff(client, batch, glossary, langs, waits=(4, 12)):
    # The production Gemma wrapper already tries its primary three times.
    # Do not multiply that into nine 95-second requests per subgroup.
    if isinstance(client, TranslationFailoverClient):
        waits = ()
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
            if (not is_transient_gemini_error(exc)
                    or is_hard_quota_error(exc)
                    or attempt > len(waits)):
                raise
            wait_seconds = waits[attempt - 1]
            if "structured output" in str(exc).lower():
                wait_seconds = min(wait_seconds, 5 * (2 ** (attempt - 1)))
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
            try:
                candidate = nvidia_client.translate(english, lang).strip()
                issue = local_language_issue(candidate, english, lang)
                if issue:
                    raise RuntimeError(
                        f"NVIDIA fallback local QA failed: {sid}/{lang}/{issue}"
                    )
                numeric_issues = translated_number_issues(
                    english, candidate, lang
                )
                if numeric_issues:
                    raise RuntimeError(
                        f"NVIDIA fallback numeric QA failed: "
                        f"{sid}/{lang}/{','.join(numeric_issues)}"
                    )
                rows[sid][lang] = candidate
            except (KeyError, ValueError, RuntimeError) as exc:
                # A provider may reject one target language. The rest of
                # the batch remains useful, but missing languages MUST be
                # filled by another provider before publication.
                print(
                    f"[NVIDIA-FALLBACK] {sid}/{lang} unavailable: "
                    f"{type(exc).__name__}; pending LLM recovery",
                    flush=True,
                )
    return rows


def translate_batch_with_provider_fallback(
    client,
    nvidia_client,
    batch,
    glossary,
    requested,
):
    """Keep Gemini primary; use NVIDIA only after transient Gemini exhaustion.

    NVIDIA Riva v2 covers nine SoulKey targets including Japanese,
    Korean, Hindi, Italian and Portuguese; the remaining six stay on LLMs.
    """
    try:
        parsed = gemini_translate_with_backoff(
            client,
            batch,
            glossary,
            requested,
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
        unsupported = [
            lang for lang in requested
            if any(lang not in rows_by_id.get(int(src["id"]), {}) for src in batch)
        ]

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
                waits=(5, 15),
            )
            for item in parsed.get("segments") or []:
                sid = int(item["segment_id"])
                rows_by_id.setdefault(sid, {"segment_id": sid})
                for lang in unsupported:
                    rows_by_id[sid][lang] = str(item.get(lang) or "").strip()

        rows = [rows_by_id[int(src["id"])] for src in batch]
        return rows, "nvidia-riva-fallback"

def build_translation_batches(remaining, max_segments=2, max_chars=900):
    """Bound long-lecture payloads without losing sparse source IDs.

    For 15 target languages a pair of 800-character paragraphs becomes a
    single-source-segment request; short paragraphs can still share a call.
    """
    batches = []
    batch = []
    chars = 0
    for source in remaining:
        size = len(str(source.get("text") or ""))
        if batch and (
            len(batch) >= max_segments
            or chars + size > max_chars
            or size >= max_chars * 0.75
        ):
            batches.append(batch)
            batch = []
            chars = 0
        batch.append(source)
        chars += size
    if batch:
        batches.append(batch)
    return batches


def translate_batch_with_missing_id_recovery(
    client, nvidia_client, batch, glossary, requested, max_retries=2
):
    """Recover omitted IDs without discarding translated sibling segments.

    The approved English Final may use sparse IDs (such as 18 and 22).
    A structured provider can return only one of the two. Retry the
    missing source ID alone and reject unexpected IDs, duplicate IDs,
    or unfilled target languages. Never synthesize a translation.
    """
    expected_ids = [int(src["id"]) for src in batch]
    if len(expected_ids) != len(set(expected_ids)):
        raise RuntimeError("duplicate approved source segment ids")
    accepted = {}
    pending = list(batch)
    engines = []

    for attempt in range(max_retries + 1):
        if not pending:
            break
        rows, engine = translate_batch_with_provider_fallback(
            client, nvidia_client, pending, glossary, requested
        )
        engines.append(engine)
        pending_ids = {int(src["id"]) for src in pending}
        observed = set()
        for row in rows:
            sid = int(row["segment_id"])
            if sid not in pending_ids:
                raise RuntimeError(
                    f"Translation unexpected id {sid}; requested={sorted(pending_ids)}"
                )
            if sid in observed or sid in accepted:
                raise RuntimeError(f"Translation duplicate id: {sid}")
            observed.add(sid)
            unfilled = row_missing_languages(row, requested)
            if unfilled:
                print(
                    f"[MISSING-TRANSLATION] segment={sid}; "
                    f"languages={','.join(unfilled)}; retry only missing ID",
                    flush=True,
                )
                continue
            accepted[sid] = row
        pending = [
            src for src in pending
            if int(src["id"]) not in accepted
        ]
        if pending:
            print(
                f"[MISSING-ID-RECOVERY] retry {attempt + 1}/{max_retries + 1}; "
                f"missing={','.join(str(x['id']) for x in pending)}",
                flush=True,
            )

    if pending:
        raise RuntimeError(
            "Translation ids still missing after targeted retries: "
            + ",".join(str(x["id"]) for x in pending)
        )
    rows = [accepted[sid] for sid in expected_ids]
    engine = (
        "nvidia-riva-fallback" if "nvidia-riva-fallback" in engines
        else "gemini"
    )
    return rows, engine


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


_ENGLISH_SCALED_NUMBER = re.compile(
    r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s+"
    r"(billion|million|trillion|thousand)\b",
    flags=re.IGNORECASE,
)
_CJK_SCALED_NUMBER = re.compile(
    r"(?<![\d.])(\d[\d,]*(?:\.\d+)?)\s*"
    r"(億|亿|억|萬|万|만|兆|조)"
)
_ENGLISH_UNITS = {"thousand":1e3,"million":1e6,"billion":1e9,"trillion":1e12}
_CJK_UNITS = {
    "萬":1e4,"万":1e4,"만":1e4,
    "億":1e8,"亿":1e8,"억":1e8,
    "兆":1e12,"조":1e12,
}


# Italian and Portuguese use a comma as a decimal separator and a dot as
# the thousands separator. Numeric QA must compare values, not substrings:
# 2.5 == 2,5, but 2.5 != 12,5 or 25.
_LOCALE_SOURCE_NUMBER = re.compile(
    r"(?<![\\w])(?:\\d{1,3}(?:,\\d{3})+(?:\\.\\d+)?|\\d+(?:\\.\\d+)?)(?![\\w])"
)
_LOCALE_TARGET_NUMBER = re.compile(r"(?<![\\w])\\d+(?:[.,]\\d+)*(?![\\w])")


def _decimal_localized_number(token):
    """Parse pt/it number tokens conservatively; 2.500 is 2500."""
    value = str(token)
    if "," in value and "." in value:
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    elif "," in value:
        value = value.replace(",", ".")
    elif "." in value:
        parts = value.split(".")
        if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]):
            value = "".join(parts)
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _locale_number_issues(english, target):
    normalized_target = normalize_unicode_digits(target)
    expected = [
        (match.group(), Decimal(match.group().replace(",", "")))
        for match in _LOCALE_SOURCE_NUMBER.finditer(normalize_unicode_digits(english))
    ]
    observed = set()
    for match in _LOCALE_TARGET_NUMBER.finditer(normalized_target):
        token = match.group()
        parsed = _decimal_localized_number(token)
        if parsed is not None:
            observed.add(parsed)
        # The untranslated English decimal spelling is also unambiguous.
        if "." in token and "," not in token:
            parts = token.split(".")
            grouping = len(parts) > 1 and all(len(part) == 3 for part in parts[1:])
            if not grouping:
                try:
                    observed.add(Decimal(token))
                except InvalidOperation:
                    pass
    return [
        f"missing_number:{original}"
        for original, value in expected
        if value not in observed
    ]


def translated_number_issues(english,target,lang):
    """Preserve ACTUAL values, including correct localized magnitudes.

    English 2.5 billion means 25億 / 25억 (2,500,000,000), not
    2.5億 / 2.5억 (250,000,000). A glyph-only check wrongly rejects
    correct 25億 because the literal text "2.5" disappears.
    """
    if lang in {"it", "pt"}:
        return _locale_number_issues(english, target)
    normalized=normalize_unicode_digits(target)
    numbers=re.findall(r"\d+(?:\.\d+)?",english)
    if lang not in {"ja","ko"}:
        return [f"missing_number:{v}" for v in numbers if v not in normalized]

    localized=[
        (float(digits.replace(",",""))*_CJK_UNITS[unit],digits,unit)
        for digits,unit in _CJK_SCALED_NUMBER.findall(normalized)
    ]
    scaled=list(_ENGLISH_SCALED_NUMBER.finditer(english))
    covered=set()
    issues=[]
    for item in scaled:
        digits=item.group(1).replace(",","")
        number=item.group(1)
        unit=item.group(2).lower()
        expected=float(digits)*_ENGLISH_UNITS[unit]
        covered.add(item.start(1))
        if localized:
            correct=any(abs(amount-expected)<=max(1.0,expected*1e-8)
                        for amount,_,_ in localized)
            if not correct:
                issues.append(f"incorrect_number_scale:{number} {unit}")
        elif number not in normalized:
            issues.append(f"missing_number:{number}")
    # Validate every other literal number, but exempt numbers whose value has
    # already been checked after conversion to local units.
    plain=[x for x in re.finditer(r"\d+(?:\.\d+)?",english)
           if x.start() not in covered]
    for item in plain:
        if item.group() not in normalized:
            issues.append(f"missing_number:{item.group()}")
    return issues


def local_failures(batch, rows, langs):
    by_id = {int(x["segment_id"]): x for x in rows}
    failures = []
    for src in batch:
        sid = int(src["id"])
        english = str(src["text"])
        for lang in langs:
            target = str(by_id[sid].get(lang) or "").strip()
            issues = []
            issue = local_language_issue(target, english, lang)
            if issue:
                issues.append(issue)
            issues.extend(translated_number_issues(english,target,lang))
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
Numbers MUST preserve their mathematical magnitude when translating unit words.
For example: English "2.5 billion" = Japanese "25億" / Korean "25억",
NOT Japanese "2.5億" / Korean "2.5억"; English "8 billion" =
Japanese "80億" / Korean "80억". Preserve all values and labels accurately.
Keep segment_id and lang unchanged.
Use natural Thai script for th, Hindi or Nepali Devanagari for hi/ne, Bengali script for bn, Tamil script for ta, Japanese kana/kanji for ja, Korean Hangul for ko, Khmer script for km, Lao script for lo, Myanmar script for my, and fluent Italian/Portuguese for it/pt. Proper names
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

    # The original 15-language QA prompt was huge and shared the
    # same provider timeout problem as translation. Audit independent
    # three-language groups, but still require every language to pass.
    semantic = []
    for group in translation_target_groups(langs, batch=batch):
        prompt = qa_prompt(batch, rows, group)
        qa = None
        # Production wrapper has its own bounded primary retries.
        waits = [] if isinstance(client, TranslationFailoverClient) else [4, 12]
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
                if (not is_transient_gemini_error(exc)
                        or is_hard_quota_error(exc)
                        or attempt > len(waits)):
                    raise
                wait_seconds_retry = waits[attempt - 1]
                print(
                    f"[QA-AUTO-RESUME] group={','.join(group)}; retry "
                    f"{attempt + 1}/{len(waits)+1} after {wait_seconds_retry}s: "
                    f"{type(exc).__name__}: {str(exc)[:240]}",
                    flush=True,
                )
                time.sleep(wait_seconds_retry)
        semantic.extend((qa or {}).get("failures") or [])
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

        local_issues.extend(translated_number_issues(
            english,candidate,lang
        ))

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
    languages=None,
):
    active_languages = [
        lang for lang in LANGS
        if lang in set(languages or LANGS)
    ]
    return {
        "version": CHECKPOINT_SCHEMA_VERSION,
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "task_id": task_id,
        "engine": "gemma4-production-multi",
        "model": DEFAULT_TEXT_MODEL,
        "source_segments": source_count,
        "source_sha256": source_sha256,
        "languages": active_languages,
        "checkpoint_seq": seq,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "translations": [translations[k] for k in sorted(translations)],
        "qa_batches": qa_batches,
    }



def record_language_result(data, lang, segment_ids, failures=None, error=None, stage="qa"):
    """A single failed target is deferred; other languages remain runnable.

    Never mark an unverified translation as QA-passed. Persist the unresolved
    (segment_id, language, stage, reason) for the next checkpointed run.
    """
    data.setdefault("segment_ids", list(segment_ids))
    data.setdefault("verified_languages", [])
    data.setdefault("unresolved", [])
    data["unresolved"] = [
        row for row in data["unresolved"]
        if str(row.get("lang") or "") != lang
    ]
    verified = set(data["verified_languages"])
    verified.discard(lang)
    if error is not None:
        issue = f"{stage}: {type(error).__name__}: {str(error)[:220]}"
        data["unresolved"].extend({
            "segment_id": int(sid), "lang": lang, "stage": stage,
            "issues": [issue],
        } for sid in segment_ids)
    elif failures:
        for (sid, failed_lang), issues in sorted(failures.items()):
            if failed_lang == lang:
                data["unresolved"].append({
                    "segment_id": int(sid), "lang": lang,
                    "stage": "qa", "issues": list(issues),
                })
    else:
        verified.add(lang)
    data["verified_languages"] = sorted(verified)
    return data


def verified_languages_for_delivery(source_segments, translations, qa_batches, requested):
    """A language can be published only with every source ID and QA pass."""
    expected = {int(src["id"]) for src in source_segments}
    ready = []
    for lang in requested:
        if any(
            not str(translations.get(sid, {}).get(lang) or "").strip()
            for sid in expected
        ):
            continue
        audited = set()
        for data in qa_batches.values():
            batch_ids = {int(sid) for sid in data.get("segment_ids") or []}
            if not batch_ids:
                continue
            if lang in set(data.get("verified_languages") or []):
                audited.update(batch_ids)
            elif "verified_languages" not in data:
                # Legacy checkpoint: QA batches were atomic across all
                # requested languages. Their unresolved list is authoritative.
                unresolved_langs = {
                    str(row.get("lang") or "")
                    for row in data.get("unresolved") or []
                }
                if lang not in unresolved_langs and (
                    "semantic_failures" in data and "local_failures" in data
                ):
                    audited.update(batch_ids)
        if expected.issubset(audited):
            ready.append(lang)
    return ready


def row_missing_languages(row, requested):
    row = row or {}
    return [
        lang for lang in requested
        if not str(row.get(lang) or "").strip()
    ]


def translation_target_groups(requested, max_languages=3, batch=None):
    """Checkpoint Riva-supported languages first; shrink groups for long text.

    Live provider verification (2026-11-04): 851 source characters into
    three languages timed out at 95s, while the exact same English segment
    into one language completed in about 7.5s. Bound output size based on
    source length instead of merely increasing the retry count.
    """
    if max_languages < 1:
        raise ValueError("max_languages must be positive")
    if batch:
        source_chars = sum(len(str(src.get("text") or "")) for src in batch)
        if source_chars >= 650:
            max_languages = min(max_languages, 1)
        elif source_chars >= 450:
            max_languages = min(max_languages, 2)
    ordered = (
        [x for x in requested if x in SUPPORTED_TARGETS] +
        [x for x in requested if x not in SUPPORTED_TARGETS]
    )
    return [
        ordered[i:i + max_languages]
        for i in range(0, len(ordered), max_languages)
    ]


def incomplete_source_segments(source_segments, translations, requested):
    result = []
    for src in source_segments:
        sid = int(src["id"])
        if row_missing_languages(translations.get(sid), requested):
            result.append(src)
    return result


def merge_translation_rows(translations, generated_rows, generated_langs):
    for generated in generated_rows:
        sid = int(generated["segment_id"])
        current = dict(translations.get(sid) or {"segment_id": sid})
        for lang in generated_langs:
            value = str(generated.get(lang) or "").strip()
            if not value:
                raise RuntimeError(f"segment {sid} 缺少 {lang}")
            current[lang] = value
        translations[sid] = current


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--langs", default="th,es,id,vi,hi,ta,ja,ko,km,bn,ne,lo,my,it,pt")
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
    if args.batch_size < 1:
        raise RuntimeError("--batch-size 必須大於 0")
    # Gemma 4 timed out on P260-L01's long English paragraphs when one
    # request demanded all 15 target languages. Bound BOTH dimensions;
    # checkpoints below persist every language subgroup independently.
    effective_batch_size = min(args.batch_size, 2) if len(requested)>10 else (
        min(args.batch_size, 4) if len(requested)>6 else args.batch_size
    )

    # Infer only selected languages; QA, repair, publishing, and completion
    # are scoped to Studio's requested
    # languages so an unselected language cannot block the job.

    drive, sheets = build_google_services()
    task = find_task(sheets, args.task_id)
    if not task:
        raise RuntimeError(f"找不到任務：{args.task_id}")
    if task["period"] is None or not task["lesson"]:
        raise RuntimeError("任務缺少期數或堂次")

    folders = resolve_lesson_folders(drive, sheets, int(task["period"]), task["lesson"])
    workdir = Path(os.environ.get("SOULKEY_GEMINI_MULTI_WORKDIR", "/kaggle/working/gemini-multi")) / args.task_id
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
    # Hosted Gemma 4 succeeds with one-segment requests but can exceed
    # 40 seconds for a multi-language lecture paragraph. Allow longer
    # responses and keep bounded three-attempt retries at the model layer.
    # Avoid nested retry multiplication and preserve batch checkpoints.
    gemma_timeout = max(45, min(150, int(
        os.getenv("SOULKEY_GEMMA4_TIMEOUT_SECONDS", "95")
    )))
    client = TranslationFailoverClient(GeminiClient(
        api_key=api_key,
        text_model=DEFAULT_TEXT_MODEL,
        max_attempts=1,
        timeout=gemma_timeout,
    ))
    print(
        f"[GEMMA4-CONFIG] model={DEFAULT_TEXT_MODEL}; "
        f"timeout={gemma_timeout}s; "
        f"primary_attempts={client.primary_attempts}",
        flush=True,
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
        message=f"Gemma 4 {len(requested)}語翻譯 + QA 執行中",
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
            if checkpoint and checkpoint.get("engine") in {"gemini-production-multi", "gemma4-production-multi"}:
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
                    checkpoint_languages = [
                        str(x) for x in (checkpoint.get("languages") or [])
                    ]
                    checkpoint_schema = int(
                        checkpoint.get("schema_version")
                        or checkpoint.get("version")
                        or 0
                    )
                    for row in checkpoint.get("translations") or []:
                        sid = int(row["segment_id"])
                        clean_row = {"segment_id": sid}
                        for lang in LANGS:
                            value = str(row.get(lang) or "").strip()
                            if value:
                                clean_row[lang] = value
                        translations[sid] = clean_row

                    qa_batches = dict(checkpoint.get("qa_batches") or {})
                    for data in qa_batches.values():
                        data["unresolved"] = [
                            item for item in (data.get("unresolved") or [])
                            if str(item.get("lang") or "") in requested
                        ]
                        # Prior releases completed QA atomically for a batch.
                        # Preserve languages that already passed when
                        # upgrading to per-language isolated QA state.
                        if ("verified_languages" not in data
                                and "semantic_failures" in data
                                and "local_failures" in data):
                            ids = [int(i) for i in data.get("segment_ids") or []]
                            unresolved_langs = {
                                str(row.get("lang") or "")
                                for row in data["unresolved"]
                            }
                            data["verified_languages"] = [
                                lang for lang in checkpoint_languages
                                if lang in requested
                                and lang not in unresolved_langs
                                and ids
                                and all(str(translations.get(sid, {}).get(lang)
                                            or "").strip() for sid in ids)
                            ]
                    seq = int(checkpoint.get("checkpoint_seq") or 0)

                    missing_counts = {
                        lang: sum(
                            1 for src in source_segments
                            if lang in row_missing_languages(
                                translations.get(int(src["id"])),
                                [lang],
                            )
                        )
                        for lang in requested
                    }
                    missing_summary = ",".join(
                        f"{lang}:{count}"
                        for lang, count in missing_counts.items()
                        if count
                    ) or "none"
                    print(
                        f"[RESUME] {source}; translations={len(translations)}; "
                        f"qa={len(qa_batches)}; "
                        f"schema={checkpoint_schema}; "
                        f"checkpoint_langs={','.join(checkpoint_languages) or 'legacy'}; "
                        f"missing={missing_summary}; "
                        f"source_sha256={source_sha256[:12]}",
                        flush=True,
                    )

                    if checkpoint_schema < CHECKPOINT_SCHEMA_VERSION:
                        print(
                            "[CHECKPOINT-MIGRATION] 舊 schema 可部分沿用；"
                            "已保留既有語言內容，只補目前 requested 缺少的語言。",
                            flush=True,
                        )

        # Resume only failed language/segment pairs from earlier checkpoints.
        # A single unrepairable language must never block other languages.
        for key, data in list(qa_batches.items()):
            unresolved_rows = [
                item for item in (data.get("unresolved") or [])
                if str(item.get("lang") or "") in requested
            ]
            if not unresolved_rows:
                continue
            ids = [int(x) for x in data.get("segment_ids") or []]
            if not ids or any(sid not in source_map for sid in ids):
                continue
            batch = [source_map[sid] for sid in ids]
            for lang in sorted({
                str(item.get("lang") or "") for item in unresolved_rows
            }):
                # Translation-stage errors are handled by the normal
                # per-language translation loop after this QA recovery.
                if any(lang in row_missing_languages(
                    translations.get(sid), [lang]
                ) for sid in ids):
                    continue
                initial = {
                    (int(item["segment_id"]), lang): list(item.get("issues") or [])
                    for item in unresolved_rows
                    if str(item.get("lang") or "") == lang
                }
                print(
                    f"[RESUME-QA-LANGUAGE] batch={key} lang={lang}; "
                    f"failures={len(initial)}",
                    flush=True,
                )
                try:
                    failures, local, semantic, repairs, models = (
                        repair_batch_until_clean(
                            client, batch, translations, source_map,
                            glossary, [lang], wait_seconds=args.wait_seconds,
                            initial_failures=initial, max_rounds=2,
                            nvidia_client=nvidia_client,
                        )
                    )
                    data.setdefault("repairs", []).extend(repairs)
                    data["repair_model"] = ",".join(x for x in models if x)
                    data.setdefault("local_failures", []).extend(local)
                    data.setdefault("semantic_failures", []).extend(semantic)
                    record_language_result(data, lang, ids, failures=failures)
                except Exception as exc:
                    record_language_result(
                        data, lang, ids, error=exc, stage="resume_qa"
                    )
                    print(
                        f"[DEFER-LANGUAGE] previous QA failed: "
                        f"batch={key} lang={lang} cause={type(exc).__name__}",
                        flush=True,
                    )
                qa_batches[key] = data
                seq += 1
                save_persistent_checkpoint(
                    args.task_id,
                    checkpoint_payload(
                        args.task_id, len(source_segments), translations,
                        qa_batches, seq, source_sha256, requested,
                    ),
                    drive=drive,
                    translation_folder_id=folders["translation"],
                    workdir=workdir,
                    require_persistent=True,
                )
                # If this language is still failing, we will continue the
                # other languages and publish only fully QA-passed outputs.

        remaining = incomplete_source_segments(
            source_segments,
            translations,
            requested,
        )
        batches = build_translation_batches(
            remaining,
            max_segments=effective_batch_size,
            max_chars=(900 if len(requested) > 10 else 1600),
        )
        print(
            f"[GEMMA4-PAYLOAD] segments={len(remaining)}; "
            f"bounded_batches={len(batches)}; "
            f"max_segments={effective_batch_size}",
            flush=True,
        )

        for batch_no, batch in enumerate(batches, start=1):
            ids = [int(src["id"]) for src in batch]
            key = f"{ids[0]}-{ids[-1]}"
            missing_langs = [
                lang for lang in requested
                if any(lang in row_missing_languages(
                    translations.get(sid), [lang]
                ) for sid in ids)
            ]
            print(
                f"\\n[BATCH {batch_no}/{len(batches)}] "
                f"{ids[0]} -> {ids[-1]} / fill={','.join(missing_langs)}",
                flush=True,
            )
            data = qa_batches.setdefault(key, {
                "segment_ids": ids,
                "translation_engine": "",
                "local_failures": [],
                "semantic_failures": [],
                "repairs": [],
                "repair_model": "",
                "unresolved": [],
                "verified_languages": [],
            })
            data["segment_ids"] = ids
            translation_engines = []

            # Translate in small language groups for throughput. If a group
            # fails, isolate each language and move to the next language,
            # instead of crashing an entire lecture.
            for group in translation_target_groups(missing_langs, batch=batch):
                group_missing = [
                    lang for lang in group
                    if any(lang in row_missing_languages(
                        translations.get(sid), [lang]
                    ) for sid in ids)
                ]
                if not group_missing:
                    continue
                print(
                    f"[GEMMA4-GROUP] {ids[0]}-{ids[-1]} "
                    f"languages={','.join(group_missing)}",
                    flush=True,
                )

                # A group may be affected by one difficult target language.
                # On group failure, retry only the missing languages one by one.
                try:
                    rows, engine = translate_batch_with_missing_id_recovery(
                        client, nvidia_client, batch, glossary, group_missing
                    )
                    merge_translation_rows(translations, rows, group_missing)
                    translation_engines.append(engine)
                    print(
                        f"[OK] translated {','.join(group_missing)}",
                        flush=True,
                    )
                except Exception as group_exc:
                    if len(group_missing) > 1:
                        print(
                            f"[LANG-ISOLATE] group={','.join(group_missing)} "
                            f"failed ({type(group_exc).__name__}); "
                            "retry each target separately",
                            flush=True,
                        )
                    for lang in group_missing:
                        needed = [
                            src for src in batch
                            if lang in row_missing_languages(
                                translations.get(int(src["id"])), [lang]
                            )
                        ]
                        if not needed:
                            continue
                        try:
                            if len(group_missing) == 1:
                                raise group_exc
                            rows, engine = translate_batch_with_missing_id_recovery(
                                client, nvidia_client, needed, glossary, [lang]
                            )
                            merge_translation_rows(translations, rows, [lang])
                            translation_engines.append(engine)
                            print(
                                f"[OK] isolated translation recovered {lang}",
                                flush=True,
                            )
                        except Exception as exc:
                            record_language_result(
                                data, lang, ids,
                                error=exc, stage="translation",
                            )
                            print(
                                f"[DEFER-LANGUAGE] {key}/{lang} "
                                f"translation failed: {type(exc).__name__}; "
                                "continuing next language",
                                flush=True,
                            )
                data["translation_engine"] = (
                    "nvidia-riva-fallback"
                    if "nvidia-riva-fallback" in translation_engines
                    else "gemma4"
                )
                qa_batches[key] = data
                # Successful translation as well as skipped-language status
                # must be durable before any later QA/provider call.
                seq += 1
                save_persistent_checkpoint(
                    args.task_id,
                    checkpoint_payload(
                        args.task_id, len(source_segments), translations,
                        qa_batches, seq, source_sha256, requested,
                    ),
                    drive=drive,
                    translation_folder_id=folders["translation"],
                    workdir=workdir,
                    require_persistent=True,
                )
                print(
                    f"[CHECKPOINT] language group "
                    f"{','.join(group_missing)} saved",
                    flush=True,
                )

            # QA is isolated per language. A bad Khmer number, for example,
            # cannot prevent Thai, Spanish, Japanese, etc. from being audited.
            for lang in requested:
                missing = [
                    sid for sid in ids
                    if lang in row_missing_languages(
                        translations.get(sid), [lang]
                    )
                ]
                if missing:
                    record_language_result(
                        data, lang, missing,
                        error=RuntimeError("translation missing"),
                        stage="translation",
                    )
                    continue
                if lang in (data.get("verified_languages") or []):
                    continue
                try:
                    failures, local, semantic, repairs, models = (
                        repair_batch_until_clean(
                            client, batch, translations, source_map,
                            glossary, [lang],
                            wait_seconds=args.wait_seconds,
                            max_rounds=2,
                            nvidia_client=nvidia_client,
                        )
                    )
                    data.setdefault("repairs", []).extend(repairs)
                    data.setdefault("local_failures", []).extend(local)
                    data.setdefault("semantic_failures", []).extend(semantic)
                    data["repair_model"] = ",".join(x for x in models if x)
                    record_language_result(data, lang, ids, failures=failures)
                    if failures:
                        print(
                            f"[DEFER-LANGUAGE] {key}/{lang} QA still "
                            f"unresolved={len(failures)}; continuing",
                            flush=True,
                        )
                    else:
                        print(
                            f"[QA-LANGUAGE-PASS] {key}/{lang}",
                            flush=True,
                        )
                except Exception as exc:
                    record_language_result(
                        data, lang, ids, error=exc, stage="qa"
                    )
                    print(
                        f"[DEFER-LANGUAGE] {key}/{lang} QA error "
                        f"{type(exc).__name__}; continuing",
                        flush=True,
                    )

                qa_batches[key] = data
                seq += 1
                save_persistent_checkpoint(
                    args.task_id,
                    checkpoint_payload(
                        args.task_id, len(source_segments), translations,
                        qa_batches, seq, source_sha256, requested,
                    ),
                    drive=drive,
                    translation_folder_id=folders["translation"],
                    workdir=workdir,
                    require_persistent=True,
                )

            # Persist translation-missing / deferred language markers when
            # the batch had no successful QA calls.
            qa_batches[key] = data
            seq += 1
            save_persistent_checkpoint(
                args.task_id,
                checkpoint_payload(
                    args.task_id, len(source_segments), translations,
                    qa_batches, seq, source_sha256, requested,
                ),
                drive=drive,
                translation_folder_id=folders["translation"],
                workdir=workdir,
                require_persistent=True,
            )

            if batch_no < len(batches) and args.wait_seconds:
                time.sleep(args.wait_seconds)

        incomplete = {
            int(src["id"]): row_missing_languages(
                translations.get(int(src["id"])),
                requested,
            )
            for src in source_segments
        }
        incomplete = {
            sid: langs for sid, langs in incomplete.items() if langs
        }
        if incomplete:
            raise RuntimeError(
                "仍有未翻譯語言：" +
                json.dumps(incomplete, ensure_ascii=False)
            )

        unresolved = []
        for data in qa_batches.values():
            unresolved.extend(
                item for item in (data.get("unresolved") or [])
                if str(item.get("lang") or "") in requested
            )
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
            output_engine = "gemma4+nvidia-riva-fallback"
        elif nvidia_repair_used:
            output_engine = "gemma4+nvidia-second-opinion"
        else:
            output_engine = "gemma4"
        if client.fallback_used:
            output_engine += "+" + client.fallback_model + "-failover"
        print(
            "[MODEL-SUMMARY] models=" + ",".join(sorted(client.models_used))
            + "; fallback_used=" + str(client.fallback_used),
            flush=True,
        )

        # Keep one explicit boolean for the QA report / task summary.
        # A refactor split NVIDIA usage into fallback vs second-opinion flags,
        # but the legacy nvidia_used references below were accidentally left
        # behind, causing a NameError after translation + QA had already run.
        nvidia_used = bool(nvidia_repair_used or nvidia_fallback_used)

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
                source_sha256=source_sha256,
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
                    "fallback_model_used": client.fallback_used,
                    "models_used": sorted(client.models_used),
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
                "Gemma 4 翻譯+QA完成；語言=" + ",".join(requested)
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
            requested,
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
        # Reporting failure must never obscure the original provider error
        # when the Google Sheets access token expires mid-run.
        try:
            mark_error(
                args.task_id,
                "multi",
                sheets=sheets,
                run_id=run_id,
                exc=exc,
            )
        except Exception as status_exc:
            print(
                f"[WARN] Multi failure status could not be reported: "
                f"{type(status_exc).__name__}: {status_exc}",
                file=sys.stderr,
            )
        print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc()
        if is_hard_quota_error(exc):
            # Stop same-workflow immediate retries of a daily exhausted model.
            # The authorized user can resume from Drive after quota reset.
            print(
                "[QUOTA-PAUSED] daily model quota exhausted; "
                "checkpoint preserved; no immediate retry",
                file=sys.stderr,
            )
            return 75
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
