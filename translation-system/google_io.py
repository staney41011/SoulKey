import io
import json
import mimetypes
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials


class BridgeCredentials(Credentials):
    """Short-lived Apps Script OAuth token that can renew itself via worker_runtime."""

    def __init__(self, token: str, bridge_url: str, runtime_nonce: str):
        super().__init__(token=token)
        self._bridge_url = str(bridge_url or "").strip()
        self._runtime_nonce = str(runtime_nonce or "").strip()
        # Apps Script OAuth tokens are short lived. Refresh a little early.
        self.expiry = datetime.utcnow() + timedelta(minutes=45)

    def refresh(self, request):
        if not self._bridge_url or not self._runtime_nonce:
            raise RuntimeError("SoulKey Bridge refresh context is missing")

        query = urllib.parse.urlencode({
            "action": "worker_runtime",
            "nonce": self._runtime_nonce,
            "_t": str(int(datetime.utcnow().timestamp())),
        })
        url = self._bridge_url + ("&" if "?" in self._bridge_url else "?") + query
        with urllib.request.urlopen(url, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))

        if not payload.get("ok"):
            raise RuntimeError(
                "SoulKey Bridge OAuth refresh failed: "
                + str(payload.get("message") or payload.get("error") or payload)
            )

        token = str(payload.get("google_access_token") or "").strip()
        if not token:
            raise RuntimeError("SoulKey Bridge OAuth refresh returned no token")

        self.token = token
        self.expiry = datetime.utcnow() + timedelta(minutes=45)
        print("[Google] SoulKey Bridge OAuth token 已自動更新", flush=True)
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload


# ---------------------------------------------------------------------------
# SoulKey Drive display naming
# ---------------------------------------------------------------------------
_DRIVE_NAMING_CONTEXT = None

_LANGUAGE_LABELS = {
    "zh-TW": "中文",
    "zh-Hant": "中文",
    "en": "英文",
    "en-US": "英文",
    "th": "泰文",
    "es": "西班牙文",
    "id": "印尼文",
    "vi": "越南文",
    "sd": "信德文",
    "ta": "泰米爾文",
}


