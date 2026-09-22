import base64
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path


def publish_review_cache(task_id: str, cache_path):
    """Publish one exact-path review JSON through the Apps Script bridge.

    GitHub path is deterministic:
      studio-review-cache/<task_id>/zh.json

    Manual/local runs without bridge runtime simply skip publishing.
    """
    bridge_url = str(os.environ.get("SOULKEY_BRIDGE_URL") or "").strip()
    nonce = str(os.environ.get("SOULKEY_RUNTIME_NONCE") or "").strip()

    if not bridge_url or not nonce:
        print("[REVIEW-CACHE] 非 Web Worker 執行，略過 GitHub 人工定稿快取。", flush=True)
        return None

    task_id = str(task_id or "").strip()
    path = Path(cache_path)
    if not path.exists():
        raise RuntimeError(f"人工定稿快取檔不存在：{path}")

    raw = path.read_bytes()
    content_b64 = base64.b64encode(raw).decode("ascii")

    data = urllib.parse.urlencode({
        "action": "worker_review_publish",
        "nonce": nonce,
        "task_id": task_id,
        "content_b64": content_b64,
    }).encode("utf-8")

    request = urllib.request.Request(
        bridge_url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    with urllib.request.urlopen(request, timeout=90) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if not payload.get("ok"):
        raise RuntimeError(
            "GitHub 人工定稿快取發佈失敗："
            + str(payload.get("message") or payload.get("error") or payload)
        )

    print(
        "[REVIEW-CACHE] GitHub 已更新："
        + str(payload.get("path") or f"studio-review-cache/{task_id}/zh.json"),
        flush=True,
    )
    return payload
