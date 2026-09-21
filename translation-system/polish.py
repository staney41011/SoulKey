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
    "歌全選": "各位前賢",
    "歌藝全學": "各位前賢",
    "隔一圈以前": "各位前賢",
    "擺煉成鋼": "百鍊成鋼",
    "萬事具備，只見東": "萬事俱備，只欠東風",
    "萬事具備，只見東風": "萬事俱備，只欠東風",
    "關法律子": "關法律主",
    "修道半道": "修道辦道",
    "經現傳承": "金線傳承",
    "死氣層層": "死氣沉沉",
    "胡園補缺": "扶圓補缺",
    "少一點賢氣": "少一點嫌棄",
}

SYSTEM_PROMPT = """你是「打開心靈的鎖匙」課程的繁體中文逐字稿校稿員。
這是台灣一貫道／道場課程的 ASR 初稿，內容可能混有華語、台語及宗教專有名詞。

工作原則：
1. 只校正辨識錯字、同音誤字、標點、斷句與明顯語病，不新增講者沒有說過的觀點。
2. 保留講者原本口語語氣與意思，不把逐字稿改寫成文章。
3. 優先使用提供的「道場專有名詞」。
4. 對上下文高度確定的常識性誤辨必須主動修正，不要因為「保守」而留下明顯錯字。例如「學護五車→學富五車」「竹繭→竹簡」「商國→三國」「擺煉成鋼→百鍊成鋼」「萬事具備，只見東→萬事俱備，只欠東風」。
5. 道場稱謂與固定用語要優先判斷，例如「關法律主」「金線傳承」「扶圓補缺」「前賢」「白陽期」。
6. 將 ASR 造成的大量驚嘆號改成自然的繁體中文標點與清楚斷句；仍保留口語感，但要讓一般讀者能順暢閱讀。
7. 如果一個詞句在語意、成語、歷史典故或上下文上明顯不成立，必須再次檢查；能高度確定就修正，不能確定就保留並放進 uncertain。uncertain 要偏向多抓，不要漏掉可疑詞。
8. 台語俗諺、人名、佛規禮節或特殊道場用語若無法高度確定，不可自行編造。
9. 每個 segment 必須保留相同 id，不可合併、刪除或新增 segment。
10. 輸出必須是 JSON，不要加 Markdown、說明或思考過程。

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
    require_gpu = os.getenv("SOULKEY_REQUIRE_GPU", "").strip() == "1"
    cuda_ok = bool(torch.cuda.is_available())

    if require_gpu and not cuda_ok:
        raise RuntimeError(
            "GPU_REQUIRED_BUT_UNAVAILABLE: "
            "PyTorch 看不到 CUDA GPU，拒絕以 CPU 執行 Qwen 校稿。"
        )

    device_key = "cuda:0" if cuda_ok else "cpu"
    key = (str(source), device_key)
    if _MODEL is not None and _MODEL_KEY == key:
        return _TOKENIZER, _MODEL

    if cuda_ok:
        print(
            f"[POLISH] GPU 模式：{torch.cuda.get_device_name(0)} / CUDA / float16",
            flush=True,
        )
        try:
            torch.set_float32_matmul_precision("high")
        except Exception:
            pass
    else:
        print("[POLISH] CPU 模式：float32", flush=True)

    print(f"[POLISH] 載入 AI 校稿模型：{source}")
    _TOKENIZER = AutoTokenizer.from_pretrained(source, trust_remote_code=True)
    _MODEL = AutoModelForCausalLM.from_pretrained(
        source,
        dtype=torch.float16 if cuda_ok else torch.float32,
        device_map={"": 0} if cuda_ok else "cpu",
        low_cpu_mem_usage=True,
        trust_remote_code=True,
    )
    _MODEL.eval()
    for name in ("temperature", "top_p", "top_k"):
        if hasattr(_MODEL.generation_config, name):
            setattr(_MODEL.generation_config, name, None)
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
    chunk_size=8,
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
            before_items = raw_segments[max(0, chunk_start - 2):chunk_start]
            before = "\n".join(
                _deterministic_fix(str(x.get("text") or "").strip())
                for x in before_items
            )
        if chunk_start + chunk_size < len(raw_segments):
            after_items = raw_segments[
                chunk_start + chunk_size:
                min(len(raw_segments), chunk_start + chunk_size + 2)
            ]
            after = "\n".join(
                _deterministic_fix(str(x.get("text") or "").strip())
                for x in after_items
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

    # 第二輪：用第一輪結果搭配原始 ASR 再做一次「校對者」審稿。
    # 目的不是改寫內容，而是抓出第一輪仍留下的成語、典故、道場稱謂與怪句。
    REVIEW_PROMPT = """你是第二輪逐字稿審稿員。
