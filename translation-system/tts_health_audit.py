"""Live smoke test of all 16 SoulKey voice profiles.

Never writes to course folders or Google Drive. Test samples are synthetic.
Reports per-voice connection, MP3, duration and silence checks.
"""
import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from natural_tts_config import EDGE_TTS_VERSION, NATURAL_TTS_PROFILES

SAMPLES = {
  "en":"We are grateful to learn together and put kindness into practice.",
  "th":"ยินดีต้อนรับทุกท่าน ขอให้เราเรียนรู้และทำความดีร่วมกัน",
  "es":"Bienvenidos a todos. Aprendamos juntos y practiquemos la bondad.",
  "id":"Selamat datang semuanya. Mari belajar bersama dan berbuat baik.",
  "vi":"Chào mừng mọi người. Chúng ta hãy cùng học hỏi và làm điều tốt.",
  "hi":"आप सभी का स्वागत है। आइए मिलकर सीखें और अच्छे काम करें।",
  "ta":"அனைவரையும் வரவேற்கிறோம். நாம் ஒன்றாகக் கற்று நல்ல செயல்கள் செய்வோம்.",
  "ja":"皆さん、ようこそ。一緒に学び、思いやりを実践しましょう。",
  "ko":"모두 환영합니다. 함께 배우고 친절을 실천합시다.",
  "km":"សូមស្វាគមន៍អ្នកទាំងអស់គ្នា យើងសូមរៀនជាមួយគ្នា។",
  "bn":"আপনাদের সবাইকে স্বাগতম। আসুন আমরা একসাথে শিখি এবং ভালো কাজ করি।",
  "ne":"तपाईंहरू सबैलाई स्वागत छ। हामी सँगै सिकौँ र असल काम गरौँ।",
  "lo":"ຍິນດີຕ້ອນຮັບທຸກຄົນ ພວກເຮົາມາຮຽນຮູ້ນຳກັນ.",
  "my":"အားလုံးကို ကြိုဆိုပါတယ်။ အတူတူ သင်ယူကြပါစို့။",
  "it":"Benvenuti a tutti. Impariamo insieme e pratichiamo la gentilezza.",
  "pt":"Sejam todos bem-vindos. Vamos aprender juntos e praticar a bondade.",
}

def validate_mp3(path):
    if not path.exists() or path.stat().st_size < 1000:
        raise ValueError("Audio missing or too short")
    ffprobe=shutil.which("ffprobe")
    if not ffprobe:
        return {"size_bytes":path.stat().st_size,"duration_sec":None,"silence_check":"ffprobe_unavailable"}
    proc=subprocess.run([ffprobe,"-v","error","-show_entries","format=duration",
        "-of","default=nokey=1:noprint_wrappers=1",str(path)],
        capture_output=True,text=True,check=True,timeout=15)
    duration=float(proc.stdout.strip())
    if not (duration>0.35 and duration < 90):
        raise ValueError(f"Unexpected MP3 duration={duration}")
    meta={"size_bytes":path.stat().st_size,"duration_sec":round(duration,3)}
    ffmpeg=shutil.which("ffmpeg")
    if ffmpeg:
        p=subprocess.run([ffmpeg,"-hide_banner","-nostats","-i",str(path),
            "-af","volumedetect","-vn","-f","null","-"],
            capture_output=True,text=True,timeout=15)
        import re
        hit=re.search(r"max_volume:\s*(-?[\d.]+) dB",p.stderr)
        if hit:
            peak=float(hit.group(1))
            meta["peak_db"]=peak
            if peak<-65:raise ValueError(f"Silent audio peak {peak}dB")
    return meta

async def audit_one(code,output,timeout):
    import edge_tts
    profile=NATURAL_TTS_PROFILES[code]
    item={"code":code,"voice":profile["voice"],"status":"failed"}
    path=output/f"{code}.mp3"
    started=time.monotonic()
    try:
        await asyncio.wait_for(
            edge_tts.Communicate(text=SAMPLES[code],
                voice=profile["voice"],rate=profile["rate"],
                pitch=profile["pitch"],boundary="SentenceBoundary").save(str(path)),
            timeout=timeout)
        item.update(validate_mp3(path))
        item["status"]="ok"
    except Exception as e:
        item["error_type"]=type(e).__name__
        item["error"]=str(e).split("url=")[0].strip()[:180]
    item["elapsed_sec"]=round(time.monotonic()-started,2)
    print("VOICE_HEALTH",json.dumps(item,ensure_ascii=False),flush=True)
    return item

async def main():
    p=argparse.ArgumentParser()
    p.add_argument("--output-dir",required=True)
    p.add_argument("--langs",default=",".join(NATURAL_TTS_PROFILES))
    p.add_argument("--timeout",type=int,default=22)
    a=p.parse_args()
    out=Path(a.output_dir)
    out.mkdir(parents=True,exist_ok=True)
    langs=[c.strip() for c in a.langs.split(",") if c.strip()]
    results=[]
    for code in langs:
        if code not in NATURAL_TTS_PROFILES:raise ValueError("Unknown voice "+code)
        results.append(await audit_one(code,out,a.timeout))
        await asyncio.sleep(.5)
    summary={"observed_at_utc":datetime.now(timezone.utc).isoformat(),
        "edge_tts_expected_version":EDGE_TTS_VERSION,
        "languages":len(results),
        "success_count":sum(r["status"]=="ok" for r in results),
        "results":results}
    (out/"voice-health.json").write_text(json.dumps(
        summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print("VOICE_HEALTH_SUMMARY",json.dumps(
        {k:v for k,v in summary.items() if k!="results"},
        ensure_ascii=False),flush=True)
    # Save results even when blocked: workflow evaluates JSON separately.
if __name__=="__main__":
    asyncio.run(main())
