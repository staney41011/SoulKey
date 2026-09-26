import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
DEFAULT_TEXT_MODEL = os.getenv("GEMINI_TEXT_MODEL", "gemini-3.8-flash")
DEFAULT_TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-3.8-flash-tts")

LANGUAGE_NAMES = {
    "en": "English",
    "th": "Thai",
    "es": "Spanish",
    "id": "Indonesian",
    "vi": "Vietnamese",
    "sd": "Sindhi",
    "ta": "Tamil",
}

TARGET_SCRIPT_PATTERNS = {
    "th": re.compile(r"[\u0E00-\u0E7F]"),
    "sd": re.compile(r"[\u0600-\u06FF]"),
    "ta": re.compile(r"[\u0B80-\u0BFF]"),
}

TRANSLATION_SCHEMA = {
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

QA_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "pass": {"type": "boolean"},
                    "meaning_preserved": {"type": "boolean"},
                    "missing_content": {"type": "boolean"},
                    "added_content": {"type": "boolean"},
                    "wrong_language": {"type": "boolean"},
                    "glossary_violation": {"type": "boolean"},
                    "tts_ready": {"type": "boolean"},
                    "issues": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "repair_instruction": {"type": "string"},
                },
                "required": [
                    "id",
                    "pass",
                    "meaning_preserved",
                    "missing_content",
                    "added_content",
                    "wrong_language",
                    "glossary_violation",
                    "tts_ready",
                    "issues",
                    "repair_instruction",
                ],
            },
        }
    },
    "required": ["items"],
}

POLISH_SCHEMA = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "text": {"type": "string"},
                    "changed": {"type": "boolean"},
                    "notes": {"type": "string"},
                    "term_candidates": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "id",
                    "text",
                    "changed",
                    "notes",
                    "term_candidates",
                ],
            },
        }
    },
    "required": ["segments"],
}


class GeminiAPIError(RuntimeError):
    pass


@dataclass
class GeminiUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    thought_tokens: int = 0
    total_tokens: int = 0


def _default_transport(url, headers, payload, timeout):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


