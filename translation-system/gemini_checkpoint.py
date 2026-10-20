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

# Drive is the primary checkpoint. Mirror to GitHub periodically and on completion.
_ACTIONS_MIRROR_INTERVAL_SECONDS = 600
_actions_last_mirror = {}


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


def _publish_github_with_actions_token(task_id: str, payload, token: str):
    """Write via scoped ephemeral Actions token, without logging credentials."""
    path = github_checkpoint_path(task_id)
    url = (
        f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/"
        f"contents/{path}"
    )
    encoded = base64.b64encode(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "SoulKey-Checkpoint-Mirror",
    }
    last_error = None
    for attempt in range(3):
        try:
            sha = ""
            request = urllib.request.Request(
                url + "?ref=" + GITHUB_REF, headers=headers
            )
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    metadata = json.loads(response.read().decode("utf-8"))
                    sha = str(metadata.get("sha") or "")
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    raise
            body = {
                "message": "Checkpoint mirror " + task_id,
                "content": encoded,
                "branch": GITHUB_REF,
            }
            if sha:
                body["sha"] = sha
            write = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers={**headers, "Content-Type": "application/json"},
                method="PUT",
            )
            with urllib.request.urlopen(write, timeout=45) as response:
                if response.status not in (200, 201):
                    raise RuntimeError("GitHub checkpoint PUT returned unexpected status")
                result = json.loads(response.read().decode("utf-8"))
            if not result.get("content", {}).get("sha"):
                raise RuntimeError("GitHub checkpoint PUT returned no content SHA")
            return {"ok": True, "path": path, "backend": "actions_token"}
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise RuntimeError(
                    "GitHub Actions checkpoint denied (HTTP "
                    + str(exc.code)
                    + "); verify CPU job contents: write"
                ) from exc
            if exc.code not in (408, 409, 422, 429, 500, 502, 503, 504):
                raise
            last_error = exc
        except (TimeoutError, ConnectionError, OSError) as exc:
            last_error = exc
        if attempt < 2:
            time.sleep(2 ** attempt)
    raise RuntimeError(
        "GitHub Actions checkpoint mirror temporarily unavailable after 3 attempts"
    ) from last_error


def publish_github_checkpoint(task_id: str, payload, *, force=False):
    """Publish via scoped Actions credential or the legacy Bridge fallback."""
    task_id = _normalize_task_id(task_id)
    actions_token = str(os.environ.get("SOULKEY_GITHUB_ACTIONS_TOKEN") or "").strip()
    if actions_token:
        previous = _actions_last_mirror.get(task_id)
        due = previous is None or (
            time.monotonic() - previous >= _ACTIONS_MIRROR_INTERVAL_SECONDS
        )
        final = str(payload.get("status") or "").lower() == "complete"
        if not final and not due and not force:
            return {"ok": False, "skipped": True, "reason": "throttled"}
        result = _publish_github_with_actions_token(task_id, payload, actions_token)
        _actions_last_mirror[task_id] = time.monotonic()
        print("[CHECKPOINT] GitHub Actions mirror 已更新：" +
              github_checkpoint_path(task_id), flush=True)
        return result
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
        detail = (
            result.get("message")
            or result.get("error")
            or result
        )
        status = result.get("github_status")
        body = result.get("github_body")
        raise RuntimeError(
            "GitHub checkpoint 發佈失敗："
            + str(detail)
            + (f"；status={status}" if status else "")
            + (f"；body={body}" if body else "")
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
    """Load all deterministic backends and choose the newest checkpoint.

    checkpoint_seq is authoritative when present. This avoids a stale GitHub
    copy hiding a newer Drive copy after a manual Kaggle run.
    """
    task_id = _normalize_task_id(task_id)
    candidates = []

    github_payload = load_github_checkpoint(task_id)
    if github_payload is not None:
        candidates.append(("github", github_payload))

    if drive is not None and translation_folder_id:
        try:
            drive_payload = load_drive_checkpoint(
                drive,
                translation_folder_id,
                workdir,
            )
            if drive_payload is not None:
                candidates.append(("drive", drive_payload))
        except Exception as exc:
            if github_payload is None:
                raise
            print(
                "[CHECKPOINT] Drive 讀取中斷；從 GitHub 永久備份恢復："
                + type(exc).__name__,
                flush=True,
            )

    local_path = Path(workdir) / DRIVE_CHECKPOINT_NAME
    if local_path.exists():
        try:
            candidates.append(("local", _read_json(local_path)))
        except Exception as exc:
            print(f"[CHECKPOINT] local checkpoint 無法解析：{exc}", flush=True)

    if not candidates:
        return None, None

    def rank(item):
        source, payload = item
        try:
            seq = int(payload.get("checkpoint_seq") or 0)
        except Exception:
            seq = 0
        updated = str(payload.get("updated_at") or "")
        persistent_bonus = 1 if source in {"github", "drive"} else 0
        return (seq, updated, persistent_bonus)

    source, payload = max(candidates, key=rank)
    print(
        f"[CHECKPOINT] 採用 {source} checkpoint；"
        f"seq={payload.get('checkpoint_seq', 0)}",
        flush=True,
    )
    return payload, source


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

    drive_error = None
    if drive is not None and translation_folder_id:
        try:
            result["drive"] = save_drive_checkpoint(
                drive,
                translation_folder_id,
                local_path,
            )
            persistent_ok = True
        except Exception as exc:
            drive_error = exc
            result["drive"] = {"ok": False, "error": type(exc).__name__}
            print(
                "[CHECKPOINT] Drive 暫時無法保存；嘗試 GitHub 後備："
                + type(exc).__name__,
                flush=True,
            )

    try:
        # If Drive failed, bypass normal 10-minute GitHub throttling.
        github_result = publish_github_checkpoint(
            task_id, payload, force=not persistent_ok
        )
        result["github"] = github_result
        if github_result.get("ok"):
            persistent_ok = True
    except Exception as exc:
        # GitHub is a secondary mirror. A successful Drive checkpoint is already
        # durable and must never be turned into a failed translation job merely
        # because the GitHub mirror could not be updated.
        result["github"] = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
        print(
            "[CHECKPOINT] GitHub mirror 更新失敗，但 Drive checkpoint 已保留："
            + str(exc),
            flush=True,
        )

    if require_persistent and not persistent_ok:
        raise RuntimeError(
            "Checkpoint 只有寫入工作目錄：Drive 與 GitHub 均未保存成功。"
            "請稍後從上次永久檢查點續跑。"
        ) from drive_error

    return result
