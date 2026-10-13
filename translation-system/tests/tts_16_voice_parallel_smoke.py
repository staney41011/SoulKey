"""16-voice, two-block live smoke for the production parallel renderer.

Uses synthetic educational phrases, never actual lesson transcripts or Drive.
"""
import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from natural_tts_edge import render_blocks, _ffprobe_duration
from natural_tts_config import NATURAL_TTS_PROFILES
from natural_tts_planner import SpeechBlock
from tts_health_audit import SAMPLES


def blocks(lang):
    phrase = SAMPLES[lang]
    strings = [phrase, phrase]
    return [
        SpeechBlock(index=i+1, segment_ids=[i+1], source_start=i*5,
                    source_end=(i+1)*5, text=text,
                    text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest())
        for i, text in enumerate(strings)
    ]


async def main(out):
    root = Path(out)
    root.mkdir(parents=True, exist_ok=True)
    os.environ["SOULKEY_TTS_PARALLEL_BLOCKS"] = "2"
    report = {"source": "synthetic 16-voice Edge TTS integration", "languages": []}
    try:
        for lang in NATURAL_TTS_PROFILES:
            dest = root / lang
            data = blocks(lang)
            meta, wavs = await render_blocks(lang=lang,blocks=data,output_dir=dest)
            assert len(meta)==2 and len(wavs)==2, lang
            assert [m["block_index"] for m in meta] == [1,2], lang
            assert all(_ffprobe_duration(dest/"blocks"/f"{i:04d}.mp3")>0.5
                       for i in (1,2)),lang
            second, _ = await render_blocks(lang=lang,blocks=data,output_dir=dest)
            assert all(x["reused"] for x in second), lang
            report["languages"].append({"lang":lang, "ok":True, "reused":2})
            print("VOICE_PILOT_OK",lang,flush=True)
        report["passed"] = True
    except Exception as exc:
        report["passed"] = False
        report["failure"] = type(exc).__name__+": "+str(exc).split("url=")[0][:160]
        print("VOICE_PILOT_ERROR",report["failure"],flush=True)
    finally:
        (root/"voice-report.json").write_text(
            json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8"
        )
        print("VOICE_PILOT_SUMMARY",len(report["languages"]),"/16",flush=True)
    if not report["passed"]:
        raise SystemExit(1)


if __name__=="__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out",required=True)
    args=parser.parse_args()
    asyncio.run(main(args.out))