class GeminiClient:
    def __init__(
        self,
        api_key=None,
        text_model=DEFAULT_TEXT_MODEL,
        tts_model=DEFAULT_TTS_MODEL,
        transport: Callable | None = None,
        sleeper: Callable | None = None,
        max_attempts=4,
        timeout=120,
    ):
        self.api_key = str(api_key or os.getenv("GEMINI_API_KEY", "")).strip()
        self.text_model = text_model
        self.tts_model = tts_model
        self.transport = transport or _default_transport
        self.sleeper = sleeper or time.sleep
        self.max_attempts = max(1, int(max_attempts))
        self.timeout = int(timeout)

    def require_key(self):
        if not self.api_key:
            raise GeminiAPIError(
                "找不到 GEMINI_API_KEY。Shadow 版不會自動讀取或提交任何 API key。"
            )

    def _request(self, payload):
        self.require_key()
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }
        last = None

        for attempt in range(1, self.max_attempts + 1):
            status, raw = self.transport(
                GEMINI_API_URL,
                headers,
                payload,
                self.timeout,
            )
            body_text = raw.decode("utf-8", errors="replace")
            if 200 <= int(status) < 300:
                try:
                    return json.loads(body_text)
                except json.JSONDecodeError as exc:
                    raise GeminiAPIError(
                        f"Gemini 回傳不是合法 JSON：{exc}"
                    ) from exc

            last = f"HTTP {status}: {body_text[:800]}"
            retryable = int(status) in {408, 409, 429, 500, 502, 503, 504}
            if not retryable or attempt >= self.max_attempts:
                break

            wait = min(2 ** (attempt - 1), 8)
            print(
                f"[GEMINI] {status}；{wait}s 後重試 "
                f"({attempt}/{self.max_attempts})",
                flush=True,
            )
            self.sleeper(wait)

        raise GeminiAPIError(last or "Gemini API request failed")

    @staticmethod
    def _last_content(response, wanted_type):
        found = None
        for step in response.get("steps") or []:
            if step.get("type") != "model_output":
                continue
            for content in step.get("content") or []:
                if content.get("type") == wanted_type:
                    found = content
        return found

    @staticmethod
    def usage(response):
        raw = response.get("usage") or {}
        return GeminiUsage(
            input_tokens=int(raw.get("total_input_tokens") or 0),
            output_tokens=int(raw.get("total_output_tokens") or 0),
            thought_tokens=int(raw.get("total_thought_tokens") or 0),
            total_tokens=int(raw.get("total_tokens") or 0),
        )

    def structured(
        self,
        prompt,
        schema,
        *,
        system_instruction="",
        model=None,
        thinking_level="low",
    ):
        payload = {
            "model": model or self.text_model,
            "input": str(prompt),
            "response_format": {
                "type": "text",
                "mime_type": "application/json",
                "schema": schema,
            },
            "generation_config": {
                "thinking_level": thinking_level,
            },
        }
        if system_instruction:
            payload["system_instruction"] = str(system_instruction)

        response = self._request(payload)
        content = self._last_content(response, "text")
        if not content or not str(content.get("text") or "").strip():
            raise GeminiAPIError("Gemini Structured Output 沒有文字輸出")

        try:
            parsed = json.loads(content["text"])
        except json.JSONDecodeError as exc:
            raise GeminiAPIError(
                f"Gemini Structured Output 無法解析：{exc}"
            ) from exc

        return parsed, self.usage(response)

    def tts(
        self,
        text,
        *,
        voice="Kore",
        style="calm, clear, natural teaching narration",
        model=None,
    ):
        payload = {
            "model": model or self.tts_model,
            "input": [{
                "type": "user_input",
                "content": [{
                    "type": "text",
                    "text": str(text),
                    "annotations": [{
                        "type": "speech_metadata",
                        "style": str(style),
                    }],
                }],
            }],
            "response_format": {
                "type": "audio",
                "mime_type": "audio/wav",
            },
            "generation_config": {
                "speech_config": [{"voice": str(voice)}],
            },
        }
        response = self._request(payload)
        content = self._last_content(response, "audio")
        if not content or not content.get("data"):
            raise GeminiAPIError("Gemini TTS 沒有 audio output")
        try:
            audio = base64.b64decode(content["data"])
        except Exception as exc:
            raise GeminiAPIError("Gemini TTS base64 解碼失敗") from exc
        if not audio.startswith(b"RIFF"):
            raise GeminiAPIError("Gemini TTS 回傳不是完整 WAV")
        return audio, str(content.get("mime_type") or "audio/wav"), self.usage(response)


def normalize_segments(payload):
    rows = payload.get("segments") if isinstance(payload, dict) else payload
    out = []
    for idx, item in enumerate(rows or []):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        out.append({
            "id": int(item.get("id", idx)),
            "start": float(item.get("start", 0) or 0),
            "end": float(item.get("end", 0) or 0),
            "text": text,
        })
    if not out:
        raise ValueError("沒有可處理的 segments")
    return out


def parse_glossary_rows(rows):
    result = []
    for raw in rows or []:
        row = list(raw) + [""] * max(0, 10 - len(raw))
        zh = str(row[0] or "").strip()
        if not zh:
            continue
        result.append({
            "zh": zh,
            "category": str(row[1] or "").strip(),
            "description": str(row[2] or "").strip(),
            "en": str(row[3] or "").strip(),
            "th": str(row[4] or "").strip(),
            "es": str(row[5] or "").strip(),
            "id": str(row[6] or "").strip(),
            "vi": str(row[7] or "").strip(),
            "locked": str(row[8] or "").strip().lower()
                in {"true", "1", "yes", "y", "是"},
            "note": str(row[9] or "").strip(),
        })
    return result


