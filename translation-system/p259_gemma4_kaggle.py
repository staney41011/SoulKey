#!/usr/bin/env python3
"""P259 Gemma 4 on Kaggle GPU; no Gemini API. Verified human English Final only."""
import argparse,json,os,re,sys,uuid,time
from datetime import datetime,timezone
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE),str(HERE.parent/"cloud-bridge")]
LANGS={"th":"Thai","es":"Spanish","id":"Indonesian","vi":"Vietnamese",
 "hi":"Hindi","ta":"Tamil","ja":"Japanese","ko":"Korean","km":"Khmer",
 "bn":"Bengali","ne":"Nepali","lo":"Lao","my":"Burmese","it":"Italian","pt":"Portuguese"}
MODEL_ID=os.environ.get("SOULKEY_GEMMA4_KAGGLE_MODEL","google/gemma-4/transformers/gemma-4-12b-it/1")

def parse_json(text):
    text=str(text).strip()
    if text.startswith(chr(96)*3):
        text=text.split("\n",1)[-1].rsplit(chr(96)*3,1)[0]
    for i,char in enumerate(text):
        if char not in "[{":continue
        try:
            parsed,_=json.JSONDecoder().raw_decode(text[i:])
            if isinstance(parsed,(dict,list)):return parsed
        except ValueError:pass
    raise ValueError("gemma_json_invalid")

def check_ids(source,rows):
    if not isinstance(rows,list):raise ValueError("gemma_segments_not_list")
    expected=[int(x["id"]) for x in source]
    if len(set(expected))!=len(expected):raise ValueError("duplicate_english_ids")
    found={}
    for item in rows:
        key=int(item["id"]);text=str(item.get("text") or "").strip()
        if key in found or not text or len(text)>15000:raise ValueError("invalid_gemma_text")
        found[key]=text
    if set(expected)!=set(found):raise ValueError("gemma_ids_incomplete")
    return [{"id":sid,"text":found[sid]} for sid in expected]

def verify_server_runtime(binary,bindir):
    """Reject an incompatible pinned Kaggle image before downloading weights."""
    import subprocess
    env=dict(os.environ)
    env["LD_LIBRARY_PATH"]=str(bindir)+os.pathsep+env.get("LD_LIBRARY_PATH","")
    probe=subprocess.run([str(binary),"--version"],capture_output=True,
                         text=True,env=env,timeout=30,check=False)
    if probe.returncode:
        # A native loader error cannot contain lesson text or OAuth values.
        detail=(probe.stderr or probe.stdout or "")[-1200:]
        print("GEMMA4_SERVER_RUNTIME_PROBE_FAILED",detail,flush=True)
        raise RuntimeError("Gemma4 CUDA binary cannot load in this Kaggle image; "
                           "use docker_image_pinning_type=latest without the old docker_image digest")
    print("GEMMA4_SERVER_RUNTIME_VERIFIED",flush=True)
    return env

