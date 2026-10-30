#!/usr/bin/env python3
"""Re-export immutable P259 approved manuscripts into four ZIP bundles.
Current-revision English Finals and QA-passed AI texts ONLY. Does not publish
into formal lesson folders or claim missing languages are completed.
"""
import json,sys,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from central_manuscript_export import manuscript_files
from tts_fingerprint import segments_fingerprint

def run():
    source=json.loads((HERE/"p259_approved_audio_source.json").read_text(encoding="utf-8"))
    assert source["period"]==259
    work=Path("/tmp/p259-verified-manuscript-bundles")
    work.mkdir(parents=True,exist_ok=True)
    counts={}
    for lesson in [f"P259-L{i:02d}" for i in range(1,5)]:
        rows=[r for r in source["tasks"] if r["task_id"]==lesson]
        assert rows and rows[0]["lang"]=="en"
        approved_ids={int(x["id"]) for x in rows[0]["segments"]}
        revision=rows[0]["revision"]
        if len(approved_ids)!=len(rows[0]["segments"]):raise ValueError("English duplicated IDs")
        zip_path=work/(lesson+"-approved-manuscripts.zip")
        index={"lesson":lesson,"status":"human-final-and-existing-current-revision-QA-only",
               "languages":[],"not_included":"unapproved_or_missing_languages"}
        with zipfile.ZipFile(zip_path,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=8) as bundle:
            for row in rows:
                lang=row["lang"]
                if row["revision"]!=revision:raise ValueError("source_revision_drift")
                if len(row["segments"])!=len(approved_ids) or {
                    int(x["id"]) for x in row["segments"]}!=approved_ids:
                    raise ValueError("segment_ID_mismatch")
                files=manuscript_files(lesson,lang,{"revision":revision},
                  {"job_id":row["job_id"],"segments":row["segments"]})
                for filename,content in files.items():
                    bundle.writestr(lang+"/"+filename,content)
                index["languages"].append({"language":lang,"source_sha256":
                    segments_fingerprint(row["segments"]), "files":list(files)})
            bundle.writestr("approved_manifest.json",json.dumps(index,ensure_ascii=False,indent=2))
        counts[lesson]=len(rows)
        print("P259_APPROVED_MANUSCRIPT_BUNDLE",lesson,len(rows),
              zip_path.stat().st_size,flush=True)
    if sum(counts.values())!=28:raise ValueError("approved snapshot count drift")
    print("P259_ALL_APPROVED_MANUSCRIPTS_PACKAGED",json.dumps(counts))
if __name__=="__main__":run()
