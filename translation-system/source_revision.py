"""Audio-source provenance for ASR checkpoint reuse.

Never trust the mere existence of Drive segments.json after a YouTube URL
change. Reuse is permitted only if the source ID is identical or a strong
audio-content match is verified with matching timing.
"""
from __future__ import annotations

import base64
import json
import math
import tempfile
import wave
import zlib
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from google_io import download_drive_file, find_file, upload_or_replace_file


def video_id(url):
    text = str(url or "").strip()
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if host in {"youtu.be", "www.youtu.be"}:
        return parsed.path.strip("/").split("/")[0]
    if host == "youtube.com" or host.endswith(".youtube.com"):
        pieces = [part for part in parsed.path.split("/") if part]
        if pieces and pieces[0] == "watch":
            return (parse_qs(parsed.query).get("v") or [""])[0]
        if len(pieces) > 1 and pieces[0] in {"live", "embed", "shorts"}:
            return pieces[1]
    return ""


def audio_signature(wav_path):
    """50ms loudness plus spectral bands; timeline-strict audio identity."""
    import numpy as np

    path = Path(wav_path)
    with wave.open(str(path), "rb") as src:
        if src.getnchannels() != 1 or src.getsampwidth() != 2:
            raise RuntimeError("Audio fingerprint requires mono 16-bit WAV")
        sample_rate = src.getframerate()
        frame_samples = max(1, round(sample_rate * 0.05))
        values = []
        spectra = []
        spectrum_edges = [0, 250, 500, 1000, 2000, 4000, 8000]
        while True:
            chunk = src.readframes(frame_samples)
            if not chunk:
                break
            pcm = np.frombuffer(chunk, dtype="<i2").astype(np.float32)
            if pcm.size:
                values.append(float(np.sqrt(np.mean(pcm * pcm))))
                # Compare spectral content as well as volume. Two different
                # voices can have almost identical loudness envelopes.
                power = np.abs(np.fft.rfft(pcm * np.hanning(len(pcm)))) ** 2
                frequencies = np.fft.rfftfreq(len(pcm), d=1 / sample_rate)
                energies = np.array([
                    power[(frequencies >= low) & (frequencies < high)].sum()
                    for low, high in zip(spectrum_edges[:-1], spectrum_edges[1:])
                ], dtype=np.float64)
                total = float(energies.sum())
                spectra.extend(
                    int(round(255 * float(v) / total)) if total > 1 else 0
                    for v in energies
                )
        duration = src.getnframes() / sample_rate

    # Quantize log-RMS in roughly 0.2dB steps, preserving silence and pauses.
    # Fixed quantization avoids gain-based auto matching false positives.
    quantized = bytes(
        max(0, min(255, round(255 * math.log1p(v) / math.log1p(32768))))
        for v in values
    )
    return {
        "version": "rms50-spectral-v2",
        "duration": round(duration, 3),
        "frames": len(values),
        "data": base64.b64encode(zlib.compress(quantized, 9)).decode("ascii"),
        "spectra": base64.b64encode(
            zlib.compress(bytes(spectra), 9)
        ).decode("ascii"),
    }


