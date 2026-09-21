import base64
import json
import re
import subprocess
from pathlib import Path

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from google_io import get_secret


LECTURER_ALIASES = {
    "中和老師": "翁樞紐",
}

LECTURER_PATTERNS = [
    r"(?:講師|主講人|主講|講者|授課老師|授課者)\s*[：:｜|]\s*([^\n｜|、,，;；]{2,30})",
    r"(?:講師|主講人|主講|講者|授課老師|授課者)\s+([^\n｜|、,，;；]{2,30})",
]

WPC_BROWSER_MARKER = Path("/kaggle/working/wpc_browser_path.txt")
DENO_MARKER = Path("/kaggle/working/deno_path.txt")
_WPC_PATCHED = False


def _patch_wpc_for_kaggle():
    """Patch installed WPC source without importing the plugin twice."""
    global _WPC_PATCHED
    if _WPC_PATCHED:
        return

    import sys

    rel = Path("yt_dlp_plugins/extractor/getpot_wpc.py")
    for base in map(Path, sys.path):
        candidate = base / rel
        if not candidate.exists():
            continue

        try:
            text = candidate.read_text(encoding="utf-8")

            patched_signature = "headless=True,"
            if patched_signature in text and "sandbox=False" in text:
                _WPC_PATCHED = True
                print("[YouTube] WPC Kaggle patch：headless + no-sandbox")
                return

            old = """return nodriver.core.config.Config(
            headless=False,
            browser_executable_path=browser_executable_path,
            browser_args=browser_args
        )"""
            new = """return nodriver.core.config.Config(
            headless=True,
            browser_executable_path=browser_executable_path,
            browser_args=browser_args,
            sandbox=False,
        )"""

            if old in text:
                candidate.write_text(text.replace(old, new), encoding="utf-8")
                _WPC_PATCHED = True
                print("[YouTube] WPC Kaggle patch：headless + no-sandbox")
                return
        except Exception as exc:
            print(f"[YouTube] WPC Kaggle patch 警告：{type(exc).__name__}: {exc}")
            return

    print("[YouTube] WPC Kaggle patch 警告：找不到 provider 原始碼")


def _cookie_file(workdir: Path):
    value = get_secret("YOUTUBE_COOKIES_B64", required=False)
    if not value:
        return None

    # 容錯支援兩種輸入：
    # 1) 正式 Base64 cookies.txt
    # 2) 使用者不小心直接貼入 Netscape cookies.txt 原文
    text = str(value).strip()
    raw = None

    if (
        text.startswith("# Netscape HTTP Cookie File")
        or "\t.youtube.com\t" in text
        or "\t.google.com\t" in text
    ):
        raw = text.encode("utf-8")
        print("[YouTube] Cookies：偵測到原始 cookies.txt，直接使用。")
    else:
        compact = "".join(text.split())
        # Base64 常因複製貼上少了尾端 = padding；自動補齊。
        compact += "=" * ((4 - len(compact) % 4) % 4)
        try:
            raw = base64.b64decode(compact, validate=False)
        except Exception as exc:
            raise RuntimeError(
                "YOUTUBE_COOKIES_B64 無法解析。請貼入 cookies.txt 的 Base64，"
                "或直接貼入完整 Netscape cookies.txt 內容。"
            ) from exc

    if not raw or len(raw) < 32:
        raise RuntimeError("YouTube Cookies 內容過短或為空。")

    path = workdir / "youtube_cookies.txt"
    path.write_bytes(raw)
    print(f"[YouTube] Cookies：已寫入 {path}（{len(raw)} bytes）")
    return str(path)


def _base_options(workdir: Path, quiet: bool):
    _patch_wpc_for_kaggle()

    options = {
        "quiet": quiet,
        "no_warnings": quiet,
        "noplaylist": True,
        "socket_timeout": 20,
        "retries": 1,
        "fragment_retries": 1,
        "extractor_retries": 1,
        # Allow yt-dlp to fetch the matching EJS challenge bundle through npm.
        # This is only used when YouTube presents an n/JS challenge.
        "remote_components": {"ejs:npm"},
    }

    if DENO_MARKER.exists():
        deno = DENO_MARKER.read_text(encoding="utf-8").strip()
        if deno and Path(deno).exists():
            options["js_runtimes"] = {"deno": {"path": deno}}

    cookiefile = _cookie_file(workdir)
    if cookiefile:
        options["cookiefile"] = cookiefile

    return options, bool(cookiefile)