def relevant_glossary(glossary, source_text, target_code, limit=80):
    haystack = str(source_text or "").lower()
    scored = []
    for item in glossary:
        zh = str(item.get("zh") or "")
        en = str(item.get("en") or "")
        target = str(item.get(target_code) or "")
        score = 0
        if zh and zh.lower() in haystack:
            score += 4
        if en and en.lower() in haystack:
            score += 4
        if item.get("locked"):
            score += 1
        if score:
            scored.append((score, item, target))
    scored.sort(key=lambda x: -x[0])
    return [x[1] for x in scored[:limit]]


def glossary_prompt(items, target_code=None):
    lines = []
    for item in items:
        lock = "LOCKED" if item.get("locked") else "preferred"
        if target_code:
            target = str(item.get(target_code) or "").strip()
            source = str(item.get("en") or item.get("zh") or "").strip()
            if target:
                lines.append(f"- {source} => {target} [{lock}]")
            else:
                lines.append(
                    f"- {item.get('zh','')} / {item.get('en','')} [{lock}]"
                    " (target translation not stored yet; preserve concept consistently)"
                )
        else:
            lines.append(
                f"- {item.get('zh','')} [{lock}]"
                + (f"｜{item.get('description','')}" if item.get("description") else "")
                + (f"｜常見英文：{item.get('en','')}" if item.get("en") else "")
            )
    return "\n".join(lines) or "(no matching glossary entries)"


def validate_returned_ids(source_batch, returned, key):
    expected = [int(x["id"]) for x in source_batch]
    got = [int(x.get("id")) for x in returned or [] if "id" in x]
    if sorted(expected) != sorted(got):
        raise GeminiAPIError(
            f"{key} segment id 不完整：expected={expected}, got={got}"
        )


def local_language_issue(text, source, target_code):
    text = str(text or "").strip()
    source = str(source or "").strip()
    if not text:
        return "empty_translation"
    if text == source and len(source) >= 20:
        return "source_text_copied"

    pattern = TARGET_SCRIPT_PATTERNS.get(target_code)
    if pattern:
        target_chars = len(pattern.findall(text))
        latin = len(re.findall(r"[A-Za-z]", text))
        if target_chars < 4:
            return "missing_target_script"
        if latin > 20 and target_chars / max(1, target_chars + latin) < 0.65:
            return "target_script_ratio_too_low"
    return ""


