import json
import os
import re
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

_MODEL = None
_TOKENIZER = None
_MODEL_KEY = None

COMMON_ASR_FIXES = {
    "前嫌": "前賢",
    "前線": "前賢",
    "淺顯": "前賢",
    "請醒": "前賢",
    "白羊棋": "白陽期",
    "白楊棋": "白陽期",
    "白羊期": "白陽期",
    "白楊期": "白陽期",
    "青陽棋": "青陽期",
    "紅陽棋": "紅陽期",
    "修半": "修辦",
    "休辦": "修辦",
    "學修講半": "學修講辦",
    "開荒半道": "開荒辦道",
    "一試修一試成": "一世修一世成",
    "先得後休": "先得後修",
    "學護五車": "學富五車",
    "竹繭": "竹簡",
    "商國": "三國",
    "杜化": "渡化",
    "天師德": "天恩師德",
    "尚方慈悲": "上方慈悲",
    "先佛慈悲": "仙佛慈悲",
}

SYSTEM_PROMPT = """你是「打開心靈的鎖匙」課程的繁體中文逐字稿校稿員。
這是台灣一貫道／道場課程的 ASR 初稿，內容可能混有華語、台語及宗教專有名詞。

工作原則：
1. 只校正辨識錯字、同音誤字、標點、斷句與明顯語病，不新增講者沒有說過的觀點。
2. 保留講者原本口語語氣與意思，不把逐字稿改寫成文章。
3. 優先使用提供的「道場專有名詞」。
4. 對上下文高度確定的常識性誤辨可以修正，例如「學護五車→學富五車」「竹繭→竹簡」「商國→三國」。
5. 台語、俗諺、人名、佛規禮節或道場用語若無法高度確定，寧可保留原文，並放進 uncertain，不可自行編造。
6. 每個 segment 必須保留相同 id，不可合併、刪除或新增 segment。
7. 輸出必須是 JSON，不要加 Markdown、說明或思考過程。

輸出格式：
{"segments":[{"id":0,"text":"校正後文字","uncertain":["不確定詞句"]}]}
"""


def _looks_like_model(path: Path):
    return (
        path.is_dir()
        and (path / "config.json").exists()
        and (path / "tokenizer_config.json").exists()
    )


def _find_model_under(root: Path, model_dir_name: str):
    if not root.exists():
        return None
    try:
        for config in root.rglob("config.json"):
            candidate = config.parent
            if candidate.name == model_dir_name and _looks_like_model(candidate):
                return candidate
    except Exception:
        return None
    return None


def resolve_polish_model(model_name: str):
    explicit = os.getenv("POLISH_MODEL_PATH", "").strip()
    if explicit:
        path = Path(explicit)
        if _looks_like_model(path):
            print(f"[POLISH] 使用 POLISH_MODEL_PATH：{path}")
            return str(path)
        raise RuntimeError(f"POLISH_MODEL_PATH 不是有效模型：{path}")

    model_dir_name = "qwen3-4b"
    input_model = _find_model_under(Path("/kaggle/input"), model_dir_name)
    if input_model:
        print(f"[POLISH] 使用 Kaggle 永久 Input 模型：{input_model}")
        return str(input_model)

    working_model = Path("/kaggle/working/persistent-model") / model_dir_name
    if _looks_like_model(working_model):
        print(f"[POLISH] 使用本 Session 模型：{working_model}")
        return str(working_model)

    print("[POLISH] 找不到永久模型，第一次將由 Hugging Face 下載。")
    return model_name


def _load_model(model_name: str):
    global _MODEL, _TOKENIZER, _MODEL_KEY

    source = resolve_polish_model(model_name)
    key = str(source)
    if _MODEL is not None and _MODEL_KEY == key:
        return _TOKENIZER, _MODEL

    print(f"[POLISH] 載入 AI 校稿模型：{source}")
    _TOKENIZER = AutoTokenizer.from_pretrained(source, trust_remote_code=True)
    _MODEL = AutoModelForCausalLM.from_pretrained(
        source,
        torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
        device_map="auto",
        low_cpu_mem_usage=True,
        trust_remote_code=True,
    )
    _MODEL.eval()
    _MODEL_KEY = key
    return _TOKENIZER, _MODEL


def _deterministic_fix(text: str):
    out = text
    for wrong, correct in COMMON_ASR_FIXES.items():
        out = out.replace(wrong, correct)
    return out


def _extract_json_object(text: str):
    text = text.strip()
    fence = chr(96) * 3
    if text.startswith(fence):
        text = re.sub(r"^.{3}(?:json)?\s*", "", text)
        text = re.sub(r"\s*.{3}$", "", text)

    first = text.find("{")
    last = text.rfind("}")
    if first < 0 or last <= first:
        raise ValueError("AI 回覆中找不到 JSON object")
    return json.loads(text[first:last + 1])


def _generate_json(tokenizer, model, messages, max_new_tokens=2200):
    try:
        prompt = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
    except TypeError:
        prompt = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )

    inputs = tokenizer(prompt, return_tensors="pt")
    device = next(model.parameters()).device
    inputs = {k: v.to(device) for k, v in inputs.items()}

    with torch.inference_mode():
        output = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            repetition_penalty=1.03,
            eos_token_id=tokenizer.eos_token_id,
            pad_token_id=tokenizer.eos_token_id,
        )

    generated = output[0][inputs["input_ids"].shape[1]:]
    return tokenizer.decode(generated, skip_special_tokens=True).strip()


