import json
import os
import re
from pathlib import Path

import ctranslate2
from faster_whisper import WhisperModel

_MODEL = None
_MODEL_KEY = None


def _looks_like_ct2_model(path: Path):
    return (
        path.is_dir()
        and (path / "model.bin").exists()
        and (path / "config.json").exists()
    )


def _find_named_model_under(root: Path, model_dir_name: str):
    if not root.exists():
        return None

    # Kaggle Notebook Output 通常會形成多層路徑，例如：
    # /kaggle/input/notebooks/<user>/<notebook>/persistent-model/taiwan-breeze-asr-26
    try:
        for config_path in root.rglob("config.json"):
            candidate = config_path.parent
            if candidate.name == model_dir_name and _looks_like_ct2_model(candidate):
                return candidate
    except Exception:
        return None

    return None


def resolve_model_source(model_name: str):
    """
    優先順序：
    1. ASR_MODEL_PATH 環境變數
    2. Kaggle 永久掛載 Input (/kaggle/input)
    3. Kaggle working 中已存在的完整模型
    4. Hugging Face repo id（faster-whisper 會下載）
    """
    explicit = os.getenv("ASR_MODEL_PATH", "").strip()
    if explicit:
        path = Path(explicit)
        if _looks_like_ct2_model(path):
            print(f"[ASR] 使用 ASR_MODEL_PATH 永久模型：{path}")
            return str(path)
        raise RuntimeError(f"ASR_MODEL_PATH 不是有效 CTranslate2 模型：{path}")

    model_dir_name = "taiwan-breeze-asr-26"

    # 先強制找 /kaggle/input，確保跨 Session 使用永久掛載模型。
    input_model = _find_named_model_under(Path("/kaggle/input"), model_dir_name)
    if input_model:
        print(f"[ASR] 使用 Kaggle 永久 Input 模型：{input_model}")
        return str(input_model)

    working_model = Path("/kaggle/working/persistent-model") / model_dir_name
    if _looks_like_ct2_model(working_model):
        print(f"[ASR] 使用本 Session 暫存模型：{working_model}")
        return str(working_model)

    print(
        "[ASR] 找不到永久掛載模型，將從 Hugging Face 下載。"
        "第一次準備模型時這是正常的。"
    )
    return model_name


def _load_model(model_name: str):
    global _MODEL, _MODEL_KEY

    try:
        cuda_device_count = int(ctranslate2.get_cuda_device_count())
    except Exception as exc:
        print(
            f"[ASR] CTranslate2 CUDA 偵測失敗：{type(exc).__name__}: {exc}",
            flush=True,
        )
        cuda_device_count = 0

    require_gpu = os.getenv("SOULKEY_REQUIRE_GPU", "").strip() == "1"
    if require_gpu and cuda_device_count < 1:
        raise RuntimeError(
            "GPU_REQUIRED_BUT_UNAVAILABLE: "
            "CTranslate2 看不到 CUDA GPU，拒絕以 CPU 執行 ASR。"
        )

    device = "cuda" if cuda_device_count > 0 else "cpu"
    compute_type = "int8_float16" if device == "cuda" else "int8"
    model_source = resolve_model_source(model_name)
    key = (model_source, device, compute_type)

    print(
        f"[ASR] CTranslate2 CUDA devices={cuda_device_count}; "
        f"require_gpu={require_gpu}",
        flush=True,
    )

    if _MODEL is None or _MODEL_KEY != key:
        print(
            f"[ASR] 載入模型: {model_source} / {device} / {compute_type}",
            flush=True,
        )

        kwargs = {
            "device": device,
            "compute_type": compute_type,
        }

        if not Path(model_source).exists():
            kwargs["download_root"] = "/kaggle/working/translation-model-cache"

        _MODEL = WhisperModel(model_source, **kwargs)
        _MODEL_KEY = key

    return _MODEL


