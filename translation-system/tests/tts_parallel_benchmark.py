"""Isolated concurrency benchmark for SoulKey P257-L01 English TTS.

No Google Drive, Sheets, workflow status, or production audio is accessed.
Produces only scratch MP3 files and JSON statistics.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

import edge_tts
from mutagen.mp3 import MP3

# Short representative human-approved excerpts from P257-L01 English Final.
SAMPLES = [
    "Dear family, peace be with you all. Hello everyone, we meet again for our weekly Open Your Heart session.",
    "Recently, we have been discussing the theme of body, mind, and spirit environmental protection. What is environmental protection? In everything we do, we must have a sense of order.",
    "We must exercise restraint and moderation, taking things at the right time and using them in measure, leaving room for everything. If we do not leave any room, our human minds will always want more.",
    "Sometimes in life, there is an indescribable bitterness, because happiness is only fleeting. But the price you have to pay for it is also very deep.",
    "Today, we continue to discuss this topic of body, mind, and spirit environmental protection. Last time, we talked about how desires expand. Then our mindset loses its balance.",
    "If you drink strong alcohol on top of that, the burden becomes even greater. As much as possible, if you can avoid drinking, do not drink. First, drinking and driving is very dangerous.",
]

VOICE = "en-US-AndrewMultilingualNeural"
RATE = "-4%"
PITCH = "-2Hz"


def select_endpoint(choice: str) -> None:
    if choice == "alternate":
        from edge_tts import communicate
        from edge_tts.constants import TRUSTED_CLIENT_TOKEN
        communicate.WSS_URL = (
            "wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1"
            "?Ocp-Apim-Subscription-Key=" + TRUSTED_CLIENT_TOKEN
        )


def public_error(exc: BaseException) -> str:
    # Avoid logging request URLs, access tokens, or user credentials.
    message = str(exc).split("url=")[0].split("wss://")[0].strip()
    return (type(exc).__name__ + ": " + message)[:180]


def permission_error(exc: BaseException) -> bool:
    msg = str(exc)
    return any(s in msg for s in ("403", "401", "429"))


async def synthesize(text: str, filename: Path) -> dict:
    begun = time.monotonic()
    try:
        await asyncio.wait_for(
            edge_tts.Communicate(
                text=text, voice=VOICE, rate=RATE, pitch=PITCH,
                boundary="SentenceBoundary",
            ).save(str(filename)), timeout=45,
        )
        byte_size = filename.stat().st_size
        speech_seconds = float(MP3(str(filename)).info.length)
        if byte_size < 1024 or speech_seconds <= 0.5:
            raise RuntimeError("invalid or empty MP3")
        return {
            "ok": True, "duration_s": round(time.monotonic()-begun, 3),
            "speech_s": round(speech_seconds, 3), "bytes": byte_size,
        }
    except Exception as exc:
        filename.unlink(missing_ok=True)
        return {
            "ok": False, "duration_s": round(time.monotonic()-begun, 3),
            "error": public_error(exc), "blocked": permission_error(exc),
        }


async def group(limit: int, root: Path) -> dict:
    target = root / ("parallel_" + str(limit))
    target.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(limit)
    async def task(index: int, text: str) -> dict:
        async with semaphore:
            result = await synthesize(text, target / f"{index+1:03}.mp3")
            result["index"] = index + 1
            return result
    begun = time.monotonic()
    results = await asyncio.gather(*(task(i,text) for i,text in enumerate(SAMPLES)))
    valid = [x for x in results if x["ok"]]
    return {
        "workers": limit,
        "wall_s": round(time.monotonic()-begun, 3),
        "success": len(valid), "total": len(results),
        "speech_s": round(sum(x["speech_s"] for x in valid), 3),
        "mean_request_s": round(statistics.mean(x["duration_s"] for x in results), 3),
        "results": results,
    }


async def run(root: Path) -> dict:
    report = {
        "task_id": "P257-L01",
        "scope": "isolated English sample TTS only; never modifies production files",
        "blocks_per_trial": len(SAMPLES),
        "edge_tts_version": getattr(edge_tts, "__version__", "unknown"),
        "trials": [],
    }
    # Fail fast: do not send 18 more requests if the voice service is rejecting
    # this environment. A cold-service success alone is not a benchmark result.
    smoke = await synthesize(SAMPLES[0], root / "preflight.mp3")
    report["preflight"] = smoke
    print("PREFLIGHT " + json.dumps(smoke, ensure_ascii=False), flush=True)
    if not smoke["ok"]:
        report["blocked_reason"] = smoke["error"]
        return report
    for workers in (1,2,4):
        trial = await group(workers, root)
        report["trials"].append(trial)
        print("TRIAL " + json.dumps({k:v for k,v in trial.items() if k!="results"}),flush=True)
        # A failed or rejected request makes the speed comparison invalid.
        if trial["success"] != trial["total"]:
            report["blocked_reason"] = "incomplete synthesis at worker_count=" + str(workers)
            break
        await asyncio.sleep(3)
    if len(report["trials"]) == 3 and all(t["success"] == t["total"] for t in report["trials"]):
        baseline = report["trials"][0]["wall_s"]
        report["speedup_vs_1"] = {str(t["workers"]): round(baseline/t["wall_s"], 3) for t in report["trials"]}
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--endpoint", choices=("standard","alternate"), default="alternate")
    args = parser.parse_args()
    root = Path(args.out).resolve()
    root.mkdir(parents=True,exist_ok=True)
    select_endpoint(args.endpoint)
    report = asyncio.run(run(root))
    report["endpoint"] = args.endpoint
    (root / "report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print("BENCHMARK_REPORT " + json.dumps({k:v for k,v in report.items() if k!="trials"},ensure_ascii=False),flush=True)


if __name__ == "__main__":
    main()
