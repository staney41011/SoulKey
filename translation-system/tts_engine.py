import gc
import os
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import numpy as np
import torch
from scipy.io import wavfile
from transformers import AutoTokenizer, VitsModel, set_seed


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


def resolve_tts_model(model_id: str):
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