請比較 raw（原始 ASR）與 current（第一輪校稿），找出 current 仍殘留的明顯辨識錯誤。

規則：
1. 不改變講者原意，不自行增加內容。
2. 必須修正高度確定的成語、典故、歷史人物與道場固定稱謂。
3. 特別注意：百鍊成鋼、萬事俱備只欠東風、關法律主、金線傳承、扶圓補缺、前賢、白陽期等。
4. current 若仍有語意不通、像隨機同音字拼出的詞，必須檢查；能確定就修，不能確定就放 uncertain。
5. 標點改為自然繁體中文，不要滿篇驚嘆號。
6. 每個 id 必須保留，不得增刪 segment。
7. 只輸出 JSON：
{"segments":[{"id":0,"text":"最終校正版","uncertain":["仍待人工確認"]}]}
"""

    second_pass = []
    second_uncertain = []

    for chunk_start in range(0, len(polished), chunk_size):
        target = polished[chunk_start:chunk_start + chunk_size]
        review_items = []
        for offset, seg in enumerate(target):
            idx = chunk_start + offset
            review_items.append({
                "id": idx,
                "raw": str(raw_segments[idx].get("text") or "").strip(),
                "current": seg["text"],
            })

        before = "\n".join(
            x["text"] for x in polished[max(0, chunk_start - 2):chunk_start]
        )
        after = "\n".join(
            x["text"]
            for x in polished[
                chunk_start + chunk_size:
                min(len(polished), chunk_start + chunk_size + 2)
            ]
        )

        review_user = f"""道場專有名詞：
{glossary_text}

前文：
{before}

要審稿的內容：
{json.dumps(review_items, ensure_ascii=False)}

後文：
{after}

請做第二輪審稿並回傳 JSON。"""

        print(
            f"[POLISH-2] 複核 segments "
            f"{chunk_start + 1}-{min(chunk_start + chunk_size, len(polished))}"
            f"/{len(polished)}"
        )

        response = _generate_json(
            tokenizer,
            model,
            [
                {"role": "system", "content": REVIEW_PROMPT},
                {"role": "user", "content": review_user},
            ],
        )
        parsed = _extract_json_object(response)
        returned = parsed.get("segments") or []
        by_id = {
            int(item["id"]): item
            for item in returned
            if isinstance(item, dict) and "id" in item
        }

        for offset, seg in enumerate(target):
            idx = chunk_start + offset
            item = by_id.get(idx, {})
            text = str(item.get("text") or seg["text"]).strip()
            uncertain = item.get("uncertain") or []
            if isinstance(uncertain, str):
                uncertain = [uncertain]
            uncertain = [str(x).strip() for x in uncertain if str(x).strip()]

            second_pass.append({
                "start": seg["start"],
                "end": seg["end"],
                "text": text,
            })
            for phrase in uncertain:
                second_uncertain.append({
                    "id": idx,
                    "start": seg["start"],
                    "phrase": phrase,
                })

    polished = second_pass

    # 重新依「最終結果」產生修改報告，並合併兩輪 uncertain。
    review_changes = []
    for idx, final_seg in enumerate(polished):
        raw_text = str(raw_segments[idx].get("text") or "").strip()
        if final_seg["text"] != raw_text:
            review_changes.append({
                "id": idx,
                "start": final_seg["start"],
                "end": final_seg["end"],
                "raw": raw_text,
                "polished": final_seg["text"],
            })

    merged_uncertain = {}
    for item in all_uncertain + second_uncertain:
        key = (int(item["id"]), str(item["phrase"]).strip())
        if key[1]:
            merged_uncertain[key] = item
    all_uncertain = list(merged_uncertain.values())

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
