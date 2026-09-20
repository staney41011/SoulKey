import json
from pathlib import Path

import torch
from faster_whisper import WhisperModel

_MODEL = None
_MODEL_KEY = None


def _load_model(model_name: str):
    global _MODEL, _MODEL_KEY

    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    key = (model_name, device, compute_type)

    if _MODEL is None or _MODEL_KEY != key:
        print(f"[ASR] 載入模型: {model_name} / {device} / {compute_type}")
        _MODEL = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
            download_root="/kaggle/working/translation-model-cache",
        )
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

    print(f"[ASR] 開始辨識: {audio_path}")
    segments_iter, info = model.transcribe(
        str(audio_path),
        language="zh",
        task="transcribe",
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=True,
        initial_prompt=initial_prompt,
        word_timestamps=False,
    )

    segments = []
    for seg in segments_iter:
        text = (seg.text or "").strip()
        if not text:
            continue
        item = {
            "start": round(float(seg.start), 3),
            "end": round(float(seg.end), 3),
            "text": text,
        }
        segments.append(item)
        print(
            f"[ASR] {_plain_time(item['start'])} -> "
            f"{_plain_time(item['end'])} {text}"
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
