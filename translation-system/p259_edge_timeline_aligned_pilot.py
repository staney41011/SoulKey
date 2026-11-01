#!/usr/bin/env python3
"""Isolated P259 L04 Vietnamese timeline-aligned Edge TTS pilot.

Reads current English Final and Gemma AI-QA translation from Drive.
Does not call Gemini, GCP, or overwrite Drive/main. Artifact is NOT human-approved.
"""
import asyncio
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import edge_tts
import gdown

sys.path.insert(0, "translation-system")
from p259_edge_audio_from_drive import VOICE, split_text  # applies tested Edge WS endpoint

ENGLISH_ID = "1WVvcJ0HbSKlwRuSCpCQtjbyq9-_7IPuF"
TRANSLATION_ID = "1LqkJ8dBdhxO5g-3lYHvOnSw2oFxP6exB"
MAX_TEMPO = 1.40
OUT = Path("p259-aligned-pilot")
OUT.mkdir(exist_ok=True)


def command(args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL)


def duration(path):
    return float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        text=True).strip())


def fingerprint(segments):
    rows = [{"id": int(s["id"]), "start": float(s["start"]),
             "end": float(s["end"]), "text": str(s["text"])} for s in segments]
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":")).encode()).hexdigest()


def read_drive(file_id, path):
    if not gdown.download(id=file_id, output=str(path), quiet=True):
        raise RuntimeError("DRIVE_READ_FAILED")
    return json.loads(path.read_text(encoding="utf-8"))


async def make_speech(i, segment, semaphore):
    folder = OUT / "parts" / f"{i:03d}"
    folder.mkdir(parents=True, exist_ok=True)
    pieces = split_text(segment["text"], 370)
    for j, piece in enumerate(pieces):
        path = folder / f"{j:03d}.mp3"
        for attempt in range(2):
            try:
                async with semaphore:
                    await asyncio.wait_for(
                        edge_tts.Communicate(text=piece, voice=VOICE["vi"],
                                             rate="-3%", pitch="-1Hz").save(str(path)),
                        timeout=120)
                if path.stat().st_size < 100:
                    raise ValueError("EMPTY_TTS_PART")
                break
            except Exception:
                if attempt == 1:
                    raise
                await asyncio.sleep(4)
    paths = [folder / f"{j:03d}.mp3" for j in range(len(pieces))]
    concat = folder / "concat.txt"
    concat.write_text("".join("file '" + p.resolve().as_posix() + "'\n" for p in paths))
    speech = folder / "speech.mp3"
    command(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat",
             "-safe", "0", "-i", str(concat), "-c:a", "libmp3lame", "-b:a", "128k",
             str(speech)])
    return speech


def write_silence(path, seconds):
    command(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
             "-i", "anullsrc=r=16000:cl=mono", "-t", f"{seconds:.6f}",
             "-c:a", "pcm_s16le", str(path)])


