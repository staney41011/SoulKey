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
        self.expiry = datetime.now(timezone.utc) + timedelta(minutes=45)

    def refresh(self, request):
        if not self._bridge_url or not self._runtime_nonce:
            raise RuntimeError("SoulKey Bridge refresh context is missing")

        query = urllib.parse.urlencode({
            "action": "worker_runtime",
            "nonce": self._runtime_nonce,
            "_t": str(int(datetime.now(timezone.utc).timestamp())),
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
        self.expiry = datetime.now(timezone.utc) + timedelta(minutes=45)
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
            fields="files(id,name,mimeType)",
            pageSize=20,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )
    files = result.get("files", [])
    return files[0] if files else None


def upload_or_replace_file(drive, parent_id: str, local_path: str, drive_name: str = None):
    local_path = str(local_path)
    drive_name = drive_name or Path(local_path).name
    mime = mimetypes.guess_type(drive_name)[0] or "application/octet-stream"
    media = MediaFileUpload(local_path, mimetype=mime, resumable=True)

    existing = find_file(drive, parent_id, drive_name)
    if existing:
        return (
            drive.files()
            .update(
                fileId=existing["id"],
                media_body=media,
                fields="id,name,webViewLink",
                supportsAllDrives=True,
            )
            .execute()
        )

    return (
        drive.files()
        .create(
            body={"name": drive_name, "parents": [parent_id]},
            media_body=media,
            fields="id,name,webViewLink",
            supportsAllDrives=True,
        )
        .execute()
    )
