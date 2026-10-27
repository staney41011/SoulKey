"""SoulKey Voice A/B: Edge Neural vs VoxCPM2, isolated from production.

Usage:
  python run_ab.py --samples samples.demo.json --output-dir ./out --dry-run
  python run_ab.py --samples my_approved_samples.json --output-dir ./out
  python run_ab.py --samples ... --edge-only

Model load occurs only after strict input/GPU preflight.
No Google/Drive/Studio credentials or production files are read or modified.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

LANGS = ("en", "th", "km", "lo", "my")
MODEL_ID = "openbmb/VoxCPM2"
VOICES = {
    "en": {"voice": "en-US-AndrewMultilingualNeural", "rate": "-4%", "pitch": "-2Hz"},
    "th": {"voice": "th-TH-NiwatNeural", "rate": "-3%", "pitch": "-1Hz"},
    "km": {"voice": "km-KH-PisethNeural", "rate": "-3%", "pitch": "-1Hz"},
    "lo": {"voice": "lo-LA-ChanthavongNeural", "rate": "-3%", "pitch": "-1Hz"},
    "my": {"voice": "my-MM-ThihaNeural", "rate": "-3%", "pitch": "-1Hz"},
}
DEFAULT_DIR = Path("/kaggle/working/soulkey-voice-ab")


def validate_samples(payload: dict) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise ValueError("Samples JSON must be an object")
    languages = payload.get("languages")
    if not isinstance(languages, dict):
        raise ValueError("Expected 'languages' mapping in samples JSON")
    missing = [lang for lang in LANGS if lang not in languages]
    if missing:
        raise ValueError("Missing requested languages: " + ", ".join(missing))
    result = {}
    for lang in LANGS:
        entry = languages[lang]
        text = entry.get("text") if isinstance(entry, dict) else entry
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"{lang}: missing non-empty text")
        if len(text) > 1500:
            raise ValueError(f"{lang}: max 1500 characters for pilot (chunk longer samples)")
        if "\x00" in text:
            raise ValueError(f"{lang}: NUL not allowed")
        result[lang] = text.strip()
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def preflight(*, voxel: bool) -> dict:
    import shutil as sh
    info = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "ffmpeg": bool(sh.which("ffmpeg")),
        "cuda_required": voxel,
    }
    if not (sys.version_info >= (3, 10) and sys.version_info < (3, 13)):
        raise RuntimeError(
            "VoxCPM2 requires Python 3.10-3.12; this runtime is "
            + info["python"] + ". Switch Kaggle environment, not production dependencies."
        )
    if not info["ffmpeg"]:
        raise RuntimeError("ffmpeg is required for normalized WAV comparison")
    if voxel:
        try:
            import torch
        except ImportError as exc:
            raise RuntimeError("PyTorch not installed") from exc
        info["torch"] = torch.__version__
        info["cuda_available"] = bool(torch.cuda.is_available())
        if not info["cuda_available"]:
            raise RuntimeError("Enable a GPU in Kaggle: Settings > Accelerator")
        index = 0
        info["gpu"] = torch.cuda.get_device_name(index)
        info["free_vram_gib"] = round(torch.cuda.mem_get_info(index)[0] / (1024 ** 3), 2)
        info["bf16_supported"] = bool(torch.cuda.is_bf16_supported())
        if info["free_vram_gib"] < 7.4:
            raise RuntimeError("Not enough free VRAM for VoxCPM2 (needs roughly 8 GB)")
    return info


def normalize_wav(source: Path, target: Path, *, sample_rate: int = 48000) -> None:
    """Standardize playback formats; neither time-stretch nor change pitch."""
    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source), "-ar", str(sample_rate), "-ac", "1",
        "-c:a", "pcm_s16le", str(target),
    ]
    subprocess.run(cmd, check=True, timeout=120)


def inspect_wav(path: Path) -> dict:
    import soundfile as sf
    info = sf.info(str(path))
    if info.frames <= 0 or info.samplerate <= 0 or info.duration <= 0.1:
        raise RuntimeError(f"Empty or malformed output: {path.name}")
    if path.stat().st_size < 1500:
        raise RuntimeError(f"Unexpectedly tiny file: {path.name}")
    return {
        "seconds": round(float(info.duration), 3),
        "sample_rate": int(info.samplerate),
        "sha256": sha256_file(path),
        "file": path.name,
    }


async def generate_edge(lang: str, text: str, output_dir: Path) -> dict:
    import edge_tts
    voice = VOICES[lang]
    raw = output_dir / f"{lang}_edge.raw.mp3"
    wav = output_dir / f"{lang}_edge.wav"
    started = time.perf_counter()
    await edge_tts.Communicate(
        text=text, voice=voice["voice"], rate=voice["rate"], pitch=voice["pitch"]
    ).save(str(raw))
    normalize_wav(raw, wav)
    result = inspect_wav(wav)
    result.update(
        "engine", "edge", "lang", lang, "voice", voice["voice"],
    ) if False else None
    result.update({
        "engine": "edge", "language": lang, "voice": voice["voice"],
        "generation_seconds": round(time.perf_counter() - started, 3),
    })
    result["rtf"] = round(result["generation_seconds"] / result["seconds"], 3)
    return result


def load_voxcpm():
    from voxcpm import VoxCPM
    return VoxCPM.from_pretrained(
        MODEL_ID, load_denoiser=False, device="cuda", optimize=False
    )


def generate_voxcpm(model, lang: str, text: str, output_dir: Path) -> dict:
    import soundfile as sf
    import torch
    output = output_dir / f"{lang}_voxcpm2.wav"
    torch.cuda.reset_peak_memory_stats(0)
    started = time.perf_counter()
    # No style prompt by default: text passed to both models is identical.
    audio = model.generate(text=text, cfg_value=2.0, inference_timesteps=10, seed=42)
    sf.write(str(output), audio, model.tts_model.sample_rate)
    del audio
    result = inspect_wav(output)
    result.update({
        "engine": "voxcpm2", "language": lang, "model": MODEL_ID,
        "generation_seconds": round(time.perf_counter() - started, 3),
        "peak_allocated_vram_gib": round(torch.cuda.max_memory_allocated(0) / 1024 ** 3, 2),
    })
    result["rtf"] = round(result["generation_seconds"] / result["seconds"], 3)
    return result


def write_review_csv(path: Path, rows: list) -> None:
    import csv
    cols = [
        "language", "engine", "audio_file", "pronunciation_1to5",
        "fluency_1to5", "naturalness_1to5", "pauses_1to5",
        "buddhist_terms_1to5", "audible_omissions_yes_no",
        "reviewer", "comments"
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        for row in rows:
            if row.get("status") == "ok":
                writer.writerow({
                    "language": row["language"],
                    "engine": row["engine"],
                    "audio_file": row["file"],
                })


def run(args) -> dict:
    payload = json.loads(args.samples.read_text(encoding="utf-8"))
    samples = validate_samples(payload)
    if args.dry_run:
        return {
            "mode": "validation_only",
            "languages": {lang: len(text) for lang, text in samples.items()},
            "production_modified": False,
        }
    if args.edge_only and args.vox_only:
        raise ValueError("--edge-only and --vox-only are incompatible")
    need_vox = not args.edge_only
    environment = preflight(voxel=need_vox)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    model = None
    if need_vox:
        model = load_voxcpm()
    for language, text in samples.items():
        for engine in ("edge", "voxcpm2"):
            if engine == "edge" and args.vox_only:
                continue
            if engine == "voxcpm2" and args.edge_only:
                continue
            try:
                print(f"[SoulKey A/B] {language} {engine}: synthesizing", flush=True)
                if engine == "edge":
                    record = asyncio.run(generate_edge(language, text, args.output_dir))
                else:
                    record = generate_voxcpm(model, language, text, args.output_dir)
                rows.append({"status": "ok", **record})
                print(f"  OK {record['seconds']}s, RTF={record['rtf']}", flush=True)
            except Exception as exc:
                print(f"  FAILED ({type(exc).__name__}): {exc}", flush=True)
                rows.append({
                    "language": language, "engine": engine, "status": "failed",
                    "error_type": type(exc).__name__, "error": str(exc)[:500],
                })
    report = {
        "experiment": "SoulKey V1 Five-Language Voice A/B",
        "model_id": MODEL_ID,
        "source_label": payload.get("source", "unknown"),
        "human_pronunciation_checked": False,
        "automatic_winner_selected": False,
        "production_modified": False,
        "environment": environment,
        "results": rows,
    }
    target = args.output_dir / "ab_report.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_review_csv(args.output_dir / "human_review.csv", rows)
    return report


def cli(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--edge-only", action="store_true")
    parser.add_argument("--vox-only", action="store_true")
    return parser.parse_args(argv)


if __name__ == "__main__":
    opts = cli()
    output = run(opts)
    if opts.dry_run:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        failed = [r for r in output["results"] if r.get("status") != "ok"]
        print("Report: " + str(opts.output_dir / "ab_report.json"), flush=True)
        if failed:
            sys.exit(2)
