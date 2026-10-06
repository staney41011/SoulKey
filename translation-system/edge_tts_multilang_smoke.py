import argparse
import asyncio
import json
from pathlib import Path

import edge_tts


async def synthesize_one(lang, cfg, outdir):
    name = f"P256-L01_{lang}_{cfg['name']}_EdgeNatural"
    mp3 = outdir / f"{name}.mp3"
    boundary = outdir / f"{name}.boundaries.jsonl"
    communicate = edge_tts.Communicate(
        text=cfg["text"],
        voice=cfg["voice"],
        rate=cfg.get("rate", "-3%"),
        pitch=cfg.get("pitch", "-1Hz"),
        boundary="SentenceBoundary",
    )
    await communicate.save(str(mp3), str(boundary))
    return {
        "language": lang,
        "language_name": cfg["name"],
        "voice": cfg["voice"],
        "rate": cfg.get("rate"),
        "pitch": cfg.get("pitch"),
        "native_voice": bool(cfg.get("native_voice", True)),
        "note": cfg.get("note", ""),
        "characters": len(cfg["text"]),
        "audio_file": mp3.name,
        "boundary_file": boundary.name,
    }


async def main_async(args):
    fixture = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    results = []
    for lang, cfg in fixture["languages"].items():
        print(f"[TTS:{lang}] voice={cfg['voice']} chars={len(cfg['text'])}", flush=True)
        result = await synthesize_one(lang, cfg, outdir)
        results.append(result)
        print(f"✅ {result['audio_file']}", flush=True)

    manifest = {
        "task_id": fixture.get("task_id"),
        "sample": fixture.get("sample"),
        "engine": "edge-tts",
        "edge_tts_version": getattr(edge_tts, "__version__", "unknown"),
        "languages": results,
    }
    (outdir / "P256-L01_EdgeNatural_Multilang_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
