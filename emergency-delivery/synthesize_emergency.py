#!/usr/bin/env python3
"""One-time emergency TTS from 2026-10-31 four draft manuscripts.
Never writes the source Drive or central QA and never marks a QA pass.
This script is for generating full-length review MP3s in GitHub Actions.
"""
from __future__ import annotations
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'translation-system'))
from natural_tts_config import NATURAL_TTS_PROFILES
from natural_tts_edge import synthesize_block, _ffprobe_duration
from natural_tts_planner import SpeechBlock

def safe_chunks(source: str, maximum: int):
    txt=" ".join(str(source or "").strip().split())
    output=[]
    # Prefer complete sentences, but never lose characters from a long paragraph.
    while txt:
        if len(txt)<=maximum:
            output.append(txt)
            break
        cut=maximum
        # Keep words together and prefer nearby sentence breaks.
        window=txt[max(0,maximum-100):maximum+1]
        punct=[m.end() for m in re.finditer(r"[.!?。！？។؛;،]",window)]
        if punct:
            cut=maximum-100+punct[-1]
        else:
            space=txt.rfind(" ",max(0,maximum-65),maximum+1)
            if space>maximum*.55:cut=space
        part=txt[:cut].strip()
        if not part:
            raise RuntimeError("empty speech chunk")
        output.append(part)
        txt=txt[cut:].strip()
    return output

def duration(path):
    return round(_ffprobe_duration(path),2)

async def synthesize_all(blocks, language, basedir):
    profile=NATURAL_TTS_PROFILES[language]
    sem=asyncio.Semaphore(3)
    async def one(block):
        async with sem:
            p=basedir/'parts'/f"{block.index:04d}.mp3"
            b=basedir/'parts'/f"{block.index:04d}.boundaries.jsonl"
            result=await synthesize_block(block,voice=profile['voice'],rate=profile['rate'],pitch=profile['pitch'],output_mp3=p,boundary_path=b,attempts=5)
            if not p.is_file() or p.stat().st_size<100:
                raise RuntimeError("invalid block audio "+str(block.index))
            print("TTS_SEG_OK",language,block.index,len(blocks),round(result['duration'],1),flush=True)
            return result
    return await asyncio.gather(*(one(b) for b in blocks))

async def main():
    lang=sys.argv[1];lesson=sys.argv[2]
    src=ROOT/'emergency-delivery'/lesson/(lang+'.json')
    data=json.loads(src.read_text('utf-8'))
    if data['language']!=lang or data['task_id']!=lesson:
        raise RuntimeError("task/language mismatch")
    segments=data['segments']
    if len(segments)!=(59 if lesson=='P259-L01' else 67):
        raise RuntimeError("wrong source segment count")
    assert all(x.get('text') and float(x['end'])>float(x['start']) for x in segments)
    profile=NATURAL_TTS_PROFILES[lang]
    chunks=[]
    for seg in segments:
        for piece in safe_chunks(seg['text'],280 if lang=='km' else 340):
            if piece:
                chunks.append(SpeechBlock(index=len(chunks)+1,segment_ids=[int(seg['id'])],source_start=float(seg['start']),source_end=float(seg['end']),text=piece,text_sha256=hashlib.sha256(piece.encode()).hexdigest()))
    output=ROOT/'emergency-delivery'/'outputs'/lesson/lang
    output.mkdir(parents=True,exist_ok=True)
    print("TTS_START",lesson,lang,"source_segments",len(segments),"audio_blocks",len(chunks),"voice",profile['voice'],flush=True)
    started=time.monotonic()
    results=await synthesize_all(chunks,lang,output)
    final=output/data['canonical_mp3']
    listing=output/'concat.txt'
    listing.write_text("".join("file '"+str((output/'parts'/f"{i:04d}.mp3").resolve())+"'\n" for i in range(1,len(chunks)+1)),encoding='utf-8')
    cmd=["ffmpeg","-y","-hide_banner","-loglevel","error","-f","concat","-safe","0","-i",str(listing),"-c:a","libmp3lame","-b:a","128k",str(final)]
    subprocess.run(cmd,check=True)
    d=duration(final)
    original=round(float(segments[-1]['end']),2)
    if final.stat().st_size<100000 or d<original*.40:
        raise RuntimeError(f"audio unexpectedly incomplete {d} vs {original}")
    metadata={"task_id":lesson,"language":lang,"engine":"edge_tts_7.2.8_emergency","source":"2026-10-31_emergency_draft_not_qa_approved","review_status":"needs_review","voice":profile['voice'],"source_segment_count":len(segments),"synthesized_block_count":len(chunks),"synthesized_block_ok_count":len(results),"source_max_end_seconds":original,"full_audio_duration_seconds":d,"duration_ratio":round(d/original,3),"duration_fit_status":"needs_review" if abs(d-original)>original*.04 else "near_source","mp3_sha256":hashlib.sha256(final.read_bytes()).hexdigest(),"mp3_bytes":final.stat().st_size,"canonical_name":data['canonical_mp3'],"target_folder_id":data['drive_folder_id'],"created_for":"urgent user handoff; do not mark central QA passed"}
    manifest=output/data['canonical_manifest']
    manifest.write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8")
    print("TTS_COMPLETED",lesson,lang,"seconds",d,"original",original,"blocks",len(results),"bytes",final.stat().st_size,"elapsed_seconds",round(time.monotonic()-started,1),flush=True)

if __name__=="__main__":
    asyncio.run(main())
