import re
import subprocess
from pathlib import Path

from google_io import download_drive_file, list_child_files

SUPPORTED_EXTENSIONS = {
    ".mp4", ".mov", ".m4v", ".mkv", ".webm",
    ".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg",
}


def find_drive_source(drive, folder_id: str):
    files = list_child_files(drive, folder_id)
    candidates = []
    for item in files:
        name = item.get("name") or ""
        mime = item.get("mimeType") or ""
        suffix = Path(name).suffix.lower()
        if mime.startswith("video/") or mime.startswith("audio/") or suffix in SUPPORTED_EXTENSIONS:
            candidates.append(item)

    if not candidates:
        return None

    candidates.sort(
        key=lambda x: x.get("modifiedTime") or "",
        reverse=True,
    )
    return candidates[0]


def _safe_filename(name: str):
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name or "source")
    return name[-180:]


def prepare_drive_audio(drive, source_file: dict, workdir: Path):
    workdir.mkdir(parents=True, exist_ok=True)
    original_name = source_file.get("name") or "source_media"
    local_source = workdir / _safe_filename(original_name)

    download_drive_file(
        drive,
        source_file["id"],
        local_source,
    )

    normalized = workdir / "audio_16k_mono.wav"
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(local_source),
            "-vn",
            "-ac", "1",
            "-ar", "16000",
            str(normalized),
        ],
        check=True,
    )

    metadata = {
        "source_type": "google_drive",
        "drive_file_id": source_file.get("id"),
        "drive_file_name": original_name,
        "mime_type": source_file.get("mimeType"),
        "modified_time": source_file.get("modifiedTime"),
    }
    return normalized, metadata
