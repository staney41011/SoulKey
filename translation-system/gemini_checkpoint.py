import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from google_io import download_drive_file, find_file, upload_or_replace_file


GITHUB_OWNER = "staney41011"
GITHUB_REPO = "SoulKey"
GITHUB_REF = "main"
DRIVE_CHECKPOINT_NAME = "gemini-shadow-checkpoint.json"


def _normalize_task_id(task_id: str):
    value = str(task_id or "").strip()
    if not re.fullmatch(r"P\d+-L\d+", value, flags=re.I):
        raise ValueError(f"task_id 格式不正確：{value}")
    return value


def github_checkpoint_path(task_id: str):
    task_id = _normalize_task_id(task_id)
    return f"translation-shadow-cache/{task_id}/gemini/checkpoint.json"


def github_checkpoint_raw_url(task_id: str):
    path = github_checkpoint_path(task_id)
    return (
        f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/"
        f"{GITHUB_REF}/{path}"
    )


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json_atomic(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp.replace(path)
    return path


def load_github_checkpoint(task_id: str, timeout=20):
    """Read the exact public GitHub checkpoint path. No fuzzy search."""
    url = github_checkpoint_raw_url(task_id)
    sep = "&" if "?" in url else "?"
    request = urllib.request.Request(
        url + sep + "_t=" + str(int(time.time())),
        headers={"Cache-Control": "no-cache"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        print(
            "[CHECKPOINT] GitHub 已載入："
            + github_checkpoint_path(task_id),
            flush=True,
        )
        return payload
    except urllib.error.HTTPError as exc:
        if int(exc.code) == 404:
            return None
        print(f"[CHECKPOINT] GitHub 讀取失敗：HTTP {exc.code}", flush=True)
        return None
    except Exception as exc:
        print(f"[CHECKPOINT] GitHub 讀取失敗：{exc}", flush=True)
        return None


def publish_github_checkpoint(task_id: str, payload):
    """Publish through the authenticated Studio runtime bridge when available."""
    task_id = _normalize_task_id(task_id)
    bridge_url = str(os.environ.get("SOULKEY_BRIDGE_URL") or "").strip()
    nonce = str(os.environ.get("SOULKEY_RUNTIME_NONCE") or "").strip()

    if not bridge_url or not nonce:
        return {
            "ok": False,
            "skipped": True,
            "reason": "bridge_unavailable",
            "path": github_checkpoint_path(task_id),
        }

    raw = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    content_b64 = base64.b64encode(raw).decode("ascii")
    data = urllib.parse.urlencode({
        "action": "worker_translation_checkpoint_publish",
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
        result = json.loads(response.read().decode("utf-8"))

    if not result.get("ok"):
        raise RuntimeError(
            "GitHub checkpoint 發佈失敗："
            + str(result.get("message") or result.get("error") or result)
        )

    print(
        "[CHECKPOINT] GitHub 已更新："
        + str(result.get("path") or github_checkpoint_path(task_id)),
        flush=True,
    )
    return result


def load_drive_checkpoint(drive, translation_folder_id: str, workdir):
    item = find_file(drive, translation_folder_id, DRIVE_CHECKPOINT_NAME)
    if not item:
        return None

    local_path = Path(workdir) / DRIVE_CHECKPOINT_NAME
    download_drive_file(drive, item["id"], local_path)
    payload = _read_json(local_path)
    print(
        "[CHECKPOINT] Drive 已載入：02_翻譯稿/" + DRIVE_CHECKPOINT_NAME,
        flush=True,
    )
    return payload


def save_drive_checkpoint(drive, translation_folder_id: str, local_path):
    result = upload_or_replace_file(
        drive,
        translation_folder_id,
        str(local_path),
        DRIVE_CHECKPOINT_NAME,
    )
    print(
        "[CHECKPOINT] Drive 已更新：02_翻譯稿/" + DRIVE_CHECKPOINT_NAME,
        flush=True,
    )
    return result


def load_persistent_checkpoint(
    task_id: str,
    *,
    drive=None,
    translation_folder_id=None,
    workdir="/kaggle/working",
):
    """Load in deterministic order: GitHub -> Drive -> local.

    GitHub is preferred for Studio-launched runs. Manual Kaggle runs normally
    fall back to Drive, which survives runtime resets without another secret.
    """
    task_id = _normalize_task_id(task_id)

    payload = load_github_checkpoint(task_id)
    if payload is not None:
        return payload, "github"

    if drive is not None and translation_folder_id:
        payload = load_drive_checkpoint(
            drive,
            translation_folder_id,
            workdir,
        )
        if payload is not None:
            return payload, "drive"

    local_path = Path(workdir) / DRIVE_CHECKPOINT_NAME
    if local_path.exists():
        print("[CHECKPOINT] 僅找到 local checkpoint", flush=True)
        return _read_json(local_path), "local"

    return None, None


def save_persistent_checkpoint(
    task_id: str,
    payload,
    *,
    drive=None,
    translation_folder_id=None,
    workdir="/kaggle/working",
    require_persistent=True,
):
    """Save locally first, then persistent backends.

    Manual Kaggle: Drive is the persistent backend.
    Studio worker: Drive + GitHub bridge are both updated.
    """
    task_id = _normalize_task_id(task_id)
    local_path = _write_json_atomic(
        Path(workdir) / DRIVE_CHECKPOINT_NAME,
        payload,
    )

    result = {
        "local": str(local_path),
        "drive": None,
        "github": None,
    }
    persistent_ok = False

    if drive is not None and translation_folder_id:
        result["drive"] = save_drive_checkpoint(
            drive,
            translation_folder_id,
            local_path,
        )
        persistent_ok = True

    github_result = publish_github_checkpoint(task_id, payload)
    result["github"] = github_result
    if github_result.get("ok"):
        persistent_ok = True

    if require_persistent and not persistent_ok:
        raise RuntimeError(
            "Checkpoint 只有寫入 /kaggle/working，沒有任何永久後端。"
            "請提供 Drive translation folder，或由 Studio runtime bridge 執行。"
        )

    return result