def _format_srt_time(seconds: float):
    ms = int(round(float(seconds) * 1000))
    hours, rem = divmod(ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _plain_time(seconds: float):
    total = max(0, int(float(seconds)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _readable_paragraphs(texts):
    joined = "".join(texts)
    sentences = [
        x.strip()
        for x in re.split(r"(?<=[。！？!?])", joined)
        if x.strip()
    ]

    paragraphs = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) > 180:
            paragraphs.append(current.strip())
            current = sentence
        else:
            current += sentence
    if current.strip():
        paragraphs.append(current.strip())

    return "\n\n".join(paragraphs) + "\n"


def polish_segments(
    segments_json_path,
    output_dir: Path,
    model_name: str,
    glossary_terms=None,
    chunk_size=5,
):
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = json.loads(Path(segments_json_path).read_text(encoding="utf-8"))
    raw_segments = payload.get("segments") or []
    if not raw_segments:
        raise RuntimeError("segments.json 沒有可校稿的 segments")

    glossary_terms = [
        str(x).strip() for x in (glossary_terms or []) if str(x).strip()
    ]
    glossary_terms = glossary_terms[:120]
    glossary_text = "、".join(glossary_terms)

    tokenizer, model = _load_model(model_name)

    polished = []
    review_changes = []
    all_uncertain = []

    for chunk_start in range(0, len(raw_segments), chunk_size):
        target = raw_segments[chunk_start:chunk_start + chunk_size]

        prepared = []
        for offset, seg in enumerate(target):
            prepared.append({
                "id": chunk_start + offset,
                "text": _deterministic_fix(str(seg.get("text") or "").strip()),
            })

        before = ""
        after = ""
        if chunk_start > 0:
            before = _deterministic_fix(
                str(raw_segments[chunk_start - 1].get("text") or "").strip()
            )
        if chunk_start + chunk_size < len(raw_segments):
            after = _deterministic_fix(
                str(raw_segments[chunk_start + chunk_size].get("text") or "").strip()
            )

        user_prompt = f"""道場專有名詞：
{glossary_text}

前一段上下文（只供理解，不要輸出）：
{before}

本次要校稿的 segments：
{json.dumps(prepared, ensure_ascii=False)}

後一段上下文（只供理解，不要輸出）：
{after}

請依規則校稿並回傳 JSON。"""

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        print(
            f"[POLISH] 校稿 segments "
            f"{chunk_start + 1}-{min(chunk_start + chunk_size, len(raw_segments))}"
            f"/{len(raw_segments)}"
        )

        response = _generate_json(tokenizer, model, messages)
        parsed = _extract_json_object(response)
        returned = parsed.get("segments") or []
        by_id = {
            int(item["id"]): item
            for item in returned
            if isinstance(item, dict) and "id" in item
        }

        for offset, raw in enumerate(target):
            idx = chunk_start + offset
            pre_fixed = prepared[offset]["text"]
            item = by_id.get(idx, {})
            corrected = str(item.get("text") or pre_fixed).strip()
            uncertain = item.get("uncertain") or []
            if isinstance(uncertain, str):
                uncertain = [uncertain]
            uncertain = [str(x).strip() for x in uncertain if str(x).strip()]

            result_seg = {
                "start": float(raw.get("start", 0)),
                "end": float(raw.get("end", 0)),
                "text": corrected,
            }
            polished.append(result_seg)

            raw_text = str(raw.get("text") or "").strip()
            if corrected != raw_text:
                review_changes.append({
                    "id": idx,
                    "start": result_seg["start"],
                    "end": result_seg["end"],
                    "raw": raw_text,
                    "polished": corrected,
                })

            for phrase in uncertain:
                all_uncertain.append({
                    "id": idx,
                    "start": result_seg["start"],
                    "phrase": phrase,
                })

    txt_path = output_dir / "zh-TW.polished.txt"
    srt_path = output_dir / "zh-TW.polished.srt"
    readable_path = output_dir / "zh-TW.readable.txt"
    report_path = output_dir / "polish_report.json"

    txt_lines = [
        f"[{_plain_time(x['start'])} - {_plain_time(x['end'])}] {x['text']}"
        for x in polished
    ]
    txt_path.write_text("\n".join(txt_lines) + "\n", encoding="utf-8")

    srt_lines = []
    for i, item in enumerate(polished, start=1):
        srt_lines.extend([
            str(i),
            f"{_format_srt_time(item['start'])} --> {_format_srt_time(item['end'])}",
            item["text"],
            "",
        ])
    srt_path.write_text("\n".join(srt_lines), encoding="utf-8")

    readable_path.write_text(
        _readable_paragraphs([x["text"] for x in polished]),
        encoding="utf-8",
    )

    report = {
        "model": model_name,
        "segment_count": len(polished),
        "changed_segment_count": len(review_changes),
        "uncertain_count": len(all_uncertain),
        "changes": review_changes,
        "uncertain": all_uncertain,
        "segments": polished,
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "txt": txt_path,
        "srt": srt_path,
        "readable": readable_path,
        "report": report_path,
        "segment_count": len(polished),
        "changed_count": len(review_changes),
        "uncertain_count": len(all_uncertain),
    }