class Gemma:
    """Gemma 4 12B on Kaggle GPU, using Google's public QAT 4-bit GGUF.

    The older Kaggle model registry path cannot attach newly requested models
    in non-interactive kernels. Download public Apache-2.0 weights directly
    from Hugging Face; no API key, Google OAuth, or model-source attachment.
    """
    def __init__(self,glossary=""):
        self.glossary=str(glossary or "")[:4000]
        import subprocess
        import time
        import urllib.request
        from pathlib import Path
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError("Gemma4 GGUF requires a real Kaggle GPU")
        print("GEMMA4_GGUF_GPU",torch.cuda.get_device_name(0),flush=True)
        base=Path("/kaggle/working/gemma4-local")
        base.mkdir(parents=True,exist_ok=True)
        # Never compile llama.cpp inside a short-lived Kaggle GPU session.
        # Official upstream release b11988 supports Gemma 4 and CUDA 12.8.
        # Kaggle T4 already provides CUDA 12.8, so install pre-built binaries.
        import tarfile
        import shutil
        binary=base/"bin"/"llama-server"
        if not binary.exists():
            release="b11988"
            asset=("llama-"+release+"-bin-ubuntu-cuda-12.8-x64.tar.gz")
            url=("https://github.com/ggml-org/llama.cpp/releases/download/"
                 +release+"/"+asset)
            package=base/asset
            print("GEMMA4_OFFICIAL_PREBUILT_DOWNLOAD",asset,flush=True)
            urllib.request.urlretrieve(url,str(package))
            extracted=base/"upstream"
            extracted.mkdir(parents=True,exist_ok=True)
            with tarfile.open(package,"r:gz") as archive:
                # Avoid path traversal or symlinks when extracting binaries.
                root=extracted.resolve()
                for member in archive.getmembers():
                    target=(extracted/member.name).resolve()
                    if not target.is_relative_to(root):
                        raise RuntimeError("Unsafe upstream archive member")
                archive.extractall(extracted,filter="data")
            found=list(extracted.rglob("llama-server"))
            if len(found)!=1:
                raise RuntimeError("llama-server missing in official binary asset")
            bindir=found[0].parent
            binary=bindir/"llama-server"
            binary.chmod(0o755)
            print("GEMMA4_PREBUILT_CUDA_SERVER",binary,flush=True)
        else:
            bindir=binary.parent
        env=verify_server_runtime(binary,bindir)
        from huggingface_hub import hf_hub_download
        repo="google/gemma-4-12B-it-qat-q4_0-gguf"
        filename="gemma-4-12b-it-qat-q4_0.gguf"
        print("GEMMA4_PUBLIC_QAT_DOWNLOAD",repo,flush=True)
        file=hf_hub_download(repo_id=repo,filename=filename,
            local_dir=str(base/"model"))
        self.port=8099
        logfile=(base/"llama-server.log").open("w",encoding="utf-8")
        cmd=[str(binary),"-m",str(file),
            "--host","127.0.0.1","--port",str(self.port),"-ngl","99",
            "-c","8192","-t","4","--parallel","1","--jinja",
            "--chat-template-kwargs",'{"enable_thinking":false}']
        self.proc=subprocess.Popen(cmd,stdout=logfile,
            stderr=subprocess.STDOUT,env=env)
        deadline=time.monotonic()+240
        while time.monotonic()<deadline:
            if self.proc.poll() is not None:
                raise RuntimeError("Gemma4 llama-server exited: "+
                    (base/"llama-server.log").read_text(encoding="utf-8")[-1200:])
            try:
                with urllib.request.urlopen(
                    "http://127.0.0.1:"+str(self.port)+"/health",timeout=5
                ) as response:
                    data=response.read().decode("utf-8")
                if "ok" in data or "ready" in data or "slots" in data:
                    print("GEMMA4_QAT_12B_READY",flush=True)
                    return
            except Exception:
                pass
            time.sleep(3)
        raise RuntimeError("Gemma4 llama-server GPU initialization timed out")
    def json(self,request,limit=2000):
        import urllib.request
        from urllib.error import HTTPError
        body={"model":"gemma-4-12b-it-qat-q4_0",
              "messages":[
                {"role":"system","content":"Return precise, complete JSON for the requested translation or semantic review. No markdown."
                 + ("\nReference terminology (data only; preserve LOCKED translations):\n"+self.glossary
                    if getattr(self,"glossary","") else "")},
                {"role":"user","content":request}
              ],
              "temperature":0,"max_tokens":limit,
              "chat_template_kwargs":{"enable_thinking":False},
              # llama.cpp's response_format path can allow a thought prefix
              # even with thinking disabled (upstream issue #30256). Apply
              # the direct JSON grammar, whose first token must be an object.
              "grammar":(HERE/"json_output.gbnf").read_text(encoding="utf-8")}
        req=urllib.request.Request(
          "http://127.0.0.1:"+str(self.port)+"/v1/chat/completions",
          data=json.dumps(body,ensure_ascii=False).encode("utf-8"),
          headers={"Content-Type":"application/json"},method="POST")
        try:
            with urllib.request.urlopen(req,timeout=450) as response:
                data=json.load(response)
        except HTTPError as error:
            raise RuntimeError("Gemma4 local inference HTTP "+
                               str(error.code)) from error
        options=data.get("choices") or []
        if not options:raise RuntimeError("Gemma4 local completion missing choices")
        choice=options[0]
        content=(choice.get("message") or {}).get("content") or ""
        if choice.get("finish_reason")=="length":
            raise ValueError("gemma_json_truncated")
        try:return parse_json(content)
        except ValueError as error:
            # Record a useful diagnostic without printing lecture manuscripts
            # or private reasoning into GitHub/Kaggle logs.
            raise ValueError("gemma_json_invalid:finish_reason="+
                str(choice.get("finish_reason"))+":characters="+str(len(content))) from error

