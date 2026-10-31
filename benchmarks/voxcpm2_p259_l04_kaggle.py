#!/usr/bin/env python3
"""Isolated Kaggle VoxCPM2 validation, P259 Lesson 04.
Only 6 speech samples, NOT 67 full-lesson segments.
Writes benchmark.json and short WAVs to Kaggle output; never touches production Drive/QA.
"""
import json
import os
from pathlib import Path
import platform
import sys
import time
import traceback
import numpy as np
import soundfile as sf

RESULT_DIR=Path("/kaggle/working") if Path("/kaggle/working").exists() else Path.cwd()
BENCH_FILE=RESULT_DIR/"voxcpm2_p259_l04_benchmark.json"
SAMPLES=__INJECT_SAMPLES_JSON__
result={"experiment":"P259-L04 isolated VoxCPM2 on Kaggle","model":"openbmb/VoxCPM2","start_utc":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),"configuration":{"load_denoiser":False,"optimize":False,"cfg_value":2.0,"inference_timesteps":10,"seed":42},"system":{"python":sys.version,"platform":platform.platform()},"samples":[],"model_loaded":False,"completed":False}
def save():
    BENCH_FILE.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print("BENCH_STATE "+json.dumps({"model_loaded":result["model_loaded"],"completed":result["completed"],"num_samples":len(result["samples"]),"last_error":result.get("error")},ensure_ascii=False),flush=True)
def memory(torch):
    if torch.cuda.is_available():
        return {"gpu_name":torch.cuda.get_device_name(0),"gpu_total_gb":round(torch.cuda.get_device_properties(0).total_memory/2**30,2),"max_allocated_gb":round(torch.cuda.max_memory_allocated(0)/2**30,3),"max_reserved_gb":round(torch.cuda.max_memory_reserved(0)/2**30,3)}
    return {"cuda_available":False}
try:
    import torch
    result["system"]["torch"]=torch.__version__
    result["system"]["cuda_version"]=torch.version.cuda
    result["system"].update(memory(torch))
    if not torch.cuda.is_available():
        raise RuntimeError("Kaggle accelerator not available: cuda is false; no CPU fallback allowed for speed benchmark")
    print("BENCH_GPU "+json.dumps(memory(torch)),flush=True)
    from voxcpm import VoxCPM
    load_start=time.monotonic()
    model=VoxCPM.from_pretrained("openbmb/VoxCPM2",device="cuda",load_denoiser=False,optimize=False)
    torch.cuda.synchronize()
    result["model_load_sec"]=round(time.monotonic()-load_start,2)
    result["model_loaded"]=True
    result["system"].update(memory(torch))
    result["sample_rate"]=model.tts_model.sample_rate
    print("BENCH_LOAD_SEC",result["model_load_sec"],"peak_gb",result["system"].get("max_allocated_gb"),flush=True)
    save()
    # First short and medium segment for each of the three delivery languages.
    for language in ("id","vi","km"):
        for case,text in enumerate(SAMPLES[language],1):
            row={"language":language,"case":case,"chars":len(text),"status":"started"}
            result["samples"].append(row)
            save()
            start=time.monotonic()
            try:
                torch.cuda.reset_peak_memory_stats()
                wav=model.generate(text=text,cfg_value=2.0,inference_timesteps=10,seed=42)
                torch.cuda.synchronize()
                elapsed=time.monotonic()-start
                sound=np.asarray(wav).reshape(-1)
                duration=len(sound)/model.tts_model.sample_rate
                if duration<=1 or not np.isfinite(sound).all() or np.max(abs(sound))<0.00001:
                    raise RuntimeError("empty, invalid or silent audio")
                # Store short sample only for manual review, never full lecture.
                p=RESULT_DIR/f"voxcpm2_p259_l04_{language}_{case}.wav"
                sf.write(str(p),sound,model.tts_model.sample_rate)
                row.update(status="ok",wall_sec=round(elapsed,2),audio_sec=round(duration,2),rtf=round(elapsed/duration,3),sample_rate=model.tts_model.sample_rate,peak_allocated_gb=round(torch.cuda.max_memory_allocated()/2**30,3),bytes=p.stat().st_size)
                print("BENCH_ROW "+json.dumps(row,ensure_ascii=False),flush=True)
            except Exception as ex:
                row.update(status="error",error_type=type(ex).__name__,error=str(ex)[:500],wall_sec=round(time.monotonic()-start,2))
                print("BENCH_ROW "+json.dumps(row,ensure_ascii=False),flush=True)
                if "out of memory" in str(ex).lower():
                    torch.cuda.empty_cache()
            save()
    ok=[x for x in result["samples"] if x["status"]=="ok"]
    result["summary"]={"ok":len(ok),"fail":len(result["samples"])-len(ok),"total":len(result["samples"]),"warm_samples":len(ok),"avg_rtf":round(sum(x["rtf"] for x in ok)/len(ok),3) if ok else None,"total_synthesis_sec":round(sum(x["wall_sec"] for x in result["samples"]),2),"total_generated_audio_sec":round(sum(x.get("audio_sec",0) for x in ok),2)}
    result["completed"]=True
except Exception as ex:
    result["error_type"]=type(ex).__name__
    result["error"]=str(ex)[:1500]
    result["traceback"]=traceback.format_exc()[-3500:]
    print("BENCH_FATAL "+result["error_type"]+" "+result["error"],flush=True)
finally:
    result["finish_utc"]=time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())
    save()
print("BENCH_FINAL "+json.dumps(result.get("summary",{"error":result.get("error")}),ensure_ascii=False),flush=True)
if not result["completed"] or result.get("summary",{}).get("fail",6):
    sys.exit(1)