def translate_and_qa(
    client: GeminiClient,
    source_segments,
    target_code,
    glossary_rows=None,
    chunk_size=12,
    repair_attempts=2,
):
    if target_code not in LANGUAGE_NAMES or target_code == "en":
        raise ValueError("Shadow 多語翻譯目前僅接受非英文目標語言")

    source_segments = normalize_segments(source_segments)
    glossary = parse_glossary_rows(glossary_rows)
    target_language = LANGUAGE_NAMES[target_code]
    translated = []
    qa_items = []
    total_usage = GeminiUsage()

    system = (
        "You are the production translation engine for a religious education course. "
        "Translate from approved English Final only. Preserve every idea, number, name, "
        "example and logical relationship. Never summarize or add doctrine. "
        "LOCKED glossary mappings are mandatory. Output only the requested schema."
    )

    for offset in range(0, len(source_segments), chunk_size):
        batch = source_segments[offset:offset + chunk_size]
        batch_text = "\n".join(x["text"] for x in batch)
        terms = relevant_glossary(glossary, batch_text, target_code)
        prompt = (
            f"Target language: {target_language} ({target_code})\n"
            f"Glossary:\n{glossary_prompt(terms, target_code)}\n\n"
            "Translate every segment. Keep each id exactly and do not merge/reorder.\n"
            + json.dumps(
                [{"id": x["id"], "text": x["text"]} for x in batch],
                ensure_ascii=False,
            )
        )
        parsed, usage = client.structured(
            prompt,
            TRANSLATION_SCHEMA,
            system_instruction=system,
            thinking_level="low",
        )
        returned = parsed.get("segments") or []
        validate_returned_ids(batch, returned, "translation")
        by_id = {int(x["id"]): x for x in returned}
        total_usage.input_tokens += usage.input_tokens
        total_usage.output_tokens += usage.output_tokens
        total_usage.thought_tokens += usage.thought_tokens
        total_usage.total_tokens += usage.total_tokens

        candidate_batch = []
        for src in batch:
            row = by_id[src["id"]]
            candidate_batch.append({
                "id": src["id"],
                "start": src["start"],
                "end": src["end"],
                "source_text": src["text"],
                "text": str(row["text"]).strip(),
                "notes": str(row.get("notes") or "").strip(),
            })

        qa_prompt = (
            f"Target language: {target_language}.\n"
            "Audit each translation against its English source. A pass requires: complete "
            "meaning, no invented content, correct target language, glossary compliance, "
            "and text suitable for direct TTS. Be strict but do not fail proper nouns merely "
            "because they remain in Latin script.\nGlossary:\n"
            f"{glossary_prompt(terms, target_code)}\n\nPAIRS:\n"
            + json.dumps([
                {
                    "id": x["id"],
                    "source": x["source_text"],
                    "translation": x["text"],
                }
                for x in candidate_batch
            ], ensure_ascii=False)
        )
        qa, qa_usage = client.structured(
            qa_prompt,
            QA_SCHEMA,
            system_instruction="You are an exacting bilingual translation QA engine.",
            thinking_level="low",
        )
        qa_returned = qa.get("items") or []
        validate_returned_ids(batch, qa_returned, "qa")
        qa_by_id = {int(x["id"]): x for x in qa_returned}
        total_usage.input_tokens += qa_usage.input_tokens
        total_usage.output_tokens += qa_usage.output_tokens
        total_usage.thought_tokens += qa_usage.thought_tokens
        total_usage.total_tokens += qa_usage.total_tokens

        for item in candidate_batch:
            verdict = qa_by_id[item["id"]]
            local_issue = local_language_issue(
                item["text"], item["source_text"], target_code
            )
            passed = bool(verdict.get("pass")) and not local_issue
            last_issue = local_issue or "; ".join(verdict.get("issues") or [])

            for repair_no in range(1, int(repair_attempts) + 1):
                if passed:
                    break
                repair_prompt = (
                    f"Repair this translation into {target_language}.\n"
                    f"QA problem: {last_issue or verdict.get('repair_instruction','')}\n"
                    f"Glossary:\n{glossary_prompt(terms, target_code)}\n"
                    "Return exactly this one segment id. Do not explain.\n"
                    + json.dumps({
                        "id": item["id"],
                        "source": item["source_text"],
                        "current_translation": item["text"],
                    }, ensure_ascii=False)
                )
                repaired, rep_usage = client.structured(
                    repair_prompt,
                    TRANSLATION_SCHEMA,
                    system_instruction=(
                        f"You are a strict {target_language} translation repair engine. "
                        "Write the main body in the target language."
                    ),
                    thinking_level="low",
                )
                rep_rows = repaired.get("segments") or []
                validate_returned_ids([item], rep_rows, "repair")
                item["text"] = str(rep_rows[0]["text"]).strip()
                total_usage.input_tokens += rep_usage.input_tokens
                total_usage.output_tokens += rep_usage.output_tokens
                total_usage.thought_tokens += rep_usage.thought_tokens
                total_usage.total_tokens += rep_usage.total_tokens

                local_issue = local_language_issue(
                    item["text"], item["source_text"], target_code
                )
                single_qa_prompt = (
                    f"Target language: {target_language}. Audit this pair.\n"
                    + json.dumps({
                        "id": item["id"],
                        "source": item["source_text"],
                        "translation": item["text"],
                    }, ensure_ascii=False)
                )
                check, check_usage = client.structured(
                    single_qa_prompt,
                    QA_SCHEMA,
                    system_instruction="Return strict translation QA only.",
                    thinking_level="low",
                )
                check_rows = check.get("items") or []
                validate_returned_ids([item], check_rows, "repair-qa")
                verdict = check_rows[0]
                total_usage.input_tokens += check_usage.input_tokens
                total_usage.output_tokens += check_usage.output_tokens
                total_usage.thought_tokens += check_usage.thought_tokens
                total_usage.total_tokens += check_usage.total_tokens
                passed = bool(verdict.get("pass")) and not local_issue
                last_issue = local_issue or "; ".join(verdict.get("issues") or [])

            item["qa_pass"] = passed
            item["qa_issues"] = [] if passed else (
                [last_issue] if last_issue else list(verdict.get("issues") or [])
            )
            item["repair_attempts"] = 0 if bool(qa_by_id[item["id"]].get("pass")) and not local_language_issue(
                candidate_batch[[x["id"] for x in candidate_batch].index(item["id"])]["text"],
                item["source_text"],
                target_code,
            ) else int(repair_attempts if not passed else 1)
            translated.append(item)
            qa_items.append({
                "id": item["id"],
                "pass": passed,
                "issues": item["qa_issues"],
            })

    return {
        "engine": "gemini",
        "model": client.text_model,
        "target_code": target_code,
        "target_language": target_language,
        "segments": translated,
        "qa": qa_items,
        "qa_pass_count": sum(1 for x in qa_items if x["pass"]),
        "qa_fail_count": sum(1 for x in qa_items if not x["pass"]),
        "usage": total_usage.__dict__,
    }


