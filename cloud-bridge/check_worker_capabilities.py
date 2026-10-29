"""Check live Bridge route wiring before touching a translation job.

This submits an intentionally invalid, non-existent job ID. It never
claims, modifies, or publishes a real translation.
"""
import json,os,urllib.request,urllib.error
base=os.environ["SOULKEY_BRIDGE_URL"].rstrip("/")
idurl=os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"]
if "audience=" not in idurl:
    idurl+=("&" if "?" in idurl else "?")+"audience=soulkey-bridge"
req=urllib.request.Request(idurl,headers={
    "Authorization":"Bearer "+os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]
})
with urllib.request.urlopen(req,timeout=25) as reply:
    token=json.load(reply)["value"]
url=base
body=b"action=worker_job_quality&job_id=00000000-0000-4000-8000-000000000000&language=xx"
request=urllib.request.Request(url,method="POST",data=body,headers={
    "Content-Type":"application/x-www-form-urlencoded",
    "Authorization":"Bearer "+token
})
try:
    with urllib.request.urlopen(request,timeout=30) as response:
        result=json.load(response)
except urllib.error.HTTPError as e:
    result=json.load(e)
if result.get("type")=="worker_job_quality":
    mode="remote"
elif result.get("type")=="bridge_error" and result.get("error")=="unauthorized":
    mode="local_receipts"
else:
    # Fail closed if route behaviour is unknown. Never guess on auth faults.
    raise RuntimeError("Unknown bridge capability response: "+
        str(result.get("type"))+"/"+str(result.get("error")))
with open(os.environ["GITHUB_ENV"],"a",encoding="utf-8") as out:
    out.write("SOULKEY_QA_RECEIPT_MODE="+mode+"\n")
print("SOULKEY_QA_RECEIPT_MODE",mode)
if mode=="local_receipts":
    print("WARNING: QA is enforced in Worker, but this deployed bridge "+
          "does not persist QA receipts. A per-job audit artifact will be saved.")
