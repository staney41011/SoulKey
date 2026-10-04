import gc
import io
import hashlib
import os
import json
import re
import shutil
import time
import wave
import subprocess
import zipfile
from pathlib import Path

import numpy as np
import torch
from scipy.io import wavfile
from transformers import AutoTokenizer, VitsModel, set_seed

from gemini_engine import GeminiClient


DIGIT_WORDS = {
    "en": ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"],
    "th": ["ศูนย์", "หนึ่ง", "สอง", "สาม", "สี่", "ห้า", "หก", "เจ็ด", "แปด", "เก้า"],
    "es": ["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve"],
    "id": ["nol", "satu", "dua", "tiga", "empat", "lima", "enam", "tujuh", "delapan", "sembilan"],
    "vi": ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"],
    "sd": ["ٻُڙي", "هڪ", "ٻه", "ٽي", "چار", "پنج", "ڇهه", "ست", "اٺ", "نو"],
    "ta": ["பூஜ்ஜியம்", "ஒன்று", "இரண்டு", "மூன்று", "நான்கு", "ஐந்து", "ஆறு", "ஏழு", "எட்டு", "ஒன்பது"],
}


def segments_fingerprint(segments):
    canonical = [
        {
            "id": int(seg.get("id", i)),
            "start": float(seg.get("start", 0) or 0),
            "end": float(seg.get("end", 0) or 0),
            "text": str(seg.get("text") or ""),
        }
        for i, seg in enumerate(segments or [])
    ]
    raw = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _input_length(inputs):
    """Return tokenizer input length for dicts and Transformers BatchEncoding.

    AutoTokenizer returns BatchEncoding (a mapping-like object, not necessarily
    an actual dict). The old isinstance(inputs, dict) guard misclassified every
    normal MMS tokenization as zero-length and skipped all speech generation.
    """
    ids = None
    try:
        ids = inputs.get("input_ids")
    except Exception:
        ids = getattr(inputs, "input_ids", None)
    if ids is None:
        return 0
    try:
        return int(ids.shape[-1])
    except Exception:
        return 0


def _numeric_spoken_fallback(text: str, lang: str):
    digits = re.findall(r"\d", str(text or ""))
    if not digits or lang not in DIGIT_WORDS:
        return ""
    return " ".join(DIGIT_WORDS[lang][int(d)] for d in digits)


def _looks_like_hf_model(path: Path):
    return path.is_dir() and (path / "config.json").exists()


def _find_named_model(root: Path, dirname: str):
    if not root.exists():
        return None
    try:
        for config in root.rglob("config.json"):
            candidate = config.parent
            if candidate.name == dirname and _looks_like_hf_model(candidate):
                return candidate
    except Exception:
        return None
    return None


def _convert_original_mms_model(language: str, output_dir: Path):
    """Convert Meta's original MMS checkpoint to HF VITS format on demand."""
    if _looks_like_hf_model(output_dir):
        return str(output_dir)

    print(
        f"[TTS] 轉換 Meta MMS 原始 checkpoint：{language} -> {output_dir}",
        flush=True,
    )
    output_dir.parent.mkdir(parents=True, exist_ok=True)

    try:
        from transformers.models.vits.convert_original_checkpoint import (
            convert_checkpoint,
        )
        converter_source = "transformers"
    except Exception:
        # transformers 5.17.0 no longer ships this helper in the wheel even
        # though SoulKey still needs it for original MMS collection models.
        from mms_vits_converter import convert_checkpoint
        converter_source = "soulkey-vendored"

    print(f"[TTS] MMS converter：{converter_source}", flush=True)

    convert_checkpoint(
        pytorch_dump_folder_path=str(output_dir),
        language=language,
    )
    if not _looks_like_hf_model(output_dir):
        raise RuntimeError(
            f"Meta MMS {language} 轉換完成後找不到 config.json"
        )
    return str(output_dir)