def semantic_polish_zh(
    client: GeminiClient,
    source_segments,
    glossary_rows=None,
    chunk_size=12,
):
    source_segments = normalize_segments(source_segments)
    glossary = parse_glossary_rows(glossary_rows)
    out = []
    total_usage = GeminiUsage()

    system = (
        "你是「打開心靈的鎖匙」繁體中文第二層語意校稿器。"
        "只修正明顯 ASR 同音錯字、專有名詞、斷句與會改變原意的錯誤。"
        "不可文學改寫、不可摘要、不可增加教義。LOCKED 詞不可改寫。"
        "若疑似出現資料庫沒有的新專有詞，只放入 term_candidates，不可自行鎖定。"
    )

    for offset in range(0, len(source_segments), chunk_size):
        batch = source_segments[offset:offset + chunk_size]
        batch_text = "\n".join(x["text"] for x in batch)
        terms = relevant_glossary(glossary, batch_text, None)
        prompt = (
            "相關專有名詞庫：\n"
            f"{glossary_prompt(terms)}\n\n"
            "逐段校稿並保留 id，不合併、不刪除、不重新排序。\n"
            + json.dumps(
                [{"id": x["id"], "text": x["text"]} for x in batch],
                ensure_ascii=False,
            )
        )
        parsed, usage = client.structured(
            prompt,
            POLISH_SCHEMA,
            system_instruction=system,
            thinking_level="medium",
        )
        returned = parsed.get("segments") or []
        validate_returned_ids(batch, returned, "zh-semantic-polish")
        by_id = {int(x["id"]): x for x in returned}
        total_usage.input_tokens += usage.input_tokens
        total_usage.output_tokens += usage.output_tokens
        total_usage.thought_tokens += usage.thought_tokens
        total_usage.total_tokens += usage.total_tokens

        for src in batch:
            row = by_id[src["id"]]
            out.append({
                "id": src["id"],
                "start": src["start"],
                "end": src["end"],
                "source_text": src["text"],
                "text": str(row["text"]).strip(),
                "changed": bool(row.get("changed")),
                "notes": str(row.get("notes") or "").strip(),
                "term_candidates": [
                    str(x).strip()
                    for x in (row.get("term_candidates") or [])
                    if str(x).strip()
                ],
            })

    return {
        "engine": "gemini",
        "model": client.text_model,
        "segments": out,
        "changed_count": sum(1 for x in out if x["changed"]),
        "term_candidates": sorted({
            term for x in out for term in x["term_candidates"]
        }),
        "usage": total_usage.__dict__,
    }


def save_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path
