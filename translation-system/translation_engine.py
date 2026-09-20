import json
import re
from pathlib import Path

from polish import _extract_json_object, _generate_json, _load_model


LANGUAGE_NAMES = {
    "en": "English",
    "th": "Thai",
    "es": "Spanish",
    "id": "Indonesian",
    "vi": "Vietnamese",
}

GLOSSARY_TARGET_COLUMN = {
    "en": 3,
    "th": 4,
    "es": 5,
    "id": 6,
    "vi": 7,
}


def _plain_time(seconds: float):
    total = max(0, int(float(seconds)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _srt_time(seconds: float):
    ms = int(round(float(seconds) * 1000))
    hours, rem = divmod(ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def normalize_source_segments(payload):
    segments = payload.get("segments") or []
    normalized = []
    for idx, seg in enumerate(segments):
        if not isinstance(seg, dict):
            continue
        text = str(seg.get("text") or "").strip()
        if not text:
            continue
        normalized.append({
            "id": int(seg.get("id", idx)),
            "start": float(seg.get("start", 0)),
            "end": float(seg.get("end", 0)),
            "text": text,
        })
    if not normalized:
        raise RuntimeError("來源逐字稿沒有可處理的 segments")
    return normalized


def parse_glossary_rows(rows):
    result = []
    for raw in rows or []:
        row = list(raw) + [""] * max(0, 10 - len(raw))
        canonical = str(row[0] or "").strip()
        if not canonical:
            continue
        result.append({
            "canonical_zh": canonical,
            "category": str(row[1] or "").strip(),
            "description": str(row[2] or "").strip(),
            "en": str(row[3] or "").strip(),
            "th": str(row[4] or "").strip(),
            "es": str(row[5] or "").strip(),
            "id": str(row[6] or "").strip(),
            "vi": str(row[7] or "").strip(),
            "locked": str(row[8] or "").strip().lower() in {"true", "1", "yes", "y", "是"},
            "note": str(row[9] or "").strip(),
        })
    return result


def _glossary_for_zh(glossary):
    lines = []
    for item in glossary[:180]:
        extra = f"｜{item['description']}" if item.get("description") else ""
        lines.append(f"- {item['canonical_zh']}{extra}")
    return "\n".join(lines)


def _glossary_for_translation(glossary, target_code):
    lines = []
    for item in glossary:
        target = str(item.get(target_code) or "").strip()
        if not target:
            continue
        if target_code == "en":
            source = item["canonical_zh"]
        else:
            source = str(item.get("en") or "").strip()
            if not source:
                continue
        lock = "LOCKED" if item.get("locked") else "preferred"
        lines.append(f"- {source} => {target} [{lock}]")
    return "\n".join(lines[:180])


def _window_text(segments, start, end):
    out = []
    for item in segments[start:end]:
        out.append(str(item.get("text") or "").strip())
    return "\n".join(x for x in out if x)


def _normalize_returned(returned):
    by_id = {}
    for item in returned or []:
        if not isinstance(item, dict) or "id" not in item:
            continue
        try:
            idx = int(item["id"])
        except Exception:
            continue
        by_id[idx] = item
    return by_id


def modernize_to_vernacular(
    source_segments,
    output_dir: Path,
    model_name: str,
    glossary_rows=None,
    chunk_size=6,
):
    """
    將整篇中文逐字稿轉為清楚的繁體中文白話文。
    已是白話文的句子盡量維持原意與資訊；文言、偈語、古語則轉成易懂白話。
    時間軸與 segment id 不變。
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    glossary = parse_glossary_rows(glossary_rows)
    tokenizer, model = _load_model(model_name)

    system_prompt = """你是「打開心靈的鎖匙」課程的繁體中文白話轉譯員。
輸入是已校稿的中文逐字稿，內容可能同時包含現代口語、道場用語、文言文、古語、偈語、經典句、台語轉寫與宗教術語。

任務：把整篇內容轉成「現代、清楚、自然的繁體中文白話文」，作為後續英文翻譯的唯一中文語義底稿。

規則：
1. 絕對不可摘要、刪減、增添教義或自行補充不存在的資訊。
2. 已經是清楚白話文的內容，盡量保持原意與語氣，只做必要的語序整理。
3. 文言文、古語、偈語與高度凝縮句，要忠實轉成一般人可理解的白話意思。
4. 道場固定術語、仙佛名稱、人物名稱不可自行改義；優先參考專有名詞表。
5. 不確定的台語、經文、仙佛稱謂或特殊詞，不要硬猜；保留原詞並標記 review_required=true。
6. 每個 segment 必須保留原 id；不可合併、刪除、新增或重新排序。
7. 每段輸出 text 是白話版本；source_text 不需輸出。
8. 只輸出 JSON，不要 Markdown，不要解釋推理。

JSON 格式：
{"segments":[{"id":0,"text":"白話文","had_classical":false,"review_required":false,"notes":""}]}
"""

    glossary_text = _glossary_for_zh(glossary)
    result = []
    reviews = []

    for start in range(0, len(source_segments), chunk_size):
        target = source_segments[start:start + chunk_size]
        payload = [{"id": x["id"], "text": x["text"]} for x in target]
        before = _window_text(source_segments, max(0, start - 2), start)
        after = _window_text(
            source_segments,
            start + chunk_size,
            min(len(source_segments), start + chunk_size + 2),
        )
        user_prompt = f"""專有名詞參考：
{glossary_text}

前文（只供理解，不要輸出）：
{before}

本次內容：
{json.dumps(payload, ensure_ascii=False)}

後文（只供理解，不要輸出）：
{after}

請逐 segment 轉成忠實白話文。"""

        print(
            f"[VERNACULAR] segments {start + 1}-"
            f"{min(start + chunk_size, len(source_segments))}/{len(source_segments)}"
        )
        response = _generate_json(
            tokenizer,
            model,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_new_tokens=2600,
        )
        parsed = _extract_json_object(response)
        by_id = _normalize_returned(parsed.get("segments"))

        for raw in target:
            item = by_id.get(raw["id"], {})
            text = str(item.get("text") or raw["text"]).strip()
            had_classical = bool(item.get("had_classical", False))
            review_required = bool(item.get("review_required", False))
            notes = str(item.get("notes") or "").strip()
            out = {
                "id": raw["id"],
                "start": raw["start"],
                "end": raw["end"],
                "source_text": raw["text"],
                "text": text,
                "had_classical": had_classical,
                "review_required": review_required,
                "notes": notes,
            }
            result.append(out)
            if review_required:
                reviews.append({
                    "id": raw["id"],
                    "start": raw["start"],
                    "source_text": raw["text"],
                    "vernacular_text": text,
                    "notes": notes,
                })

    return write_language_outputs(
        code="zh-TW.vernacular",
        language="Traditional Chinese Vernacular",
        segments=result,
        output_dir=output_dir,
        extra={
            "source_policy": "Chinese transcript -> full vernacular Chinese -> English",
            "review_required_count": len(reviews),
            "review_items": reviews,
        },
    )


def translate_segments(
    source_segments,
    source_language: str,
    target_code: str,
    output_dir: Path,
    model_name: str,
    glossary_rows=None,
    chunk_size=6,
):
    if target_code not in LANGUAGE_NAMES:
        raise ValueError(f"不支援的翻譯語言：{target_code}")

    output_dir.mkdir(parents=True, exist_ok=True)
    target_language = LANGUAGE_NAMES[target_code]
    glossary = parse_glossary_rows(glossary_rows)
    glossary_text = _glossary_for_translation(glossary, target_code)
    tokenizer, model = _load_model(model_name)

    if target_code == "en":
        source_rule = (
            "Source is Traditional Chinese vernacular. Translate faithfully into natural "
            "spoken English."
        )
    else:
        source_rule = (
            "Source is the approved English pivot translation. Translate from English only; "
            "do not reinterpret from Chinese."
        )

    system_prompt = f"""You are a professional religious-course translator.
Target language: {target_language}.
{source_rule}

Rules:
1. Preserve the complete meaning. Do not summarize, omit, preach, embellish, or add explanations.
2. Keep the tone natural for spoken teaching, but remain faithful to the source.
3. Preserve names, scripture references, numbers, examples, and logical relationships.
4. Obey glossary mappings. Items marked LOCKED must use the exact target term.
5. For religious or I-Kuan Tao terminology without a locked translation, choose a clear translation and set review_required=true when there is real ambiguity.
6. Keep every segment id exactly. Do not merge, add, delete, or reorder segments.
7. Output only JSON.

JSON format:
{{"segments":[{{"id":0,"text":"translation","review_required":false,"notes":""}}]}}
"""

    result = []
    reviews = []

    for start in range(0, len(source_segments), chunk_size):
        target = source_segments[start:start + chunk_size]
        payload = [{"id": x["id"], "text": x["text"]} for x in target]
        before = _window_text(source_segments, max(0, start - 2), start)
        after = _window_text(
            source_segments,
            start + chunk_size,
            min(len(source_segments), start + chunk_size + 2),
        )
        user_prompt = f"""Glossary:
{glossary_text or "(No locked glossary entries yet.)"}

Previous context (context only):
{before}

Segments to translate:
{json.dumps(payload, ensure_ascii=False)}

Following context (context only):
{after}

Translate all requested segments into {target_language}."""

        print(
            f"[TRANSLATE:{target_code}] segments {start + 1}-"
            f"{min(start + chunk_size, len(source_segments))}/{len(source_segments)}"
        )
        response = _generate_json(
            tokenizer,
            model,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_new_tokens=3000,
        )
        parsed = _extract_json_object(response)
        by_id = _normalize_returned(parsed.get("segments"))

        for raw in target:
            item = by_id.get(raw["id"], {})
            text = str(item.get("text") or "").strip()
            missing = not text
            if missing:
                text = raw["text"]
            review_required = bool(item.get("review_required", False)) or missing
            notes = str(item.get("notes") or "").strip()
            if missing and not notes:
                notes = "model_missing_output_fallback_to_source"

            out = {
                "id": raw["id"],
                "start": raw["start"],
                "end": raw["end"],
                "source_text": raw["text"],
                "text": text,
                "review_required": review_required,
                "notes": notes,
            }
            result.append(out)
            if review_required:
                reviews.append({
                    "id": raw["id"],
                    "start": raw["start"],
                    "source_text": raw["text"],
                    "translated_text": text,
                    "notes": notes,
                })

    return write_language_outputs(
        code=target_code,
        language=target_language,
        segments=result,
        output_dir=output_dir,
        extra={
            "source_language": source_language,
            "translation_policy": (
                "zh-TW vernacular -> English"
                if target_code == "en"
                else "English pivot -> target language"
            ),
            "review_required_count": len(reviews),
            "review_items": reviews,
        },
    )


def write_language_outputs(code, language, segments, output_dir: Path, extra=None):
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{code}.json"
    txt_path = output_dir / f"{code}.txt"
    srt_path = output_dir / f"{code}.srt"

    payload = {
        "language": language,
        "segments": segments,
    }
    payload.update(extra or {})
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    txt_lines = [
        f"[{_plain_time(x['start'])} - {_plain_time(x['end'])}] {x['text']}"
        for x in segments
    ]
    txt_path.write_text("\n".join(txt_lines) + "\n", encoding="utf-8")

    srt_lines = []
    for i, x in enumerate(segments, start=1):
        srt_lines.extend([
            str(i),
            f"{_srt_time(x['start'])} --> {_srt_time(x['end'])}",
            x["text"],
            "",
        ])
    srt_path.write_text("\n".join(srt_lines), encoding="utf-8")

    return {
        "json": json_path,
        "txt": txt_path,
        "srt": srt_path,
        "segments": segments,
        "review_required_count": int((extra or {}).get("review_required_count", 0)),
    }


def load_segments_json(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return normalize_source_segments(payload)
