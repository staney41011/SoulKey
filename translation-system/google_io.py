import io
import hashlib
import time
import json
import mimetypes
import os
import re
import ssl
from http.client import RemoteDisconnected
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from drive_naming import (
    canonical_from_description,
    canonical_marker,
    output_label,
)

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
    """Retry transient TLS/HTTP faults; writing the same cells is idempotent.

    Google Sheets may commit a batch before an SSL connection breaks. Retrying
    identical cell values is safe, unlike blindly repeating a Drive CREATE.
    """
    data = [{"range": rng, "values": [[value]]} for rng, value in updates.items()]
    if not data:
        return
    for attempt in range(1, 5):
        try:
            (
                sheets.spreadsheets()
                .values()
                .batchUpdate(
                    spreadsheetId=spreadsheet_id,
                    body={"valueInputOption": "USER_ENTERED", "data": data},
                )
                .execute(num_retries=5)
            )
            return
        except Exception as exc:
            if not _transient_upload_error(exc):
                raise
            code = _upload_error_status(exc)
            print(
                f"[Sheets:WRITE-RETRY] HTTP {code or 'network'} "
                f"attempt {attempt}/4; retrying same {len(data)} cells",
                flush=True,
            )
            if attempt >= 4:
                raise RuntimeError(
                    "Google Sheets write interrupted after retries; "
                    "translation checkpoint remains in Drive for safe resume"
                ) from exc
            time.sleep(min(16.0, 2.0 ** attempt))


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
    """Find by legacy filename first, then by SoulKey canonical marker.

    Drive display names may be human-friendly.  The canonical marker stored in
    description keeps all existing pipeline lookups stable.
    """
    safe_name = _escape_query(name)
    query = (
        f"'{parent_id}' in parents and "
        f"name = '{safe_name}' and trashed = false"
    )
    result = (
        drive.files()
        .list(
            q=query,
            spaces="drive",
            fields="files(id,name,mimeType,description)",
            pageSize=20,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )
    files = result.get("files", [])
    if files:
        return files[0]

    # Formal Drive names are intentionally different from canonical technical
    # names.  Folders are small, so a parent-scoped fallback scan is cheap and
    # avoids changing every downstream reader.
    query = f"'{parent_id}' in parents and trashed = false"
    page_token = None
    while True:
        result = (
            drive.files()
            .list(
                q=query,
                spaces="drive",
                fields="nextPageToken,files(id,name,mimeType,description)",
                pageSize=200,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        formal_suffix = "_" + output_label(name)
        for item in result.get("files", []):
            if canonical_from_description(item.get("description")) == name:
                return item
            if str(item.get("name") or "").endswith(formal_suffix):
                return item
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return None


# Google Drive resumable writes intermittently fail with 502/503; the
# built-in googleapiclient execute() previously had zero HTTP retries.
# Do not recreate translations or checkpoints when the upload is transient.
_RETRYABLE_UPLOAD_HTTP = {408, 409, 429, 500, 502, 503, 504}


def _upload_error_status(exc):
    try:
        return int(getattr(getattr(exc, "resp", None), "status", 0))
    except (TypeError, ValueError):
        return 0


def _transient_upload_error(exc):
    if _upload_error_status(exc) in _RETRYABLE_UPLOAD_HTTP:
        return True
    return isinstance(exc, (TimeoutError, ConnectionError, ssl.SSLError, RemoteDisconnected))


def _uploaded_matches(drive, item, local_path):
    """Confirm a prior ambiguous Drive commit before repeating a CREATE."""
    if not item or not item.get("id"):
        return False
    try:
        metadata = drive.files().get(
            fileId=item["id"], fields="id,size,md5Checksum,name,description",
            supportsAllDrives=True,
        ).execute(num_retries=3)
        if int(metadata.get("size") or 0) != Path(local_path).stat().st_size:
            return False
        local_md5 = hashlib.md5()
        with open(local_path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                local_md5.update(chunk)
        return str(metadata.get("md5Checksum") or "").lower() == local_md5.hexdigest()
    except Exception:
        return False


def upload_or_replace_file(
    drive,
    parent_id: str,
    local_path: str,
    drive_name: str = None,
    display_name: str = None,
):
    """Idempotent Drive upload with bounded 5xx retry and verified recovery.

    Recover an ambiguous successful create using file size + MD5 before
    attempting to write again. Rebuild the media on each retry so a failed
    resumable session is never reused. Canonical filenames stay unchanged.
    """
    local_path = str(local_path)
    canonical_name = drive_name or Path(local_path).name
    final_name = display_name or canonical_name
    mime = mimetypes.guess_type(canonical_name)[0] or "application/octet-stream"
    description = canonical_marker(canonical_name)
    last_error = None

    for attempt in range(1, 4):
        try:
            # A fresh lookup on every attempt protects already-committed CREATEs.
            existing = find_file(drive, parent_id, canonical_name)
            if attempt > 1 and existing and _uploaded_matches(drive, existing, local_path):
                print(f"[Drive:UPLOAD] {canonical_name}: verified existing bytes after retry", flush=True)
                return {"id": existing["id"], "name": final_name, "description": description}
            media = MediaFileUpload(local_path, mimetype=mime, resumable=True)
            if existing:
                request = drive.files().update(
                    fileId=existing["id"],
                    body={"name": final_name, "description": description},
                    media_body=media,
                    fields="id,name,webViewLink,description",
                    supportsAllDrives=True,
                )
            else:
                request = drive.files().create(
                    body={
                        "name": final_name,
                        "parents": [parent_id],
                        "description": description,
                    },
                    media_body=media,
                    fields="id,name,webViewLink,description",
                    supportsAllDrives=True,
                )
            # googleapiclient also retries transient responses within one
            # resumable session; the outer loop restarts a broken session.
            result = request.execute(num_retries=5)
            if not result or not result.get("id"):
                raise RuntimeError("Drive upload did not return a file ID")
            return result
        except Exception as exc:
            if not _transient_upload_error(exc):
                raise
            last_error = exc
            code = _upload_error_status(exc)
            print(
                f"[Drive:UPLOAD-RETRY] {canonical_name}: HTTP {code or 'network'} "
                f"attempt {attempt}/3; local manuscript/checkpoint retained",
                flush=True,
            )
            if attempt < 3:
                time.sleep(min(8.0, 2.0 ** attempt))
    raise RuntimeError(
        f"Google Drive upload temporarily unavailable after retries: "
        f"HTTP {_upload_error_status(last_error) or 'network'} "
        f"file={canonical_name}; rerun resumes from checkpoint"
    ) from last_error
