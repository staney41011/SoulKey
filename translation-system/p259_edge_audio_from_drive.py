#!/usr/bin/env python3
"""P259 isolated audio recovery from a real Drive manuscript; uses validated MS Edge endpoint."""
import argparse, asyncio, hashlib, json, subprocess, sys
from pathlib import Path
import gdown, edge_tts
import edge_tts.communicate as edge_communicate
from edge_tts.constants import TRUSTED_CLIENT_TOKEN

# Official SoulKey production workaround since October 2026.
edge_communicate.WSS_URL=(
  "wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1"
  "?Ocp-Apim-Subscription-Key="+TRUSTED_CLIENT_TOKEN
)
VOICE={
"it":"it-IT-DiegoNeural","hi":"hi-IN-MadhurNeural","ta":"ta-IN-ValluvarNeural",
"km":"km-KH-PisethNeural","bn":"bn-BD-PradeepNeural","ne":"ne-NP-SagarNeural",
"lo":"lo-LA-ChanthavongNeural","ko":"ko-KR-InJoonNeural","my":"my-MM-ThihaNeural",
"pt":"pt-BR-AntonioNeural","id":"id-ID-ArdiNeural","vi":"vi-VN-NamMinhNeural",
"ja":"ja-JP-KeitaNeural",
}
def split_text(src,maxc):
    s=" ".join(str(src).split());parts=[]
    while s:
      if len(s)<=maxc:parts.append(s);break
      cut=maxc
      for j in range(maxc,max(30,maxc-75),-1):
         if s[j-1] in " .!?។。！？，、;；":cut=j;break
      parts.append(s[:cut].strip());s=s[cut:].strip()
    return [x for x in parts if x]
async def synthesize(doc,output,voice):
    blocks=[]
    for s in doc["segments"]:
       for part in split_text(s["text"],320 if doc["language"] in ("km","lo","ta") else 370):
         blocks.append(part)
    print("VOICE_START",doc["language"],"blocks",len(blocks),flush=True)
    sem=asyncio.Semaphore(2);partdir=output/"parts";partdir.mkdir(parents=True,exist_ok=True)
    async def one(i,text):
        path=partdir/f"{i:04d}.mp3"
        for retry in range(1,4):
            try:
                async with sem:
                    comm=edge_tts.Communicate(text=text,voice=voice,rate="-3%",pitch="-1Hz")
                    await asyncio.wait_for(comm.save(str(path)),timeout=90)
                if path.stat().st_size<100:raise ValueError("empty mp3 part")
                if i%12==0:print("VOICE_PROGRESS",i,"/",len(blocks),flush=True)
                return
            except Exception as exc:
                print("VOICE_RETRY",i,retry,type(exc).__name__,str(exc)[:80],flush=True)
                if retry==3:raise
                await asyncio.sleep(retry*4)
    await asyncio.gather(*(one(i+1,s) for i,s in enumerate(blocks)))
    c=output/"concat.txt";c.write_text("".join("file '"+str((partdir/f"{i:04d}.mp3").resolve())+"'\n" for i in range(1,len(blocks)+1)))
    result=output/"audio.mp3"
    subprocess.run(["ffmpeg","-y","-hide_banner","-loglevel","error","-f","concat","-safe","0","-i",str(c),"-c:a","libmp3lame","-b:a","128k",str(result)],check=True)
    sec=float(subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(result)],text=True).strip())
    if sec<120 or result.stat().st_size<100000:raise ValueError("incomplete audio")
    print("VOICE_COMPLETED",doc["language"],"audio_sec",round(sec,1),"bytes",result.stat().st_size,"parts",len(blocks),flush=True)
    return {"audio_seconds":round(sec,2),"bytes":result.stat().st_size,"blocks":len(blocks),"sha256":hashlib.sha256(result.read_bytes()).hexdigest(),"voice":voice}
def main():
    p=argparse.ArgumentParser();p.add_argument("--file-id",required=True);p.add_argument("--lang",required=True,choices=VOICE)
    p.add_argument("--lesson",required=True);args=p.parse_args()
    d=Path("audio-only-output")/args.lesson/args.lang;d.mkdir(parents=True,exist_ok=True)
    source=d/"translation.json"
    if not gdown.download(id=args.file_id,output=str(source),quiet=True):raise RuntimeError("DRIVE_READ_FAILED")
    payload=json.loads(source.read_text("utf-8"))
    if payload.get("language")!=args.lang or not payload.get("segments") or payload.get("task_id")!=f"P259-{args.lesson}":raise ValueError("wrong manuscript task/lang")
    if any(not str(s["text"]).strip() for s in payload["segments"]):raise ValueError("empty manuscript")
    result=asyncio.run(synthesize(payload,d,VOICE[args.lang]))
    # derive displayed file prefix from manuscript's formal Drive name only after validated source
    name=(source.parent/"audio.mp3")
    filename=f"P259-{args.lesson}_{args.lang}_EdgeTTS_待複核.mp3"
    name.rename(d/filename)
    q={"task_id":payload["task_id"],"language":args.lang,"engine":"edge-tts-7.2.8-msedgeservices","source_sha256":payload.get("source_sha256"),"qa_status":payload.get("qa_status","unknown"),"audio_status":"needs_timeline_review","source_segments":len(payload["segments"]),"video_end_seconds":float(payload["segments"][-1]["end"]),**result}
    (d/"TTS_QA_驗收報告.json").write_text(json.dumps(q,ensure_ascii=False,indent=2),encoding="utf-8")
    source.unlink();(d/"concat.txt").unlink(missing_ok=True)
    import shutil;shutil.rmtree(d/"parts",ignore_errors=True)
if __name__=="__main__":main()