def resolve_tts_model(model_id: str):
    original_prefix = "facebook/mms-tts/models/"
    if model_id.startswith(original_prefix):
        language = model_id[len(original_prefix):].strip("/")
        if not language:
            raise RuntimeError("MMS original model 缺少語言代碼")

        dirname = f"mms-tts-{language}"
        input_model = _find_named_model(Path("/kaggle/input"), dirname)
        if input_model:
            print(f"[TTS] 使用 Kaggle 永久 Input 模型：{input_model}")
            return str(input_model)

        working_model = Path("/kaggle/working/persistent-model") / dirname
        return _convert_original_mms_model(language, working_model)

    dirname = model_id.rsplit("/", 1)[-1]

    input_model = _find_named_model(Path("/kaggle/input"), dirname)
    if input_model:
        print(f"[TTS] 使用 Kaggle 永久 Input 模型：{input_model}")
        return str(input_model)

    working_model = Path("/kaggle/working/persistent-model") / dirname
    if _looks_like_hf_model(working_model):
        print(f"[TTS] 使用本 Session 永久模型：{working_model}")
        return str(working_model)

    print(f"[TTS] 找不到永久模型，將從 Hugging Face 取得：{model_id}")
    return model_id


def _split_for_tts(text: str, max_chars=220):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return []

    pieces = re.split(r"(?<=[。！？!?；;：:.])\s*", text)
    chunks = []
    current = ""

    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        if len(current) + len(piece) + 1 <= max_chars:
            current = (current + " " + piece).strip()
        else:
            if current:
                chunks.append(current)
            while len(piece) > max_chars:
                chunks.append(piece[:max_chars])
                piece = piece[max_chars:]
            current = piece

    if current:
        chunks.append(current)

    return chunks


def _float_audio(x):
    x = np.asarray(x, dtype=np.float32).reshape(-1)
    if not len(x):
        return x
    peak = float(np.max(np.abs(x)))
    if peak > 1.0:
        x = x / peak
    return np.clip(x, -1.0, 1.0)


def _write_wav(path: Path, sample_rate: int, audio):
    path.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(str(path), sample_rate, _float_audio(audio))


def _wav_to_mp3(wav_path: Path, mp3_path: Path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("找不到 FFmpeg，無法產生 MP3")
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(wav_path),
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "128k",
            str(mp3_path),
        ],
        check=True,
    )



def _read_wav_bytes(audio_bytes):
    with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
        channels = int(wf.getnchannels())
        sample_width = int(wf.getsampwidth())
        sample_rate = int(wf.getframerate())
        raw = wf.readframes(wf.getnframes())

    if sample_width != 2:
        raise RuntimeError(
            f"Gemini TTS WAV sample width 不支援：{sample_width}"
        )

    audio = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return sample_rate, _float_audio(audio)


def _gemini_tts_batches(segments, max_chars=1400, max_segments=24):
    batches = []
    current = []
    chars = 0

    for seg in segments or []:
        text = str(seg.get("text") or "").strip()
        if not text:
            continue
        added = len(text) + (1 if current else 0)
        if current and (
            chars + added > max_chars or len(current) >= max_segments
        ):
            batches.append(current)
            current = []
            chars = 0
        current.append(seg)
        chars += len(text) + (1 if len(current) > 1 else 0)

    if current:
        batches.append(current)
    return batches


