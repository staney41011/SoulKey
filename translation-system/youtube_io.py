import base64
import json
import re
import subprocess
from pathlib import Path

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from google_io import get_secret


LECTURER_PATTERNS = [
    r"(?:講師|主講人|主講|講者|授課老師|授課者)\s*[：:｜|]\s*([^\n｜|、,，;；]{2,30})",
    r"(?:講師|主講人|主講|講者|授課老師|授課者)\s+([^\n｜|、,，;；]{2,30})",
]

POT_SERVER_HOME = Path("/kaggle/working/bgutil-ytdlp-pot-provider/server")
POT_SCRIPT = POT_SERVER_HOME / "build" / "generate_once.js"


def _cookie_file(workdir: Path):
    value = get_secret("YOUTUBE_COOKIES_B64", required=False)
    if not value:
        return None

    try:
        raw = base64.b64decode(value)
    except Exception as exc:
        raise RuntimeError("YOUTUBE_COOKIES_B64 不是有效的 Base64") from exc

    path = workdir / "youtube_cookies.txt"
    path.write_bytes(raw)

    first_line = path.read_text(
        encoding="utf-8",
        errors="ignore",
    ).splitlines()[:1]
    if not first_line or first_line[0] not in {
        "# HTTP Cookie File",
        "# Netscape HTTP Cookie File",
    }:
        raise RuntimeError(
            "YouTube cookies 必須是 Mozilla/Netscape cookies.txt 格式。"
        )

    return str(path)


def _base_options(workdir: Path, quiet: bool):
    options = {
        "quiet": quiet,
        "no_warnings": quiet,
        "noplaylist": True,
    }

    cookiefile = _cookie_file(workdir)
    if cookiefile:
        options["cookiefile"] = cookiefile

    user_agent = get_secret("YOUTUBE_USER_AGENT", required=False)
    if user_agent:
        options["http_headers"] = {"User-Agent": user_agent}

    return options, bool(cookiefile)


def _pot_profile():
    if not POT_SCRIPT.exists():
        return None

    return {
        "youtube": {
            "player_client": ["mweb"],
        },
        "youtubepot-bgutilscript": {
            "server_home": [str(POT_SERVER_HOME)],
        },
    }


def _anonymous_profiles():
    return [
        {
            "youtube": {
                "player_client": ["web_embedded", "android_vr"],
            }
        },
        {
            "youtube": {
                "player_client": ["web_embedded", "android_vr"],
                "player_skip": ["webpage"],
            }
        },
    ]


def _extract_info(url: str, options: dict, download: bool, has_cookies: bool):
    if has_cookies:
        with YoutubeDL(options) as ydl:
            return ydl.extract_info(url, download=download)

    last_error = None

    pot = _pot_profile()
    if pot:
        attempt = dict(options)
        attempt["extractor_args"] = pot
        print("[YouTube] PO Token 模式：mweb + bgutil script provider")
        try:
            with YoutubeDL(attempt) as ydl:
                return ydl.extract_info(url, download=download)
        except DownloadError as exc:
            last_error = exc
            print("[YouTube] PO Token 模式失敗，改試匿名 fallback。")
    else:
        print(
            "[YouTube] 尚未安裝 PO Token Provider，"
            "可先執行 setup_pot_provider.py。"
        )

    for index, extractor_args in enumerate(_anonymous_profiles(), start=1):
        attempt = dict(options)
        attempt["extractor_args"] = extractor_args
        print(
            f"[YouTube] 匿名 fallback 第 {index} 層："
            f"{extractor_args['youtube']['player_client']}"
        )
        try:
            with YoutubeDL(attempt) as ydl:
                return ydl.extract_info(url, download=download)
        except DownloadError as exc:
            last_error = exc
            print(f"[YouTube] 匿名 fallback 第 {index} 層失敗。")

    if last_error:
        raise last_error
    raise RuntimeError("YouTube 取得失敗")


def detect_lecturer(info: dict):
    title = (info.get("title") or "").strip()
    description = (info.get("description") or "").strip()
    haystack = title + "\n" + description[:5000]

    for pattern in LECTURER_PATTERNS:
        match = re.search(pattern, haystack, flags=re.IGNORECASE)
        if match:
            lecturer = re.sub(r"\s+", " ", match.group(1)).strip(" -–—：:")
            if lecturer:
                return lecturer, "title_or_description"

    fallback = (
        info.get("channel")
        or info.get("uploader")
        or info.get("uploader_id")
        or ""
    )
    return str(fallback).strip(), "channel_or_uploader"


def extract_metadata(url: str, workdir: Path):
    workdir.mkdir(parents=True, exist_ok=True)
    options, has_cookies = _base_options(workdir, quiet=True)
    options["skip_download"] = True

    info = _extract_info(
        url=url,
        options=options,
        download=False,
        has_cookies=has_cookies,
    )

    lecturer, lecturer_source = detect_lecturer(info)
    return {
        "id": info.get("id"),
        "title": info.get("title") or "",
        "description": info.get("description") or "",
        "channel": info.get("channel") or "",
        "uploader": info.get("uploader") or "",
        "upload_date": info.get("upload_date") or "",
        "duration": info.get("duration"),
        "webpage_url": info.get("webpage_url") or url,
        "lecturer": lecturer,
        "lecturer_source": lecturer_source,
    }


def download_audio(url: str, workdir: Path):
    workdir.mkdir(parents=True, exist_ok=True)
    raw_template = str(workdir / "source.%(ext)s")

    options, has_cookies = _base_options(workdir, quiet=False)
    options.update(
        {
            "format": "bestaudio/best",
            "outtmpl": raw_template,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "wav",
                }
            ],
        }
    )

    info = _extract_info(
        url=url,
        options=options,
        download=True,
        has_cookies=has_cookies,
    )

    source_wav = workdir / "source.wav"
    if not source_wav.exists():
        candidates = list(workdir.glob("source.*"))
        if not candidates:
            raise RuntimeError("yt-dlp 完成但找不到下載後的音訊檔。")
        source_wav = candidates[0]

    normalized = workdir / "audio_16k_mono.wav"
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(source_wav),
        "-ac", "1",
        "-ar", "16000",
        str(normalized),
    ]
    subprocess.run(cmd, check=True)

    meta = {
        "id": info.get("id"),
        "title": info.get("title"),
        "duration": info.get("duration"),
        "webpage_url": info.get("webpage_url") or url,
    }
    return normalized, meta


def save_metadata_json(metadata: dict, path: Path):
    path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