def equivalent_audio(left, right):
    """Conservative match: same duration, envelope and spectral content."""
    import numpy as np

    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    if (left.get("version") != "rms50-spectral-v2"
            or right.get("version") != "rms50-spectral-v2"):
        return False
    try:
        if abs(float(left.get("duration", 0)) - float(right.get("duration", 0))) > 0.5:
            return False
    except (ValueError, TypeError):
        return False

    try:
        a = np.frombuffer(zlib.decompress(base64.b64decode(left["data"])), dtype=np.uint8).astype(np.float32)
        b = np.frombuffer(zlib.decompress(base64.b64decode(right["data"])), dtype=np.uint8).astype(np.float32)
        sa = np.frombuffer(zlib.decompress(base64.b64decode(left["spectra"])), dtype=np.uint8)
        sb = np.frombuffer(zlib.decompress(base64.b64decode(right["spectra"])), dtype=np.uint8)
    except Exception:
        return False
    if min(len(a), len(b)) < 1200 or abs(len(a) - len(b)) > 10:
        return False
    if len(sa) != len(a) * 6 or len(sb) != len(b) * 6:
        return False
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    if float(a.std()) < 2.0 or float(b.std()) < 2.0:
        return False
    similarity = float(np.corrcoef(a, b)[0, 1])
    # Different lectures can have similar overall noise floors. Require
    # strong agreement across four quarters, not just aggregate correlation.
    if not math.isfinite(similarity) or similarity < 0.995:
        return False
    for i in range(4):
        x, y = a[n*i//4:n*(i+1)//4], b[n*i//4:n*(i+1)//4]
        if float(x.std()) < 2 or float(y.std()) < 2:
            return False
        if float(np.corrcoef(x, y)[0, 1]) < 0.990:
            return False

    spectra_a = sa[:n*6].reshape(-1, 6).astype(np.float32)
    spectra_b = sb[:n*6].reshape(-1, 6).astype(np.float32)
    active = (a > 80) & (b > 80)
    if int(active.sum()) < n * 0.10:
        return False
    spectral_diff = np.abs(spectra_a[active] - spectra_b[active]).mean(axis=1)
    if float(spectral_diff.mean()) > 6.0:
        return False
    if float(np.percentile(spectral_diff, 90)) > 12.0:
        return False
    return True


def _read_json(drive, folder_id, name, tempdir):
    item = find_file(drive, folder_id, name)
    if not item:
        return None
    dest = Path(tempdir) / name
    download_drive_file(drive, item["id"], dest)
    return json.loads(dest.read_text(encoding="utf-8"))


def verify_existing_asr(drive, folders, current_url, workdir, download_audio_fn):
    """Return (reusable, reason), updating metadata only after proof.

    If the previous video is deleted and lacks an audio signature, reuse
    is unprovable and the caller must re-transcribe; no guessing by title
    or similar duration.
    """
    with tempfile.TemporaryDirectory(prefix="soulkey-source-check-") as tmp:
        try:
            previous = _read_json(drive, folders["source"], "source_info.json", tmp)
        except (OSError, ValueError, TypeError) as exc:
            print("[SOURCE] Source manifest unreadable: " + type(exc).__name__, flush=True)
            return False, "source_info_unreadable"
        if not isinstance(previous, dict) or not previous:
            return False, "no_source_info"
        old_url = str(previous.get("youtube_url") or previous.get("webpage_url") or "").strip()
        if not old_url:
            return False, "no_recorded_url"

        old_id = video_id(old_url)
        current_id = video_id(current_url)
        if old_id and current_id and old_id == current_id:
            return True, "same_youtube_video_id"
        if not old_id or not current_id:
            return False, "unrecognized_youtube_video_id"

        # If metadata already recorded the old audio envelope, no need to
        # fetch a disappeared old YouTube upload.
        old_signature = previous.get("audio_signature")
        if not old_signature:
            try:
                old_dir = Path(workdir) / "verify-original"
                old_wav, _ = download_audio_fn(old_url, old_dir)
                old_signature = audio_signature(old_wav)
            except Exception as exc:
                print("[SOURCE] Cannot re-fetch original video; ASR required: " +
                      type(exc).__name__, flush=True)
                return False, "original_audio_unavailable"

        try:
            new_dir = Path(workdir) / "verify-new-upload"
            new_wav, new_meta = download_audio_fn(current_url, new_dir)
            new_signature = audio_signature(new_wav)
        except Exception as exc:
            print("[SOURCE] New audio comparison failed: " + type(exc).__name__, flush=True)
            return False, "new_audio_unavailable"

        if not equivalent_audio(old_signature, new_signature):
            return False, "audio_or_timeline_changed"

        # Only an affirmative match can advance provenance without ASR.
        previous["source_history"] = (
            list(previous.get("source_history") or []) +
            [{"youtube_url": old_url, "source_id": old_id, "result": "audio_matched"}]
        )[-20:]
        previous["youtube_url"] = current_url
        previous["webpage_url"] = (new_meta or {}).get("webpage_url") or current_url
        previous["audio_signature"] = new_signature
        previous["id"] = current_id
        file_path = Path(tmp) / "source_info_verified.json"
        file_path.write_text(json.dumps(previous, ensure_ascii=False, indent=2), encoding="utf-8")
        source_item = find_file(drive, folders["source"], "source_info.json")
        upload_or_replace_file(
            drive, folders["source"], file_path, "source_info.json",
            display_name=(source_item or {}).get("name") or "source_info.json",
        )
        return True, "audio_and_timeline_match"
