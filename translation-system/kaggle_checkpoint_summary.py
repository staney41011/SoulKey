"""Read-only Kaggle progress summary without lecture text or credentials."""
import argparse
from collections import Counter
import json
import re
import subprocess

def reason_category(reason):
    value=str(reason).lower()
    for name,words in [
        ("numbers",("number","numeric","digit")),
        ("negation",("negation","negative")),
        ("omission",("omission","omit","missing","incomplete")),
        ("addition",("added","addition","invent","hallucinat")),
        ("language_copy",("english_copy","copied english","empty_or_english","copy")),
        ("repetition",("repeat",)),
        ("terminology",("terminolog","proper name","religious term")),
        ("uncertainty",("uncertain","possible","maybe")),
        ("meaning",("meaning","semantic","incorrect","mistranslat")),
        ("language_script",("script","language")),
    ]:
        if any(word in value for word in words):return name
    return "other"

def summarize(raw):
    try:
        entries=json.loads(raw)
    except (ValueError,TypeError):
        entries=[]
    if not isinstance(entries,list):entries=[]
    text="".join(str(row.get("data", "")) for row in entries if isinstance(row,dict))
    result={"scope":"latest_private_kernel_logs","entries":len(entries),
        "elapsed_seconds":round(max((float(row.get("time",0) or 0) for row in entries if isinstance(row,dict)),default=0)),
        "native_runtime_verified":False,"model_ready":False,"translation_budget_reached":False,
        "delivered":[],"review":[],"qa_reasons":{}}
    for line in text.splitlines():
        if line.startswith("GEMMA4_SERVER_RUNTIME_VERIFIED"):result["native_runtime_verified"]=True
        if line.startswith("GEMMA4_QAT_12B_READY"):result["model_ready"]=True
        if line.startswith("GEMMA4_P259_TRANSLATION_TIME_BUDGET_REACHED"):result["translation_budget_reached"]=True
        match=re.fullmatch(r"GEMMA4_P259_PENDING_LANGUAGES (\d+)",line)
        if match:result["pending_at_start"]=int(match[1])
        match=re.fullmatch(r"GEMMA4_P259_PROGRESS (\d+) (\d+)",line)
        if match:result["progress"]={"passed":int(match[1]),"review":int(match[2])}
        match=re.fullmatch(r"GEMMA4_P259_DELIVERED (P259-L0[1-4]) ([a-z]{2}) (\d+)",line)
        if match:result["delivered"].append({"task":match[1],"lang":match[2],"segments":int(match[3])})
        match=re.match(r"GEMMA4_P259_REVIEW_ONLY (P259-L0[1-4]) ([a-z]{2}) ([A-Za-z]+)(?: |$)",line)
        if match:result["review"].append({"task":match[1],"lang":match[2],"error_class":match[3]})
        match=re.match(r"GEMMA4_QA_UNRESOLVED_REASONS ([a-z]{2}) (\{.*\})$",line)
        if match:
            try:
                issues=json.loads(match[2]);counts=Counter();ids=[]
                for sid,reasons in issues.items():
                    if not str(sid).isdigit() or not isinstance(reasons,list):continue
                    ids.append(int(sid));counts.update(reason_category(reason) for reason in reasons)
                result["qa_reasons"][match[1]]={"segment_ids":ids,"categories":dict(counts)}
            except (ValueError,AttributeError,TypeError):pass
    if "GLIBC_2.38" in text or "GLIBCXX_3.4.32" in text:result["native_loader_failure"]=True
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel",default="cwlmrcsir/soulkey-gpu-worker")
    args=parser.parse_args()
    try:
        process=subprocess.run(["kaggle","kernels","logs",args.kernel],capture_output=True,text=True,timeout=90)
    except (subprocess.TimeoutExpired,OSError):
        print(json.dumps({"ok":False,"reason":"kaggle_logs_unavailable"}));return 1
    if process.returncode:
        print(json.dumps({"ok":False,"reason":"kaggle_logs_unavailable","exit_code":process.returncode}));return 1
    print(json.dumps({"ok":True,**summarize(process.stdout)},ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__":raise SystemExit(main())