def _clean_drive_component(value: str):
    value = str(value or "").strip()
    value = re.sub(r"[\\/\r\n\t]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    value = value.replace("_", "－")
    return value[:120].strip(" .") or "未命名"


def configure_drive_naming(task: dict):
    """Set the lesson-level display-name context for subsequent Drive I/O."""
    global _DRIVE_NAMING_CONTEXT
    task = dict(task or {})
    period = re.sub(r"\D+", "", str(task.get("period") or ""))
    lesson = re.sub(r"\D+", "", str(task.get("lesson") or ""))
    raw_title = str(task.get("title") or "").strip()
    lecturer = str(task.get("lecturer") or "").strip()

    # YouTube course titles commonly follow:
    # 課程名稱 | 講師 | 打開心靈的鎖匙XXX期
    title_parts = [x.strip() for x in re.split(r"[｜|]", raw_title) if x.strip()]
    title = title_parts[0] if title_parts else raw_title
    if len(title_parts) >= 2:
        speaker_segment = title_parts[1]
        # Plain personal names such as 賴義鍠 should beat a channel fallback
        # such as 白陽文化. Teacher aliases (中和老師 etc.) are already
        # normalized by youtube_io, so keep the task lecturer for those.
        if (
            re.fullmatch(r"[\u4e00-\u9fff·]{2,8}", speaker_segment)
            and not speaker_segment.endswith("老師")
        ):
            lecturer = speaker_segment

    if not period or not lesson or not title or not lecturer:
        _DRIVE_NAMING_CONTEXT = None
        return None

    _DRIVE_NAMING_CONTEXT = {
        "period": period,
        "lesson": lesson,
        "title": _clean_drive_component(title),
        "lecturer": _clean_drive_component(lecturer),
    }
    return dict(_DRIVE_NAMING_CONTEXT)


def _split_extension(name: str):
    lower = name.lower()
    for ext in [".tts_manifest.json", ".segments.zip"]:
        if lower.endswith(ext):
            return name[:-len(ext)], ext
    suffixes = Path(name).suffixes
    if not suffixes:
        return name, ""
    ext = "".join(suffixes[-1:])
    return name[:-len(ext)], ext


def _content_label(logical_name: str):
    name = Path(str(logical_name)).name
    stem, ext = _split_extension(name)

    fixed = {
        "source_info": "來源資訊",
        "youtube.en": "YouTube英文字幕資料",
        "youtube-audio-manifest": "YouTube音軌資訊",
        "segments": "中文逐字稿資料",
        "zh-TW": "中文逐字稿" if ext != ".srt" else "中文逐字稿字幕",
        "zh-TW.polished": "中文AI校稿" if ext != ".srt" else "中文AI校稿字幕",
        "zh-TW.readable": "中文易讀稿",
        "polish_report": "中文校稿報告",
        "zh-TW.review-cache": "中文人工校稿快取",
        "zh-TW.final": "中文定稿字幕" if ext == ".srt" else ("中文定稿資料" if ext == ".json" else "中文定稿"),
        "zh-TW.vernacular": "中文白話稿字幕" if ext == ".srt" else ("中文白話稿資料" if ext == ".json" else "中文白話稿"),
        "zh-TW.vernacular.final": "中文白話定稿字幕" if ext == ".srt" else ("中文白話定稿資料" if ext == ".json" else "中文白話定稿"),
        "subtitle_manifest": "字幕資訊",
    }
    if stem in fixed:
        return fixed[stem]

    # YouTube source audio: youtube.en-US.mp3 / youtube.zh-Hant.mp3
    m = re.fullmatch(r"youtube\.([A-Za-z-]+)", stem)
    if m:
        lang = _LANGUAGE_LABELS.get(m.group(1), m.group(1))
        return f"{lang}音檔"

    # TTS manifests and segmented audio archives.
    m = re.fullmatch(r"([A-Za-z-]+)", stem)
    if m and ext == ".tts_manifest.json":
        lang = _LANGUAGE_LABELS.get(m.group(1), m.group(1))
        return f"{lang}音檔資訊"
    if m and ext == ".segments.zip":
        lang = _LANGUAGE_LABELS.get(m.group(1), m.group(1))
        return f"{lang}分段音檔"

    # Translation / subtitle / audio files.
    m = re.fullmatch(r"([A-Za-z-]+)(\.final)?", stem)
    if m:
        code = m.group(1)
        lang = _LANGUAGE_LABELS.get(code, code)
        is_final = bool(m.group(2))
        if ext in {".mp3", ".wav", ".m4a"}:
            return f"{lang}音檔"
        if ext == ".srt":
            return f"{lang}{'定稿' if is_final else ''}字幕"
        if ext == ".json":
            return f"{lang}{'定稿' if is_final else ''}翻譯資料"
        if ext == ".txt":
            return f"{lang}{'定稿' if is_final else ''}翻譯稿"

    # Unknown system artifacts still get the lesson prefix and preserve their
    # original stem as the content descriptor instead of being left unnamed.
    return _clean_drive_component(stem)


def drive_display_name(logical_name: str):
    logical_name = Path(str(logical_name)).name
    if not _DRIVE_NAMING_CONTEXT:
        return logical_name
    ctx = _DRIVE_NAMING_CONTEXT
    _, ext = _split_extension(logical_name)
    label = _content_label(logical_name)
    return (
        f"第{ctx['period']}期_第{ctx['lesson']}堂課_"
        f"{ctx['title']}_{ctx['lecturer']}_{label}{ext}"
    )


def _find_by_logical_property(drive, parent_id: str, logical_name: str):
    safe_logical = _escape_query(Path(str(logical_name)).name)
    query = (
        f"'{parent_id}' in parents and trashed = false and "
        f"appProperties has {{ key='soulkey_logical_name' and value='{safe_logical}' }}"
    )
    result = (
        drive.files()
        .list(
            q=query,
            spaces="drive",
            fields="files(id,name,mimeType,appProperties)",
            pageSize=20,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )
    files = result.get("files", [])
    return files[0] if files else None


def normalize_lesson_files(drive, folders: dict, task: dict):
    """Rename existing lesson artifacts in-place to the canonical display format."""
    if not configure_drive_naming(task):
        print("[Drive Naming] 課程名稱或講師尚未就緒；暫不重新命名。", flush=True)
        return 0

    changed = 0
    for folder_key, parent_id in (folders or {}).items():
        if folder_key == "lesson" or not parent_id:
            continue
        query = f"'{parent_id}' in parents and trashed = false"
        result = (
            drive.files()
            .list(
                q=query,
                spaces="drive",
                fields="files(id,name,mimeType,appProperties)",
                pageSize=1000,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        for item in result.get("files", []):
            if item.get("mimeType") == "application/vnd.google-apps.folder":
                continue
            props = dict(item.get("appProperties") or {})
            logical = str(props.get("soulkey_logical_name") or "").strip()
            if not logical:
                current_name = str(item.get("name") or "")
                # For legacy files the current name is the logical filename.
                # Already-prefixed files without metadata are left intact to
                # avoid guessing a lost logical identity.
                if current_name.startswith(f"第{_DRIVE_NAMING_CONTEXT['period']}期_"):
                    continue
                logical = current_name
            target = drive_display_name(logical)
            update_body = {
                "name": target,
                "appProperties": {**props, "soulkey_logical_name": logical},
            }
            if item.get("name") != target or props.get("soulkey_logical_name") != logical:
                drive.files().update(
                    fileId=item["id"],
                    body=update_body,
                    fields="id,name,appProperties",
                    supportsAllDrives=True,
                ).execute()
                changed += 1
    print(f"[Drive Naming] 已重新命名／標記 {changed} 個既有檔案。", flush=True)
    return changed


def get_secret(name: str, required: bool = True):
    value = os.environ.get(name)
    if value:
        return value

    try:
        from kaggle_secrets import UserSecretsClient
        value = UserSecretsClient().get_secret(name)
        if value:
            return value
    except Exception:
        pass

    if required:
        raise RuntimeError(
            f"找不到 Secret: {name}。請在 Kaggle Add-ons > Secrets 建立它。"
        )
    return None


def build_google_services():
    access_token = os.environ.get("GOOGLE_ACCESS_TOKEN", "").strip()

    if access_token:
        print("[Google] 使用 SoulKey Bridge 提供的短效 OAuth access token")
        bridge_url = os.environ.get("SOULKEY_BRIDGE_URL", "").strip()
        runtime_nonce = os.environ.get("SOULKEY_RUNTIME_NONCE", "").strip()
        if bridge_url and runtime_nonce:
            creds = BridgeCredentials(
                token=access_token,
                bridge_url=bridge_url,
                runtime_nonce=runtime_nonce,
            )
        else:
            creds = Credentials(token=access_token)
    else:
        client_id = get_secret("GOOGLE_CLIENT_ID")
        client_secret = get_secret("GOOGLE_CLIENT_SECRET")
        refresh_token = get_secret("GOOGLE_REFRESH_TOKEN")

        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
        )
        creds.refresh(Request())

    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    return drive, sheets


def read_values(sheets, spreadsheet_id: str, a1_range: str):
    result = (
        sheets.spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range=a1_range,
            valueRenderOption="FORMATTED_VALUE",
        )
        .execute()
    )
    return result.get("values", [])


def update_cells(sheets, spreadsheet_id: str, updates: dict):
    data = [{"range": rng, "values": [[value]]} for rng, value in updates.items()]
    if not data:
        return
    (
        sheets.spreadsheets()
        .values()
        .batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": "USER_ENTERED", "data": data},
        )
        .execute()
    )


def extract_drive_id(url: str):
    if not url:
        return None
    match = re.search(r"/folders/([A-Za-z0-9_-]+)", url)
    if match:
        return match.group(1)
    match = re.search(r"/d/([A-Za-z0-9_-]+)", url)
    return match.group(1) if match else None


def _escape_query(value: str):
    return value.replace("\\", "\\\\").replace("'", "\\'")


def find_child_folder(drive, parent_id: str, name: str):
    safe_name = _escape_query(name)
    query = (
        f"'{parent_id}' in parents and "
        f"name = '{safe_name}' and "
        "mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    result = (
        drive.files()
        .list(
            q=query,
            spaces="drive",
            fields="files(id,name)",
            pageSize=20,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )
    files = result.get("files", [])
    return files[0]["id"] if files else None


def require_child_folder(drive, parent_id: str, name: str):
    folder_id = find_child_folder(drive, parent_id, name)
    if not folder_id:
        raise RuntimeError(f"找不到資料夾：{name} (parent={parent_id})")
    return folder_id


def list_child_files(drive, parent_id: str):
    query = f"'{parent_id}' in parents and trashed = false"
    files = []
    page_token = None
    while True:
        result = (
            drive.files()
            .list(
                q=query,
                spaces="drive",
                fields="nextPageToken,files(id,name,mimeType,size,modifiedTime)",
                pageSize=100,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        files.extend(result.get("files", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return files


def download_drive_file(drive, file_id: str, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    request = drive.files().get_media(
        fileId=file_id,
        supportsAllDrives=True,
    )
    with destination.open("wb") as fh:
        downloader = MediaIoBaseDownload(
            fh,
            request,
            chunksize=16 * 1024 * 1024,
        )
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status:
                print(f"[Drive] 下載 {status.progress() * 100:.1f}%")

    return destination


def find_file(drive, parent_id: str, name: str):
    logical_name = Path(str(name)).name

    # New canonical files are keyed by appProperties so internal code can keep
    # asking for stable logical names such as segments.json / en.final.json.
    by_property = _find_by_logical_property(drive, parent_id, logical_name)
    if by_property:
        return by_property

    # Legacy exact-name lookup remains for files not migrated yet.
    candidates = [logical_name]
    display_name = drive_display_name(logical_name)
    if display_name not in candidates:
        candidates.append(display_name)

    for candidate in candidates:
        safe_name = _escape_query(candidate)
        query = (
            f"'{parent_id}' in parents and "
            f"name = '{safe_name}' and trashed = false"
        )
        result = (
            drive.files()
            .list(
                q=query,
                spaces="drive",
                fields="files(id,name,mimeType,appProperties)",
                pageSize=20,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        files = result.get("files", [])
        if files:
            return files[0]
    return None


def upload_or_replace_file(drive, parent_id: str, local_path: str, drive_name: str = None):
    local_path = str(local_path)
    logical_name = Path(str(drive_name or Path(local_path).name)).name
    display_name = drive_display_name(logical_name)
    mime = mimetypes.guess_type(logical_name)[0] or "application/octet-stream"
    media = MediaFileUpload(local_path, mimetype=mime, resumable=True)

    existing = find_file(drive, parent_id, logical_name)
    body = {
        "name": display_name,
        "appProperties": {"soulkey_logical_name": logical_name},
    }
    if existing:
        existing_props = dict(existing.get("appProperties") or {})
        body["appProperties"] = {
            **existing_props,
            "soulkey_logical_name": logical_name,
        }
        return (
            drive.files()
            .update(
                fileId=existing["id"],
                body=body,
                media_body=media,
                fields="id,name,webViewLink,appProperties",
                supportsAllDrives=True,
            )
            .execute()
        )

    body["parents"] = [parent_id]
    return (
        drive.files()
        .create(
            body=body,
            media_body=media,
            fields="id,name,webViewLink,appProperties",
            supportsAllDrives=True,
        )
        .execute()
    )