def synthesize_gemini_language(
    segments,
    lang: str,
    output_dir: Path,
    target_duration=None,
    model_id="gemini-3.8-flash-tts",
    voice="Kore",
    request_gap_seconds=12,
):
    """Generate low-resource TTS with Gemini while preserving SoulKey outputs.

    Sindhi is supported by Gemini 3.8 Flash TTS, while the historical MMS
    download path used by SoulKey no longer provides a reliable snd model.
    Requests are grouped into short batches to avoid long-form voice drift and
    to keep API usage practical.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    segment_dir = output_dir / f"{lang}_segments"
    segment_dir.mkdir(parents=True, exist_ok=True)

    client = GeminiClient(
        api_key=os.getenv("GEMINI_API_KEY", ""),
        tts_model=model_id,
        max_attempts=4,
        timeout=180,
    )
    batches = _gemini_tts_batches(segments)
    if not batches:
        raise RuntimeError(f"{lang} 沒有可供 Gemini TTS 朗讀的文字")

    print(
        f"[TTS:{lang}] Gemini fallback：model={model_id}；"
        f"batches={len(batches)}",
        flush=True,
    )

    full_parts = []
    manifest_segments = []
    sample_rate = None
    between_batch = None

    for batch_index, batch in enumerate(batches, start=1):
        text = "\n".join(
            str(seg.get("text") or "").strip()
            for seg in batch
            if str(seg.get("text") or "").strip()
        )
        if not text:
            continue

        print(
            f"[TTS:{lang}] Gemini batch {batch_index}/{len(batches)}；"
            f"segments={len(batch)}；chars={len(text)}",
            flush=True,
        )
        audio_bytes, _, usage = client.tts(
            text,
            voice=voice,
            style=(
                "Clear, calm, natural Sindhi teaching narration. "
                "Read the transcript faithfully without adding or omitting content."
            ),
            model=model_id,
        )
        batch_rate, audio = _read_wav_bytes(audio_bytes)
        if sample_rate is None:
            sample_rate = batch_rate
            between_batch = np.zeros(
                int(sample_rate * 0.25),
                dtype=np.float32,
            )
        elif batch_rate != sample_rate:
            raise RuntimeError(
                f"Gemini TTS 取樣率不一致：{sample_rate} -> {batch_rate}"
            )

        if not len(audio):
            raise RuntimeError(
                f"{lang} Gemini batch {batch_index} 沒有產生音訊"
            )

        batch_path = segment_dir / f"batch_{batch_index:04d}.wav"
        _write_wav(batch_path, sample_rate, audio)

        start = float(batch[0].get("start", 0) or 0)
        end = float(batch[-1].get("end", start) or start)
        manifest_segments.append({
            "id": int(batch[0].get("id", batch_index - 1)),
            "source_ids": [
                int(seg.get("id", i))
                for i, seg in enumerate(batch)
            ],
            "start": start,
            "end": end,
            "source_duration": round(max(0.0, end - start), 3),
            "generated_duration": round(len(audio) / sample_rate, 3),
            "text": text,
            "file": batch_path.name,
            "gemini_total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        })

        full_parts.append(audio)
        full_parts.append(between_batch)

        if batch_index < len(batches) and request_gap_seconds:
            time.sleep(float(request_gap_seconds))

    if not full_parts or sample_rate is None:
        raise RuntimeError(f"{lang} 沒有產生任何 Gemini TTS 音訊")

    speech_audio = np.concatenate(full_parts[:-1])
    speech_duration = len(speech_audio) / sample_rate
    target_duration = (
        float(target_duration)
        if target_duration is not None and float(target_duration) > 0
        else None
    )

    within_source_duration = True
    remaining_silence = 0.0
    over_by_seconds = 0.0
    if target_duration is not None and speech_duration <= target_duration:
        remaining_silence = max(0.0, target_duration - speech_duration)
        pad_samples = int(round(remaining_silence * sample_rate))
        full_audio = (
            np.concatenate([
                speech_audio,
                np.zeros(pad_samples, dtype=np.float32),
            ])
            if pad_samples > 0
            else speech_audio
        )
    elif target_duration is not None:
        within_source_duration = False
        over_by_seconds = speech_duration - target_duration
        full_audio = speech_audio
    else:
        full_audio = speech_audio

    wav_path = output_dir / f"{lang}.wav"
    mp3_path = output_dir / f"{lang}.mp3"
    manifest_path = output_dir / f"{lang}.tts_manifest.json"
    zip_path = output_dir / f"{lang}.segments.zip"

    _write_wav(wav_path, sample_rate, full_audio)
    _wav_to_mp3(wav_path, mp3_path)

    manifest = {
        "language": lang,
        "model": model_id,
        "engine": "gemini-tts",
        "source_sha256": segments_fingerprint(segments),
        "sample_rate": sample_rate,
        "timeline_aligned": False,
        "duration_policy": "natural_speech_no_speed_change_no_segment_alignment",
        "target_duration": round(target_duration, 3) if target_duration else None,
        "speech_duration": round(speech_duration, 3),
        "full_duration": round(len(full_audio) / sample_rate, 3),
        "within_source_duration": within_source_duration,
        "remaining_silence": round(remaining_silence, 3),
        "over_by_seconds": round(over_by_seconds, 3),
        "note": (
            "Sindhi 使用 Gemini TTS 短批次朗讀；不做逐段時間對齊、不調速。"
            "若較短僅在尾端補靜音；若超過原片長度則保留完整內容並標記人工確認。"
        ),
        "segments": manifest_segments,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for wav_path_item in sorted(segment_dir.glob("*.wav")):
            zf.write(wav_path_item, arcname=wav_path_item.name)

    return {
        "wav": wav_path,
        "mp3": mp3_path,
        "manifest": manifest_path,
        "segments_zip": zip_path,
        "duration": manifest["full_duration"],
        "speech_duration": manifest["speech_duration"],
        "target_duration": manifest["target_duration"],
        "within_source_duration": manifest["within_source_duration"],
        "remaining_silence": manifest["remaining_silence"],
        "over_by_seconds": manifest["over_by_seconds"],
        "segment_count": len(manifest_segments),
        "model": model_id,
    }


def synthesize_language(
    segments,
    lang: str,
    model_id: str,
    output_dir: Path,
    seed=555,
    target_duration=None,
):
    output_dir.mkdir(parents=True, exist_ok=True)
    segment_dir = output_dir / f"{lang}_segments"
    segment_dir.mkdir(parents=True, exist_ok=True)

    source = resolve_tts_model(model_id)
    print(f"[TTS:{lang}] 載入模型：{source}")

    tokenizer = AutoTokenizer.from_pretrained(source)
    model = VitsModel.from_pretrained(source)

    require_gpu = os.getenv("SOULKEY_REQUIRE_GPU", "").strip() == "1"
    cuda_ok = bool(torch.cuda.is_available())
    if require_gpu and not cuda_ok:
        raise RuntimeError(
            "GPU_REQUIRED_BUT_UNAVAILABLE: "
            "PyTorch 看不到 CUDA GPU，拒絕以 CPU 執行 TTS。"
        )

    device = "cuda" if cuda_ok else "cpu"
    if cuda_ok:
        print(
            f"[TTS:{lang}] GPU 模式：{torch.cuda.get_device_name(0)}",
            flush=True,
        )
    model = model.to(device)
    model.eval()

    sample_rate = int(model.config.sampling_rate)
    between_piece = np.zeros(int(sample_rate * 0.08), dtype=np.float32)
    between_segment = np.zeros(int(sample_rate * 0.25), dtype=np.float32)

    full_parts = []
    manifest_segments = []

    for order, seg in enumerate(segments, start=1):
        seg_id = int(seg.get("id", order - 1))
        text = str(seg.get("text") or "").strip()
        chunks = _split_for_tts(text)

        if not chunks:
            continue

        print(f"[TTS:{lang}] segment {order}/{len(segments)}")
        piece_audio = []

        for chunk_index, chunk in enumerate(chunks):
            inputs = tokenizer(text=chunk, return_tensors="pt")

            # MMS VITS crashes inside relative-position attention when the
            # tokenizer returns a zero-length sequence. This legitimately
            # happens for punctuation-only / unsupported-script fragments.
            # Numeric headings such as "7." are first converted to spoken
            # target-language digits; other empty fragments are skipped rather
            # than aborting the entire language.
            if _input_length(inputs) <= 0:
                fallback_text = _numeric_spoken_fallback(chunk, lang)
                if fallback_text:
                    print(
                        f"[TTS:{lang}] zero-token chunk -> numeric fallback: "
                        f"{chunk!r} -> {fallback_text!r}",
                        flush=True,
                    )
                    inputs = tokenizer(text=fallback_text, return_tensors="pt")

            if _input_length(inputs) <= 0:
                print(
                    f"[TTS:{lang}] skip zero-token chunk: {chunk!r}",
                    flush=True,
                )
                continue

            inputs = {k: v.to(device) for k, v in inputs.items()}
            set_seed(seed + seg_id + chunk_index)

            with torch.inference_mode():
                output = model(**inputs).waveform[0]

            audio = _float_audio(output.detach().cpu().numpy())
            if len(audio):
                piece_audio.append(audio)
                if chunk_index < len(chunks) - 1:
                    piece_audio.append(between_piece)

        if not piece_audio:
            continue

        segment_audio = np.concatenate(piece_audio)
        segment_path = segment_dir / f"{seg_id:04d}.wav"
        _write_wav(segment_path, sample_rate, segment_audio)

        generated_seconds = len(segment_audio) / sample_rate
        source_seconds = max(0.0, float(seg.get("end", 0)) - float(seg.get("start", 0)))

        manifest_segments.append({
            "id": seg_id,
            "start": float(seg.get("start", 0)),
            "end": float(seg.get("end", 0)),
            "source_duration": round(source_seconds, 3),
            "generated_duration": round(generated_seconds, 3),
            "text": text,
            "file": segment_path.name,
        })

        full_parts.append(segment_audio)
        full_parts.append(between_segment)

    if not full_parts:
        raise RuntimeError(f"{lang} 沒有產生任何音訊")

    speech_audio = np.concatenate(full_parts[:-1])
    speech_duration = len(speech_audio) / sample_rate

    target_duration = (
        float(target_duration)
        if target_duration is not None and float(target_duration) > 0
        else None
    )
    within_source_duration = True
    remaining_silence = 0.0
    over_by_seconds = 0.0

    if target_duration is not None:
        if speech_duration <= target_duration:
            remaining_silence = max(0.0, target_duration - speech_duration)
            pad_samples = int(round(remaining_silence * sample_rate))
            if pad_samples > 0:
                full_audio = np.concatenate([
                    speech_audio,
                    np.zeros(pad_samples, dtype=np.float32),
                ])
            else:
                full_audio = speech_audio
        else:
            # 使用者要求不調速、不截字，因此超過原片長度時保留完整語音，
            # 並明確標記需要人工處理，而不是破壞內容。
            within_source_duration = False
            over_by_seconds = speech_duration - target_duration
            full_audio = speech_audio
    else:
        full_audio = speech_audio

    wav_path = output_dir / f"{lang}.wav"
    mp3_path = output_dir / f"{lang}.mp3"
    manifest_path = output_dir / f"{lang}.tts_manifest.json"
    zip_path = output_dir / f"{lang}.segments.zip"

    _write_wav(wav_path, sample_rate, full_audio)
    _wav_to_mp3(wav_path, mp3_path)

    manifest = {
        "language": lang,
        "model": model_id,
        "source_sha256": segments_fingerprint(segments),
        "sample_rate": sample_rate,
        "timeline_aligned": False,
        "duration_policy": "natural_speech_no_speed_change_no_segment_alignment",
        "target_duration": round(target_duration, 3) if target_duration else None,
        "speech_duration": round(speech_duration, 3),
        "full_duration": round(len(full_audio) / sample_rate, 3),
        "within_source_duration": within_source_duration,
        "remaining_silence": round(remaining_silence, 3),
        "over_by_seconds": round(over_by_seconds, 3),
        "note": (
            "目前只要求完整朗讀在原片總長內結束；不做逐段時間對齊、"
            "不調整語速，也不為了時間重新斷句。若朗讀較短，僅在尾端補靜音；"
            "若朗讀超過原片長度，保留完整內容並標記需要人工處理，不截斷語音。"
        ),
        "segments": manifest_segments,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for wav in sorted(segment_dir.glob("*.wav")):
            zf.write(wav, arcname=wav.name)

    del model
    del tokenizer
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    return {
        "wav": wav_path,
        "mp3": mp3_path,
        "manifest": manifest_path,
        "segments_zip": zip_path,
        "duration": manifest["full_duration"],
        "speech_duration": manifest["speech_duration"],
        "target_duration": manifest["target_duration"],
        "within_source_duration": manifest["within_source_duration"],
        "remaining_silence": manifest["remaining_silence"],
        "over_by_seconds": manifest["over_by_seconds"],
        "segment_count": len(manifest_segments),
        "model": model_id,
    }
