"""One-off CPU Edge TTS recovery from already-published P256-L01 translations.

Reads only the public link-enabled existing Drive JSON files. Never modifies
English Final or translation content. Publishes audio via GitHub Actions
artifacts; Google Drive upload is deliberately not performed without OAuth.
"""
import argparse
import asyncio
import json
from pathlib import Path

import gdown

from natural_tts_config import (
    NATURAL_TTS_PROFILES,
    NATURAL_TTS_PROFILE_REVISION,
    EDGE_TTS_VERSION,
)
from natural_tts_planner import build_speech_blocks
from natural_tts_edge import render_blocks
from natural_tts_assemble import (
    assemble_preview,
    assemble_continuous_with_limit,
    wav_to_mp3,
    write_alignment_report,
)
from tts_engine import segments_fingerprint

DRIVE_SOURCE_IDS = {
    "en": "1EHj_C2uNdDo_Not_Use_Unverified",  # set in main via verified CLI
    "hi": "1qiB9qXrVavE_dQs2aZiSBtEJVVY9mg8P",
    "ta": "19Cdzo6tUIiKwP27eVlQisd6ozXVHoiDK",
    "source": "1zAFO_3LwsZQPjd7gnYX3L72o-h7BXsx5",
}


def get_json(file_id: str, target: Path):
    for trial in range(1, 4):
        try:
            result = gdown.download(
                id=file_id, output=str(target), quiet=True, fuzzy=True,
                use_cookies=False
            )
            if not result or not target.is_file():
                raise RuntimeError("Drive returned no file")
            raw = target.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("Unexpected JSON payload type")
            return data
        except Exception as exc:
            if trial == 3:
                raise RuntimeError(
                    f"Failed to read Google Drive JSON, id={file_id}: {exc}"
                ) from exc
            print(f"[FETCH] retry {trial}/3, error={type(exc).__name__}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", required=True, choices=["hi", "ta"])
    parser.add_argument("--english-id", required=True)
    parser.add_argument("--output-dir", default="repaired-audio")
    args = parser.parse_args()

    outdir = Path(args.output_dir) / args.lang
    outdir.mkdir(parents=True, exist_ok=True)

    english = get_json(args.english_id, outdir / "en.final.json")
    en_segments = english.get("segments") or []
    if not en_segments:
        raise RuntimeError("English Final has no segments")

    current_sha = segments_fingerprint(en_segments)
    translated = get_json(DRIVE_SOURCE_IDS[args.lang], outdir / f"{args.lang}.json")
    declared = str(translated.get("source_sha256") or "").strip()
    declared_source = str(translated.get("source") or "").strip()
    print(f"[REVISION] {args.lang} translation={declared[:12]} current_en={current_sha[:12]}", flush=True)
    if declared_source != "en.final.json" or declared != current_sha:
        raise RuntimeError(
            "Current English Final and translation revision do not match; "
            "refusing to synthesize obsolete content."
        )

    segments = translated.get("segments") or []
    if not segments:
        raise RuntimeError("Translation has no segments")
    source = get_json(DRIVE_SOURCE_IDS["source"], outdir / "source_info.json")
    duration = float(source.get("duration") or 1915)
    if duration <= 0:
        raise RuntimeError("Source duration unavailable")

    blocks, overlap_report = build_speech_blocks(segments, args.lang)
    print(f"[TTS] lang={args.lang} segments={len(segments)} blocks={len(blocks)} duration_limit={duration}", flush=True)
    block_results, wav_parts = asyncio.run(
        render_blocks(lang=args.lang, blocks=blocks, output_dir=outdir)
    )
    preview_wav = outdir / f"{args.lang}.preview.wav"
    preview_mp3 = outdir / f"{args.lang}.preview.mp3"
    preview = assemble_preview(wav_parts, preview_wav)
    wav_to_mp3(preview_wav, preview_mp3)

    final_wav = outdir / f"{args.lang}.wav"
    final_mp3 = outdir / f"{args.lang}.mp3"
    timeline = assemble_continuous_with_limit(
        preview_wav, final_wav, source_duration=duration
    )
    wav_to_mp3(final_wav, final_mp3)
    report = outdir / f"{args.lang}.alignment_report.json"
    write_alignment_report(report, preview=preview, timeline=timeline)

    profile = NATURAL_TTS_PROFILES[args.lang]
    status = "needs_review" if timeline["needs_review"] else "done"
    manifest = {
        "version": 2,
        "engine": "edge-natural-v2",
        "edge_tts_version": EDGE_TTS_VERSION,
        "profile_revision": NATURAL_TTS_PROFILE_REVISION,
        "language": args.lang,
        "voice": profile["voice"],
        "rate": profile["rate"],
        "pitch": profile["pitch"],
        "source_sha256": segments_fingerprint(segments),
        "en_source_sha256": current_sha,
        "source_segment_count": len(segments),
        "block_count": len(blocks),
        "assembly_policy": "continuous_total_duration",
        "duration_limit_basis": "source_info.duration",
        "duration_limit_seconds": round(duration, 3),
        "overlap_cleanup": overlap_report,
        "blocks": block_results,
        "preview": preview,
        "timeline": timeline,
        "status": status,
    }
    manifest_path = outdir / f"{args.lang}.tts_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"[RESULT] {args.lang} status={status} final_seconds={timeline['final_duration']} "
        f"preview_mp3={preview_mp3.stat().st_size} canonical_mp3={final_mp3.stat().st_size}",
        flush=True,
    )
    # Avoid publishing segment text, source JSON, and intermediate WAVs
    # through the Actions artifact. Only the final audio/QA artifacts ship.
    delivered = Path(args.output_dir) / "deliver"
    delivered.mkdir(parents=True, exist_ok=True)
    import shutil
    for p in [preview_mp3, final_mp3, report, manifest_path]:
        shutil.copy2(p, delivered / p.name)


if __name__ == "__main__":
    main()
