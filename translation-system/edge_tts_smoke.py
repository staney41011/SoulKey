import argparse
import asyncio
import json
from pathlib import Path

import edge_tts


DEFAULT_VOICE = "en-US-AndrewMultilingualNeural"
DEFAULT_RATE = "-4%"
DEFAULT_PITCH = "-2Hz"


async def synthesize(text: str, output_mp3: Path, output_meta: Path, voice: str, rate: str, pitch: str):
    output_mp3.parent.mkdir(parents=True, exist_ok=True)
    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
        pitch=pitch,
        boundary="SentenceBoundary",
    )
    await communicate.save(str(output_mp3), str(output_meta))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--text-file", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--name", default="256_L01_English_Kaggle_Edge_Natural_v1")
    parser.add_argument("--voice", default=DEFAULT_VOICE)
    parser.add_argument("--rate", default=DEFAULT_RATE)
    parser.add_argument("--pitch", default=DEFAULT_PITCH)
    args = parser.parse_args()

    text_path = Path(args.text_file)
    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    text = text_path.read_text(encoding="utf-8").strip()
    if not text:
        raise RuntimeError("TTS sample text is empty")

    mp3_path = outdir / f"{args.name}.mp3"
    meta_path = outdir / f"{args.name}.boundaries.jsonl"
    manifest_path = outdir / f"{args.name}.manifest.json"

    print("=" * 72, flush=True)
    print("SoulKey Edge Natural TTS | Kaggle smoke test", flush=True)
    print(f"voice={args.voice} rate={args.rate} pitch={args.pitch}", flush=True)
    print(f"characters={len(text)}", flush=True)
    print("=" * 72, flush=True)

    asyncio.run(
        synthesize(
            text=text,
            output_mp3=mp3_path,
            output_meta=meta_path,
            voice=args.voice,
            rate=args.rate,
            pitch=args.pitch,
        )
    )

    manifest = {
        "engine": "edge-tts",
        "voice": args.voice,
        "rate": args.rate,
        "pitch": args.pitch,
        "characters": len(text),
        "source_file": text_path.name,
        "audio_file": mp3_path.name,
        "boundary_file": meta_path.name,
        "purpose": "Kaggle-only naturalness smoke test; does not replace production TTS.",
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"✅ audio={mp3_path}", flush=True)
    print(f"✅ manifest={manifest_path}", flush=True)


if __name__ == "__main__":
    main()
