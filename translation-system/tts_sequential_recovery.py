"""P256 lesson TTS recovery from existing, revision-verified Drive translations.

Run by a one-time GitHub Actions chain: L02 -> L03 -> L04.
No ASR, translation, English Final edits, or unauthenticated Drive writes.
Audio and QA artifacts are retained for Drive import after verification.
"""
import argparse
import asyncio
import json
import shutil
from pathlib import Path

from tts_public_drive_repair import get_json, segments_fingerprint
from natural_tts_config import (
    EDGE_TTS_VERSION, NATURAL_TTS_PROFILES, NATURAL_TTS_PROFILE_REVISION,
)
from natural_tts_planner import build_speech_blocks
from natural_tts_edge import render_blocks
from natural_tts_assemble import (
    assemble_preview, assemble_continuous_with_limit,
    wav_to_mp3, write_alignment_report,
)

# Verified existing Drive IDs in SoulKey / 第256期.
DRIVE_INPUTS = {
    "P256-L02": {
        "en": "15H1GrvekIYZ0WpmPb-3q3-MOMXwD_lNE",
        "th": "1bQhBvoGd0B9ovHFfB31ZvlByJVD2gLxY",
        "es": "1A_m3cGm8p1aJPBApTSMTWnjr78jHReaQ",
        "id": "1y-h6fU9VDYd-Ck4C-AOahow9bd_KVRaP",
        "vi": "1MByGfepkgq3LijPHvn2SUkwZJnNAki9M",
        "hi": "1QnRzfCe5-m2EcbErxMg6n9dmrPCdVklJ",
        "ta": "13YHFKMQ6XZiRPVAH70p5sYWh-NnOnhEe",
        "source": "1pu4DEvbpMkBBCAKosdlWlWr6kw3dbWIo",
    },
    "P256-L03": {
        "en": "1KSOmT9jbJq_6LllsNtthvDGfv4-27dIL",
        "th": "1h5jc72T6tYTv7nneKEcjn1k-NRqNqQZx",
        "es": "14Y8BilNGLUzFigcl66mAgtEuRqV-DbG8",
        "id": "1Zr_MvTsbryLuS7Ghfvhsp0qFk5kESemd",
        "vi": "1fgbsGQBkn8Ny4CRsO_jSAHkbvU1eQw4O",
        "hi": "1_kXfEpQIdHsOt8hpqT33M8TMOmvRceH4",
        "ta": "1c_94asTGFg-cVdiQKeC9MujOgVeeClF9",
        "source": "1XoS294NaM4pcCH520XtUzKw8Qo1-_xfZ",
    },
    "P256-L04": {
        "en": "1G5TmB9repHMQcuqy_qUEW8iHIqAI6ARB",
        "th": "11yUavGMpJmnXh24A-iMFZwKWR9fY1hTp",
        "es": "1VaAlt9Kh_KnsoMp3nyIfWjU5ZXpaeLPd",
        "id": "1B77tjPjXL5LxsZFrAcsHyNeijKnbGyUv",
        "vi": "1eiOC0iNAPkwpav-dn35KkiJSiJP8INTL",
        "hi": "14Rdo9TS8LSGPsdonOX97_-ae2JkD252x",
        "ta": "1RIGIRYwNAWtmAyO8Ek42UXHJTnepB4YW",
        "source": "1gKf0vylE3FoMvzh3DqJ0S8wngmZDewcM",
    },
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True, choices=sorted(DRIVE_INPUTS))
    parser.add_argument("--lang", required=True, choices=list(NATURAL_TTS_PROFILES))
    parser.add_argument("--output-dir", default="tts-sequence-output")
    args = parser.parse_args()

    sources = DRIVE_INPUTS[args.task_id]
    lang = args.lang
    output_root = Path(args.output_dir)
    work = output_root / "work" / args.task_id / lang
    work.mkdir(parents=True, exist_ok=True)

    en = get_json(sources["en"], work / "en.final.json")
    en_segments = en.get("segments") or []
    if not en_segments:
        raise RuntimeError("English Final missing segments")
    english_revision = segments_fingerprint(en_segments)

    if lang == "en":
        segments = en_segments
    else:
        translation = get_json(sources[lang], work / f"{lang}.json")
        if translation.get("source") != "en.final.json":
            raise RuntimeError(f"{args.task_id}/{lang}: wrong source (not en.final.json)")
        if translation.get("source_sha256") != english_revision:
            raise RuntimeError(
                f"{args.task_id}/{lang}: stale translation, "
                f"translated={str(translation.get('source_sha256') or '')[:12]} "
                f"current={english_revision[:12]}"
            )
        segments = translation.get("segments") or []

    if not segments:
        raise RuntimeError(f"{args.task_id}/{lang}: no translated segments")

    source_info = get_json(sources["source"], work / "source_info.json")
    duration = float(source_info.get("duration") or 0)
    if duration <= 0:
        raise RuntimeError(f"{args.task_id}: original video duration unavailable")

    blocks, overlap_report = build_speech_blocks(segments, lang)
    if not blocks:
        raise RuntimeError(f"{args.task_id}/{lang}: no speech blocks")
    print(
        f"[PREFLIGHT] task={args.task_id} lang={lang} en_rev={english_revision[:12]} "
        f"segments={len(segments)} blocks={len(blocks)} duration_limit={duration:.2f}s",
        flush=True,
    )

    rendered, wav_parts = asyncio.run(
        render_blocks(lang=lang, blocks=blocks, output_dir=work)
    )
    natural_wav = work / f"{lang}.preview.wav"
    natural_mp3 = work / f"{lang}.preview.mp3"
    preview = assemble_preview(wav_parts, natural_wav)
    wav_to_mp3(natural_wav, natural_mp3)

    final_wav = work / f"{lang}.wav"
    final_mp3 = work / f"{lang}.mp3"
    timeline = assemble_continuous_with_limit(
        natural_wav, final_wav, source_duration=duration
    )
    if not timeline["needs_review"]:
        wav_to_mp3(final_wav, final_mp3)

    status = "needs_review" if timeline["needs_review"] else "done"
    report = work / f"{lang}.alignment_report.json"
    write_alignment_report(report, preview=preview, timeline=timeline)

    profile = NATURAL_TTS_PROFILES[lang]
    manifest = {
        "version": 2,
        "task_id": args.task_id,
        "engine": "edge-natural-v2",
        "edge_tts_version": EDGE_TTS_VERSION,
        "profile_revision": NATURAL_TTS_PROFILE_REVISION,
        "language": lang,
        "voice": profile["voice"],
        "rate": profile["rate"],
        "pitch": profile["pitch"],
        "source_sha256": segments_fingerprint(segments),
        "en_source_sha256": english_revision,
        "source_segment_count": len(segments),
        "block_count": len(blocks),
        "assembly_policy": "continuous_total_duration",
        "duration_limit_basis": "source_info.duration",
        "duration_limit_seconds": round(duration, 3),
        "overlap_cleanup": overlap_report,
        "blocks": rendered,
        "preview": preview,
        "timeline": timeline,
        "status": status,
    }
    manifest_path = work / f"{lang}.tts_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    delivery = output_root / "deliver"
    delivery.mkdir(parents=True, exist_ok=True)
    for src in (natural_mp3, report, manifest_path):
        shutil.copy2(src, delivery / src.name)
    if status == "done":
        shutil.copy2(final_mp3, delivery / final_mp3.name)
    else:
        # Never publish overlong narration with the canonical filename.
        shutil.copy2(natural_mp3, delivery / f"{lang}.needs_review.mp3")

    print(
        f"[RESULT] {args.task_id}/{lang}={status} "
        f"natural={timeline['natural_duration']:.1f}s "
        f"limit={duration:.1f}s speedup_required={timeline['required_speedup']:.3f}x "
        f"published={','.join(sorted(p.name for p in delivery.iterdir()))}",
        flush=True,
    )


if __name__ == "__main__":
    main()