async def main():
    report = {"task_id": "P259-L04", "language": "vi",
              "status": "pilot_pending", "human_qa": False,
              "max_tempo": MAX_TEMPO, "segments": []}
    receipt = OUT / "timeline_qa.json"
    try:
        english = read_drive(ENGLISH_ID, OUT / "english.json")
        translated = read_drive(TRANSLATION_ID, OUT / "translated.json")
        es = english["segments"]
        ts = translated["segments"]
        sha = fingerprint(es)
        if sha != english["source_sha256"] or sha != translated["source_sha256"]:
            raise ValueError("SOURCE_SHA256_MISMATCH")
        if translated["task_id"] != "P259-L04" or translated["language"] != "vi":
            raise ValueError("WRONG_TRANSLATION")
        if translated.get("qa_status") != "AI_QA_PASS_NOT_HUMAN_REVIEWED":
            raise ValueError("TRANSLATION_QA_NOT_PASS")
        if len(es) != len(ts) or [int(x["id"]) for x in es] != [int(x["id"]) for x in ts]:
            raise ValueError("SEGMENT_ID_MISMATCH")
        last = 0.0
        for e, t in zip(es, ts):
            if (float(t["start"]) != float(e["start"]) or
                float(t["end"]) != float(e["end"]) or
                not t["text"].strip() or float(t["start"]) < last - 0.001 or
                float(t["end"]) <= float(t["start"])):
                raise ValueError("SEGMENT_TIMELINE_OR_CONTENT_MISMATCH")
            last = float(t["end"])
        report["source_sha256"] = sha
        report["source_segments"] = len(ts)
        report["target_seconds"] = last
        sem = asyncio.Semaphore(2)
        speeches = await asyncio.gather(*(make_speech(i, seg, sem)
                                          for i, seg in enumerate(ts)))
        timeline = []
        cursor = 0.0
        overruns = []
        for i, (seg, speech) in enumerate(zip(ts, speeches)):
            start, end = float(seg["start"]), float(seg["end"])
            slot = end - start
            raw = duration(speech)
            tempo = max(1.0, raw / max(0.1, slot - 0.20))
            item = {"id": int(seg["id"]), "start": start, "end": end,
                    "slot_seconds": round(slot, 3), "speech_seconds": round(raw, 3),
                    "tempo_required": round(tempo, 4)}
            report["segments"].append(item)
            if tempo > MAX_TEMPO:
                overruns.append(item)
                continue
            if start > cursor + 0.001:
                gap = OUT / f"gap_{i:03d}.wav"
                write_silence(gap, start - cursor)
                timeline.append(gap)
            aligned = OUT / f"aligned_{i:03d}.wav"
            command(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                     "-i", str(speech),
                     "-af", f"atempo={tempo:.6f},apad,atrim=duration={slot:.6f},asetpts=PTS-STARTPTS",
                     "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(aligned)])
            timeline.append(aligned)
            cursor = end
        # A duration match alone can hide excessive inserted silence.
        # This is an estimated QA metric, not proof of perceptual quality.
        rendered_speech = sum(
            min(x["slot_seconds"], x["speech_seconds"] / x["tempo_required"])
            for x in report["segments"]
        )
        slot_total = sum(x["slot_seconds"] for x in report["segments"])
        gap_total = max(0.0, last - slot_total)
        silence_total = max(0.0, last - rendered_speech)
        max_padding = max(
            (max(0.0, x["slot_seconds"] - x["speech_seconds"] / x["tempo_required"])
             for x in report["segments"]), default=0.0
        )
        report["estimated_rendered_speech_seconds"] = round(rendered_speech, 3)
        report["estimated_silence_seconds"] = round(silence_total, 3)
        report["estimated_silence_ratio"] = round(silence_total / last, 4) if last else 0.0
        report["estimated_intersegment_gap_seconds"] = round(gap_total, 3)
        report["max_segment_padding_seconds"] = round(max_padding, 3)
        report["qa_warnings"] = []
        if report["estimated_silence_ratio"] > 0.20:
            report["qa_warnings"].append("HIGH_ESTIMATED_SILENCE_RATIO_GT_20_PERCENT")
        if max_padding > 12.0:
            report["qa_warnings"].append("LONG_SINGLE_SEGMENT_PADDING_GT_12_SECONDS")
        report["overrun_segments"] = overruns
        if overruns:
            report["status"] = "blocked_speech_exceeds_slot_speed_cap"
            raise RuntimeError(f"{len(overruns)} SEGMENTS REQUIRE TEMPO ABOVE {MAX_TEMPO}")
        concat = OUT / "aligned_concat.txt"
        concat.write_text("".join("file '" + p.resolve().as_posix() + "'\n"
                                  for p in timeline))
        mp3 = OUT / "L04_vi_timeline_aligned_AI_QA_ONLY.mp3"
        command(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f",
                 "concat", "-safe", "0", "-i", str(concat),
                 "-c:a", "libmp3lame", "-b:a", "128k", str(mp3)])
        sec = duration(mp3)
        report["audio_seconds"] = round(sec, 3)
        report["audio_bytes"] = mp3.stat().st_size
        report["audio_sha256"] = hashlib.sha256(mp3.read_bytes()).hexdigest()
        if abs(sec - last) > 1.0 or mp3.stat().st_size < 100000:
            raise ValueError("FINAL_AUDIO_DURATION_OR_SIZE_MISMATCH")
        report["status"] = ("mechanical_timeline_pass_silence_review_required"
                            if report["qa_warnings"] else
                            "mechanical_timeline_pass_human_review_required")
        print("PILOT_MECHANICAL_PASS", len(ts), sec, flush=True)
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        if report["status"] == "pilot_pending":
            report["status"] = "failed"
        raise
    finally:
        receipt.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                           encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