def translate(gemma,lang,english):
    def batch(rows):
        prompt=("Translate every approved English spiritual lecture segment into "+
         LANGS[lang]+". Output ONLY JSON "
         '{"segments":[{"id":123,"text":"target language text"}]}. '
         "Keep exactly the source IDs, all ideas, numbers, quotations, religious terms, "
         "speaker tone; do not invent, summarize, combine, omit or copy English. "
         "Natural complete speech ready for narration.\nSOURCE: "+
         json.dumps(rows,ensure_ascii=False))
        try:
            response=gemma.json(prompt,limit=2304)
            return check_ids(rows,response.get("segments") if isinstance(response,dict) else response)
        except Exception:
            if len(rows)==1:raise
            m=len(rows)//2
            return batch(rows[:m])+batch(rows[m:])
    result=[]
    for start in range(0,len(english),6):
        result+=batch(english[start:start+6])
        print("GEMMA4_TRANSLATION",lang,len(result),len(english),flush=True)
    return result

def local_issues(source,target,lang):
    from gemini_engine import local_language_issue
    from gemini_quality import translated_number_issues
    issues=[]
    original=str(source or "").strip()
    candidate=str(target or "").strip()
    # Numbers, timestamps and punctuation are language-neutral subtitle
    # fragments. Requiring them to be "translated" creates a QA deadlock:
    # the faithful target is identical to the English source.
    neutral_source=not re.search(r"[A-Za-z]",original)
    if not candidate:
        issues.append("empty_or_english_copy")
    elif candidate.casefold()==original.casefold() and not neutral_source:
        issues.append("empty_or_english_copy")
    error=local_language_issue(target,source,lang)
    if error:issues.append(str(error))
    issues+=translated_number_issues(source,target,lang)
    if re.search(r"(.{3,20}?)\1{7,}",target,re.S):issues.append("repeated_text")
    return list(dict.fromkeys(issues))

