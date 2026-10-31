#!/usr/bin/env python3
"""P259 Edge audio-only from a prior GitHub translation artifact. No Gemini/GCP."""
import argparse, asyncio, hashlib, importlib.util, json, re
from pathlib import Path
import gdown

SOURCES={"L01":"1EM3T1iZ2N5AJoW0OSawKJTiD5mUCIuyy","L02":"1oHonBUDOKYe95SXkmUPdy8rasSG1Uiy1","L03":"1B4zHH4p2eQ-ApLrMtHBwZkN8xfqOwU-5","L04":"1WVvcJ0HbSKlwRuSCpCQtjbyq9-_7IPuF"}
def fingerprint(segments):
    rows=[{"id":int(s["id"]),"start":float(s["start"]),"end":float(s["end"]),"text":str(s["text"])} for s in segments]
    return hashlib.sha256(json.dumps(rows,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--lesson",required=True,choices=SOURCES)
    ap.add_argument("--lang",required=True)
    ap.add_argument("--artifact-dir",default="artifact-in")
    args=ap.parse_args()
    folder=Path(args.artifact_dir)
    docs=list(folder.rglob("*翻譯稿資料.json"))
    reports=list(folder.rglob("QA_驗收報告.json"))
    if len(docs)!=1 or len(reports)!=1:raise ValueError("artifact manuscript or QA missing/ambiguous")
    doc=json.loads(docs[0].read_text("utf-8"));qa=json.loads(reports[0].read_text("utf-8"))
    if doc.get("task_id")!=f"P259-{args.lesson}" or doc.get("language")!=args.lang:raise ValueError("artifact lesson/language mismatch")
    if qa.get("translation_status")!="AI_QA_PASS_NOT_HUMAN_REVIEWED" or qa.get("unresolved"):raise ValueError("Gemma AI QA not clean")
    if doc.get("qa_status")!=qa.get("translation_status"):raise ValueError("QA status mismatch")
    srcfile=Path("source_en_final.json")
    if not gdown.download(id=SOURCES[args.lesson],output=str(srcfile),quiet=True):raise RuntimeError("SOURCE_READ_FAILED")
    src=json.loads(srcfile.read_text("utf-8"))
    source_segments=src["segments"];segs=doc["segments"];sha=fingerprint(source_segments)
    if sha!=src.get("source_sha256") or sha!=doc.get("source_sha256") or sha!=qa.get("source_sha256"):raise ValueError("ENGLISH_SOURCE_SHA_MISMATCH")
    if [int(x["id"]) for x in segs]!=[int(x["id"]) for x in source_segments]:raise ValueError("SEGMENT_IDS_MISMATCH")
    if len(segs)!=qa.get("segments_translated") or any(not x.get("text","").strip() for x in segs):raise ValueError("INCOMPLETE_MANUSCRIPT")
    txt=list(folder.rglob("*翻譯稿時間軸.txt"))
    srt=list(folder.rglob("*翻譯稿字幕.srt"))
    if len(txt)!=1 or len(srt)!=1:raise ValueError("TXT_SRT_MISSING")
    if txt[0].read_text("utf-8").strip()!="\n".join(x["text"] for x in segs).strip():raise ValueError("TXT_CONTENT_MISMATCH")
    if len(re.findall(r"(?m)^[0-9]+[ ]*$",srt[0].read_text("utf-8")))!=len(segs):raise ValueError("SRT_SEGMENT_MISMATCH")
    spec=importlib.util.spec_from_file_location("edge_audio","translation-system/p259_edge_audio_from_drive.py")
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    if args.lang not in module.VOICE:raise ValueError("VOICE_NOT_CONFIGURED")
    out=Path("audio-only-output")/args.lesson/args.lang;out.mkdir(parents=True,exist_ok=True)
    result=asyncio.run(module.synthesize(doc,out,module.VOICE[args.lang]))
    name=docs[0].name.replace("翻譯稿資料.json","Gemma4待複核TTS音檔.mp3")
    (out/"audio.mp3").rename(out/name)
    report={"task_id":doc["task_id"],"language":args.lang,"source_sha256":sha,"qa_status":qa["translation_status"],"audio_status":"needs_timeline_review","source_segments":len(segs),"video_end_seconds":float(segs[-1]["end"]),**result}
    (out/"TTS_QA_驗收報告.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print("ARTIFACT_AUDIO_COMPLETE",args.lesson,args.lang,result["bytes"],result["audio_seconds"],flush=True)
if __name__=="__main__":main()
