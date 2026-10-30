"""Real Kaggle GPU check using public synthetic text, no user manuscripts."""
import json
from pathlib import Path
from p259_gemma4_kaggle import Gemma,translate,repair


def main():
    source=[{"id":7,"text":"Please arrive at 7 pm. We will read two chapters together. Thank you for helping the community."}]
    gemma=Gemma()
    result={"engine":"gemma4-12b-gguf","passed":[],"failures":{}}
    try:
        for lang in ["it","pt"]:
            try:
                rows=translate(gemma,lang,source)
                checked,_,_=repair(gemma,lang,source,rows)
                if [r["id"] for r in checked]!=[7]:raise ValueError("wrong_ids")
                result["passed"].append(lang)
            except Exception as error:
                result["failures"][lang]=type(error).__name__+":"+str(error)[:240]
    finally:
        gemma.proc.terminate()
        Path("/kaggle/working/gemma-json-smoke.json").write_text(json.dumps(result),encoding="utf-8")
    print("GEMMA_JSON_SMOKE",json.dumps(result),flush=True)
    if result["failures"]:raise SystemExit(1)


if __name__=="__main__":main()