def qa(gemma,lang,source,translation,semantic_pass_cache=None):
    """Recheck all hard rules; reuse semantic passes only for unchanged text.

    Cache lifetime is exactly one repair() call for one task, language and
    English revision. Changed candidates always get a fresh semantic review.
    """
    dest={int(x["id"]):x["text"] for x in translation}
    errors={}
    for item in source:
        sid=int(item["id"])
        issues=local_issues(item["text"],dest[sid],lang)
        if issues:errors[sid]=issues
    # Semantic QA is performed by local Gemma, not a paid/rate-limited API.
    for i in range(0,len(source),6):
        part=source[i:i+6]
        if semantic_pass_cache is not None:
            part=[x for x in part if
                  (int(x["id"]),dest[int(x["id"])]) not in semantic_pass_cache]
        if not part:
            continue
        pairs=[{"id":x["id"],"english":x["text"],
                "translation":dest[int(x["id"])]} for x in part]
        prompt=("Inspect "+LANGS[lang]+" translations versus their English source. "
         "Flag only material omissions, invented ideas, wrong numbers, incorrect names, "
         "wrong language, or serious religious-term mistranslations. Accept natural "
         "rewording. Return ONLY JSON "
         '{"failures":[{"id":123,"issue":"reason"}]} '
         "or an empty failures array.\n"+json.dumps(pairs,ensure_ascii=False))
        answer=gemma.json(prompt,limit=900)
        fail=answer.get("failures") if isinstance(answer,dict) else None
        if not isinstance(fail,list):raise ValueError("local_gemma_qa_invalid")
        legal={int(x["id"]) for x in part}
        flagged=set()
        for item in fail:
            sid=int(item.get("id",item.get("segment_id",-1)))
            if sid not in legal:raise ValueError("local_gemma_qa_unknown_id")
            issue=str(item.get("issue") or "").strip()
            if issue:
                flagged.add(sid)
                errors.setdefault(sid,[]).append(issue[:200])
        if semantic_pass_cache is not None:
            for item in part:
                sid=int(item["id"])
                if sid not in flagged:
                    semantic_pass_cache.add((sid,dest[sid]))
    return errors

def repair(gemma,lang,source,translated):
    originals={int(x["id"]):x["text"] for x in source}
    current={int(x["id"]):x["text"] for x in translated}
    repairs=0
    semantic_pass_cache=set()
    for round_no in range(5):
        failures=qa(gemma,lang,source,[{"id":i,"text":t} for i,t in current.items()],
                    semantic_pass_cache=semantic_pass_cache)
        if not failures:
            return [{"id":x["id"],"text":current[int(x["id"])]} for x in source],round_no+1,repairs
        if round_no==4:break
        print("GEMMA4_QA_REPAIR",lang,len(failures),flush=True)
        for sid,issues in failures.items():
            prompt=("Re-translate this ONE English segment faithfully to "+LANGS[lang]+
              ". Correct: "+",".join(issues)+". Do not omit meaning, quantities or proper "
              "names. Output ONLY JSON "+'{"segments":[{"id":'+str(sid)+',"text":"..."}]}'+
              "\nEnglish: "+originals[sid]+"\nEarlier result: "+current[sid])
            # Long English CC segments often contain 150+ words and several
            # numerical claims. 950 tokens may clip their target-language
            # retranslation. Increase only for such difficult segments.
            token_budget=2304 if len(originals[sid])>560 else 1200
            ans=gemma.json(prompt,limit=token_budget)
            rows=ans.get("segments") if isinstance(ans,dict) else ans
            current[sid]=check_ids([{"id":sid}],rows)[0]["text"]
            repairs+=1
    # A second, isolated check is necessary for self-judged semantic QA.
    # Gemma occasionally flags faithful paraphrases as omissions.  Never
    # override deterministic wrong-language, number, copied-English, or
    # repetition checks; only independently adjudicate semantic-only flags.
    verified_failures={}
    for sid,issues in failures.items():
        original=originals[sid]
        candidate=current[sid]
        hard_issues=local_issues(original,candidate,lang)
        if hard_issues:
            verified_failures[sid]=list(dict.fromkeys(hard_issues+issues))
            continue
        try:
            prompt=("You are an independent final translation reviewer. Compare exactly "
              "ONE English spiritual-lecture segment with its "+LANGS[lang]+
              " translation. A paraphrase or different word order IS acceptable. "
              "Do not demand word-for-word translation. Decide whether an actual "
              "material claim, negation, name, number, or religious meaning is "
              "wrong or missing. Reply ONLY JSON: "
              '{"verdict":"accurate|material_issue|uncertain","evidence":"brief specific reason"}. '
              "Only return accurate when the entire original meaning is preserved; "
              "uncertain must never count as passing.\nENGLISH: "+
              json.dumps(original,ensure_ascii=False)+"\nTRANSLATION: "+
              json.dumps(candidate,ensure_ascii=False)+"\nFIRST_REVIEW_CONCERNS: "+
              json.dumps(issues,ensure_ascii=False))
            review=gemma.json(prompt,limit=700)
            if isinstance(review,dict) and review.get("verdict")=="accurate":
                print("GEMMA4_SECOND_REVIEW_CLEARED",lang,sid,flush=True)
                continue
        except Exception as exc:
            print("GEMMA4_SECOND_REVIEW_ERROR",lang,sid,type(exc).__name__,flush=True)
        verified_failures[sid]=issues
    if not verified_failures:
        return [{"id":x["id"],"text":current[int(x["id"])]}
                for x in source],6,repairs
    print("GEMMA4_QA_UNRESOLVED_REASONS",lang,
          json.dumps({str(k):v for k,v in verified_failures.items()},
                     ensure_ascii=False)[:4500],flush=True)
    raise ValueError("gemma4_unresolved_qa_"+lang+"_"+
                     ",".join(map(str,verified_failures)))