def _wpc_profile():
    if not WPC_BROWSER_MARKER.exists():
        return None
    browser = WPC_BROWSER_MARKER.read_text(encoding="utf-8").strip()
    if not browser or not Path(browser).exists():
        return None

    return {
        "youtube": {
            "player_client": ["mweb"],
            "fetch_pot": ["always"],
        },
        "youtubepot-wpc": {
            "browser_path": [browser],
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
        last_error = None

        # Fast path: valid login cookies usually do not need Chromium / WPC.
        print("[YouTube] Cookies 快速模式：direct")
        try:
            with YoutubeDL(dict(options)) as ydl:
                return ydl.extract_info(url, download=download)
        except DownloadError as exc:
            last_error = exc
            print("[YouTube] Cookies direct 失敗，改試相容模式。")

        cookie_profiles = [
            (
                "default + web_embedded",
                {
                    "youtube": {
                        "player_client": ["default", "web_embedded"],
                    }
                },
            )
        ]

        # Only use WPC when it was explicitly prepared already.
        wpc = _wpc_profile()
        if wpc:
            cookie_profiles.append(
                (
                    "mweb + WPC",
                    {
                        "youtube": {
                            "player_client": ["mweb"],
                            "fetch_pot": ["always"],
                        },
                        "youtubepot-wpc": wpc["youtubepot-wpc"],
                    },
                )
            )

        for label, extractor_args in cookie_profiles:
            attempt = dict(options)
            attempt["extractor_args"] = extractor_args
            print(f"[YouTube] Cookies 模式：{label}")
            try:
                with YoutubeDL(attempt) as ydl:
                    return ydl.extract_info(url, download=download)
            except DownloadError as exc:
                last_error = exc
                print(f"[YouTube] {label} 失敗，改試下一層。")

        if last_error:
            raise last_error

    last_error = None

    wpc = _wpc_profile()
    if wpc:
        attempt = dict(options)
        attempt["extractor_args"] = wpc
        print("[YouTube] WPC 模式：mweb + Chromium WebPoClient")
        try:
            with YoutubeDL(attempt) as ydl:
                return ydl.extract_info(url, download=download)
        except DownloadError as exc:
            last_error = exc
            print("[YouTube] WPC 模式失敗，改試匿名 fallback。")
    else:
        print(
            "[YouTube] 尚未準備 WPC Provider；"
            "請先執行 setup_wpc_provider.py。"
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


def normalize_lecturer(name: str):
    name = str(name or "").strip()
    return LECTURER_ALIASES.get(name, name)


def detect_lecturer(info: dict):
    title = (info.get("title") or "").strip()
    description = (info.get("description") or "").strip()
    haystack = title + "\n" + description[:5000]

    # Many course uploads use title segments such as:
    # "心念的力量225 | 中和老師 | 打開心靈的鎖匙253期"
    for segment in re.split(r"[｜|]", title):
        segment = segment.strip()
        if re.fullmatch(r"[\u4e00-\u9fff·]{2,12}老師", segment):
            return normalize_lecturer(segment), "title_teacher_segment"

    for pattern in LECTURER_PATTERNS:
        match = re.search(pattern, haystack, flags=re.IGNORECASE)
        if match:
            lecturer = re.sub(r"\s+", " ", match.group(1)).strip(" -–—：:")
            if lecturer:
                return normalize_lecturer(lecturer), "title_or_description"

    fallback = (
        info.get("channel")
        or info.get("uploader")
        or info.get("uploader_id")
        or ""
    )
    return normalize_lecturer(str(fallback).strip()), "channel_or_uploader"


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
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(source_wav),
            "-ac", "1",
            "-ar", "16000",
            str(normalized),
        ],
        check=True,
    )

    lecturer, lecturer_source = detect_lecturer(info)
    return normalized, {
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


def save_metadata_json(metadata: dict, path: Path):
    path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