def _srt_time(seconds: float):
    milliseconds = int(round(seconds * 1000))
    hours, rem = divmod(milliseconds, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _plain_time(seconds: float):
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _clean_asr_text(text: str):
    text = str(text or "").strip()
    # Whisper 常把一般敘述誤標成驚嘆語氣；ASR 原始稿先做最保守的標點正規化。
    text = text.replace("!", "。").replace("！", "。")
    text = text.replace("??", "？").replace("？？", "？")
    text = text.replace("..", "。").replace("。。", "。")
    text = re.sub(r"[，,]{2,}", "，", text)
    text = re.sub(r"[。]{2,}", "。", text)
    return text.strip()


def _join_word_text(parts):
    text = "".join(parts).strip()
    # faster-whisper 的中文 word token 偶爾帶前置空白。
    text = re.sub(r"\s+", "", text)
    return _clean_asr_text(text)


def _regroup_words(word_items):
    """
    將 word timestamp 重新組成適合課堂逐字稿的段落。
    目標：依真實停頓切句，避免 Whisper segment 邊界造成奇怪時間點。
    """
    if not word_items:
        return []

    result = []
    current = []

    strong_pause = 0.72
    medium_pause = 0.42
    min_chars_for_medium = 16
    target_chars = 28
    hard_chars = 46
    hard_seconds = 18.0
    min_segment_chars = 6

    def current_text():
        return _join_word_text([x["word"] for x in current])

    def flush():
        nonlocal current
        if not current:
            return
        text = current_text()
        if not text:
            current = []
            return
        result.append({
            "start": round(float(current[0]["start"]), 3),
            "end": round(float(current[-1]["end"]), 3),
            "text": text,
        })
        current = []

    for index, item in enumerate(word_items):
        if current:
            prev = current[-1]
            gap = max(0.0, float(item["start"]) - float(prev["end"]))
            chars = len(current_text())
            duration = float(prev["end"]) - float(current[0]["start"])

            # 長句優先在自然停頓處切；真的太長才強制切。
            if (
                gap >= strong_pause
                or (gap >= medium_pause and chars >= min_chars_for_medium)
                or (chars >= target_chars and gap >= 0.28)
                or chars >= hard_chars
                or duration >= hard_seconds
            ):
                flush()

        current.append(item)

    flush()

    # 避免「嗯、好、那」等極短碎段獨立存在；若與相鄰段間隔很短則合併。
    merged = []
    for seg in result:
        if (
            merged
            and len(seg["text"]) < min_segment_chars
            and float(seg["start"]) - float(merged[-1]["end"]) < 0.85
            and len(merged[-1]["text"]) + len(seg["text"]) <= hard_chars
        ):
            merged[-1]["end"] = seg["end"]
            merged[-1]["text"] = _clean_asr_text(
                merged[-1]["text"] + seg["text"]
            )
        else:
            merged.append(seg)

    return merged


def transcribe_audio(
    audio_path: str,
    output_dir: Path,
    model_name: str,
    glossary_terms=None,
):
    output_dir.mkdir(parents=True, exist_ok=True)
    model = _load_model(model_name)

    glossary_terms = [x.strip() for x in (glossary_terms or []) if x and x.strip()]
    glossary_terms = glossary_terms[:80]
    initial_prompt = None
    if glossary_terms:
        initial_prompt = "可能出現的專有名詞：" + "、".join(glossary_terms)

    print(f"[ASR] 開始辨識: {audio_path}", flush=True)
    segments_iter, info = model.transcribe(
        str(audio_path),
        language="zh",
        task="transcribe",
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 350},
        condition_on_previous_text=True,
        initial_prompt=initial_prompt,
        word_timestamps=True,
    )

    model_segments = []
    word_items = []

    for seg in segments_iter:
        text = _clean_asr_text(seg.text or "")
        if text:
            model_segments.append({
                "start": round(float(seg.start), 3),
                "end": round(float(seg.end), 3),
                "text": text,
            })

        for word in (getattr(seg, "words", None) or []):
            word_text = str(getattr(word, "word", "") or "").strip()
            word_start = getattr(word, "start", None)
            word_end = getattr(word, "end", None)
            if not word_text or word_start is None or word_end is None:
                continue
            word_items.append({
                "start": float(word_start),
                "end": float(word_end),
                "word": word_text,
            })

    if word_items:
        segments = _regroup_words(word_items)
        print(
            f"[ASR] 使用 word timestamps 重新斷句："
            f"{len(word_items)} 詞 → {len(segments)} 段",
            flush=True,
        )
    else:
        segments = model_segments
        print(
            "[ASR] 模型未提供 word timestamps；退回 Whisper 原始 segments。",
            flush=True,
        )

    for item in segments:
        print(
            f"[ASR] {_plain_time(item['start'])} -> "
            f"{_plain_time(item['end'])} {item['text']}"
        )

    # 若模型沒有 word timestamp 或極少數 timestamp 異常，保留最後一道修復。
    # word timestamp 正常時幾乎不會進入此分支。
    # 僅修正 end < start 這種明確無效時間，不再把 end 拉到下一段 start，
    # 避免把真實停頓誤吃進字幕時間軸。
    repaired = 0
    for i in range(len(segments) - 1):
        current = segments[i]
        nxt = segments[i + 1]
        start = float(current["start"])
        end = float(current["end"])
        next_start = float(nxt["start"])
        if end < start and next_start > start:
            current["end"] = round(min(next_start, start + 0.5), 3)
            repaired += 1

    if repaired:
        print(
            f"[ASR] 修正 {repaired} 個無效 end timestamp。",
            flush=True,
        )

    txt_path = output_dir / "zh-TW.txt"
    srt_path = output_dir / "zh-TW.srt"
    json_path = output_dir / "segments.json"

    txt_lines = [
        f"[{_plain_time(x['start'])} - {_plain_time(x['end'])}] {x['text']}"
        for x in segments
    ]
    txt_path.write_text("\n".join(txt_lines) + "\n", encoding="utf-8")

    srt_lines = []
    for i, item in enumerate(segments, start=1):
        srt_lines.extend(
            [
                str(i),
                f"{_srt_time(item['start'])} --> {_srt_time(item['end'])}",
                item["text"],
                "",
            ]
        )
    srt_path.write_text("\n".join(srt_lines), encoding="utf-8")

    payload = {
        "model": model_name,
        "language": getattr(info, "language", "zh"),
        "language_probability": getattr(info, "language_probability", None),
        "duration": getattr(info, "duration", None),
        "duration_after_vad": getattr(info, "duration_after_vad", None),
        "segments": segments,
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "txt": txt_path,
        "srt": srt_path,
        "json": json_path,
        "segment_count": len(segments),
        "duration": payload.get("duration"),
    }