def append_verify(sheets,tab,rows):
    from config import SPREADSHEET_ID
    appended=sheets.spreadsheets().values().append(
      spreadsheetId=SPREADSHEET_ID,range="'"+tab+"'!A1",
      valueInputOption="RAW",insertDataOption="INSERT_ROWS",
      body={"values":rows}).execute(num_retries=5)
    area=appended.get("updates",{}).get("updatedRange")
    if not area:raise RuntimeError("no_sheet_write_receipt")
    observed=sheets.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID,
      range=area,valueRenderOption="FORMATTED_VALUE").execute(num_retries=5).get("values",[])
    if observed!=rows:raise RuntimeError("sheet_write_readback_mismatch_"+tab)

def run():
    parser=argparse.ArgumentParser()
    parser.add_argument("--period",type=int,default=259)
    parser.add_argument("--task-id",default="")
    parser.add_argument("--langs",default="",help="Only requested, enabled AI translation languages")
    parser.add_argument("--max-new-languages",type=int,default=60)
    parser.add_argument("--self-test",action="store_true")
    opts=parser.parse_args()
    requested={x.strip() for x in opts.langs.split(",") if x.strip()}
    if requested-set(LANGS):raise SystemExit("Unsupported requested translation language")
    if opts.self_test:
        assert parse_json('Example {"segments":[{"id":1,"text":"hello"}]}')["segments"][0]["id"]==1
        assert check_ids([{"id":2},{"id":3}],[{"id":3,"text":"b"},{"id":2,"text":"a"}])[0]["id"]==2
        print("GEMMA4_OFFLINE_TEST_OK")
        return
    if opts.period!=259:raise SystemExit("Only P259 is authorized")
    from config import SPREADSHEET_ID
    from google_io import build_google_services,read_values
    from central_tts_source import verified_english_final,verified_translation,SourceNotReady
    from central_tts_recovery import ready_tasks
    from central_manuscript_export import publish_manuscript
    drive,sheets=build_google_services()
    read=lambda r:read_values(sheets,SPREADSHEET_ID,r)
    indexes=read("英文定稿索引!A2:F10000")
    backups=read("英文定稿備存!A2:G10000")
    plans=read("語言任務設定!A2:J5000")
    trans=read("多語翻譯結果!A2:G50000")
    receipts=read("翻譯QA紀錄!A2:I5000")
    tasks=list(ready_tasks(sheets,259,opts.task_id))
    remaining=[]
    for task in tasks:
        final=verified_english_final(task["task_id"],indexes,backups)
        langs=list(dict.fromkeys(str(r[1]) for r in plans if
            len(r)>=7 and r[0]==task["task_id"] and r[1] in LANGS
            and str(r[3]).upper()=="TRUE" and str(r[4]).lower()=="ai"))
        for lang in langs:
            if requested and lang not in requested:continue
            try:
                existing=verified_translation(task["task_id"],lang,final,trans,receipts)
            except SourceNotReady:remaining.append((task,final,lang))
            else:
                # A passed central row is not yet a Drive manuscript. Publish
                # it even when this language does not request an audio file.
                work=Path("/kaggle/working/gemma4-p259")/task["task_id"]/lang/"reuse"
                publish_manuscript(drive,sheets,task,lang,final,existing,work)
    print("GEMMA4_P259_PENDING_LANGUAGES",len(remaining),flush=True)
    if not remaining:return
    gemma=Gemma()
    passed=failed=0
    # Leave substantial Kaggle time for producing verified Edge TTS audio.
    deadline=time.monotonic()+int(os.environ.get("SOULKEY_GEMMA4_TRANSLATION_BUDGET_SECONDS","9000"))
    for task,final,lang in remaining:
        if passed>=opts.max_new_languages:break
        if time.monotonic()>=deadline:
            print("GEMMA4_P259_TRANSLATION_TIME_BUDGET_REACHED; resume remaining languages next run",flush=True)
            break
        work=Path("/kaggle/working/gemma4-p259")/task["task_id"]/lang
        work.mkdir(parents=True,exist_ok=True)
        try:
            # Reuse verified languages from pre-existing Gemini work; no rerun.
            prior=read("翻譯QA紀錄!A2:I5000")
            all_trans=read("多語翻譯結果!A2:G50000")
            try:
                approved=verified_translation(task["task_id"],lang,final,all_trans,prior)
                publish_manuscript(drive,sheets,task,lang,final,approved,work/"reuse")
                print("GEMMA4_ALREADY_DONE",task["task_id"],lang,flush=True)
                continue
            except SourceNotReady:pass
            source=[{"id":x["id"],"text":x["text"]} for x in final["segments"]]
            proposed=translate(gemma,lang,source)
            checked,batches,repair_count=repair(gemma,lang,source,proposed)
            checked_by_id={str(x["id"]):x["text"] for x in checked}
            job="gemma4-"+uuid.uuid4().hex
            now=datetime.now(timezone.utc).isoformat()
            rows=[[task["task_id"],final["revision"],lang,str(s["id"]),
                   checked_by_id[str(s["id"])],job,now] for s in final["segments"]]
            append_verify(sheets,"多語翻譯結果",rows)
            proof=[[job,task["task_id"],final["revision"],lang,
                "gemma-4-12b-it-local-gemma-qa",str(batches*((len(source)+5)//6)),str(repair_count),
                "passed",now]]
            append_verify(sheets,"翻譯QA紀錄",proof)
            approved=verified_translation(task["task_id"],lang,final,rows,proof)
            publish_manuscript(drive,sheets,task,lang,final,approved,work/"published")
            passed+=1
            print("GEMMA4_P259_DELIVERED",task["task_id"],lang,len(rows),flush=True)
        except Exception as exc:
            failed+=1
            (work/"needs_review.json").write_text(json.dumps(
                {"task_id":task["task_id"],"language":lang,
                 "error":type(exc).__name__+": "+str(exc)[:500]},ensure_ascii=False))
            print("GEMMA4_P259_REVIEW_ONLY",task["task_id"],lang,
                 type(exc).__name__,str(exc)[:300],flush=True)
        print("GEMMA4_P259_PROGRESS",passed,failed,flush=True)
    print("GEMMA4_P259_COMPLETE_THIS_RUN",passed,failed,flush=True)
    latest_trans=read("多語翻譯結果!A2:G50000")
    latest_qa=read("翻譯QA紀錄!A2:I5000")
    incomplete=0
    for task,final,lang in remaining:
        try:verified_translation(task["task_id"],lang,final,latest_trans,latest_qa)
        except SourceNotReady:incomplete+=1
    if failed or incomplete:raise SystemExit(2)

if __name__=="__main__":run()
