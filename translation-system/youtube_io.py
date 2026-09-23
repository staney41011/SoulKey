import base64
import json
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError
from youtube_transcript_api import YouTubeTranscriptApi

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

    deno = ""
    if DENO_MARKER.exists():
        deno = DENO_MARKER.read_text(encoding="utf-8").strip()
    if not deno:
        deno = shutil.which("deno") or ""

    if deno and Path(deno).exists():
        options["js_runtimes"] = {"deno": {"path": deno}}
        # yt-dlp[default] already bundles EJS; npm is an additional self-healing source.
        options["remote_components"] = ["ejs:npm"]
        print(f"[YouTube] JS runtime：Deno ({deno})")
    else:
        print("[YouTube] JS runtime：未找到 Deno；YouTube n challenge 可能失敗。")

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


def _select_english_auto_caption(info: dict):
    captions = info.get("automatic_captions") or {}
    if not isinstance(captions, dict) or not captions:
        return None, None

    candidates = []
    for key in captions:
        normalized = str(key or "").lower()
        if normalized == "en":
            candidates.append((0, key))
        elif normalized in {"en-us", "en_us"}:
            candidates.append((1, key))
        elif normalized.startswith("en-") or normalized.startswith("en_"):
            candidates.append((2, key))

    if not candidates:
        return None, None

    candidates.sort(key=lambda x: (x[0], str(x[1])))
    lang_key = candidates[0][1]
    formats = captions.get(lang_key) or []
    if not isinstance(formats, list):
        return lang_key, None

    preferred = None
    for ext in ("json3", "vtt", "srv3", "ttml"):
        for item in formats:
            if str(item.get("ext") or "").lower() == ext and item.get("url"):
                preferred = item
                break
        if preferred:
            break

    if not preferred:
        preferred = next(
            (x for x in formats if isinstance(x, dict) and x.get("url")),
            None,
        )
    return lang_key, preferred


def _segments_from_json3_bytes(raw: bytes):
    payload = json.loads(raw.decode("utf-8"))
    segments = []
    for event in payload.get("events") or []:
        segs = event.get("segs") or []
        text = "".join(str(x.get("utf8") or "") for x in segs)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        start_ms = float(event.get("tStartMs") or 0)
        duration_ms = float(event.get("dDurationMs") or 0)
        start = start_ms / 1000.0
        end = (start_ms + max(0.0, duration_ms)) / 1000.0
        segments.append({
            "start": round(start, 3),
            "end": round(max(start, end), 3),
            "text": text,
        })
    return segments


def _write_english_cc_json(
    workdir: Path,
    segments,
    video_id: str,
    language: str,
    source: str,
):
    if not segments:
        return None

    out = workdir / "youtube.en.json"
    out.write_text(
        json.dumps(
            {
                "source": source,
                "language": str(language or "en"),
                "video_id": video_id,
                "segment_count": len(segments),
                "segments": segments,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return out


def _download_english_cc_explicit_ytdlp(video_url: str, workdir: Path):
    if not video_url:
        return None

    # 第二條獨立字幕路徑：即使音訊 extraction 的 info 沒帶回
    # automatic_captions，也明確要求 yt-dlp 寫出 English auto-subs。
    try:
        for old in workdir.glob("youtube_cc*.json3"):
            try:
                old.unlink()
            except Exception:
                pass

        options, has_cookies = _base_options(workdir, quiet=False)
        options.update(
            {
                "skip_download": True,
                "writeautomaticsub": True,
                "writesubtitles": False,
                "subtitleslangs": ["en", "en-US", "en-GB"],
                "subtitlesformat": "json3",
                "outtmpl": str(workdir / "youtube_cc.%(ext)s"),
            }
        )

        info = _extract_info(
            url=video_url,
            options=options,
            download=True,
            has_cookies=has_cookies,
        )

        candidates = list(workdir.glob("youtube_cc*.json3"))
        candidates.sort(
            key=lambda p: (
                0 if ".en." in p.name else
                1 if ".en-US." in p.name else
                2 if ".en-GB." in p.name else 9,
                p.name,
            )
        )

        for candidate in candidates:
            try:
                segments = _segments_from_json3_bytes(candidate.read_bytes())
            except Exception as exc:
                print(
                    f"[YouTube CC] explicit yt-dlp 解析 {candidate.name} 失敗："
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )
                continue

            if segments:
                language = "en"
                name = candidate.name
                if ".en-US." in name:
                    language = "en-US"
                elif ".en-GB." in name:
                    language = "en-GB"

                out = _write_english_cc_json(
                    workdir,
                    segments,
                    str(info.get("id") or ""),
                    language,
                    "youtube_auto_generated_explicit_ytdlp",
                )
                print(
                    f"[YouTube CC] explicit yt-dlp 成功："
                    f"{language} / {len(segments)} cues",
                    flush=True,
                )
                return out

        print(
            "[YouTube CC] explicit yt-dlp 沒有產生 English json3 字幕檔。",
            flush=True,
        )
    except Exception as exc:
        print(
            f"[YouTube CC] explicit yt-dlp fallback 失敗："
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )

    return None


def _download_english_cc_via_transcript_api(video_id: str, workdir: Path):
    if not video_id:
        return None

    try:
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)
        selected = None

        for finder in (
            transcript_list.find_generated_transcript,
            transcript_list.find_transcript,
        ):
            try:
                selected = finder(["en", "en-US", "en-GB"])
                break
            except Exception:
                pass

        if selected is None:
            return None

        fetched = selected.fetch()
        segments = []
        for snippet in fetched:
            text = re.sub(r"\s+", " ", str(snippet.text or "")).strip()
            if not text:
                continue
            start = float(snippet.start or 0)
            duration = max(0.0, float(snippet.duration or 0))
            segments.append({
                "start": round(start, 3),
                "end": round(start + duration, 3),
                "text": text,
            })

        if not segments:
            return None

        out = workdir / "youtube.en.json"
        out.write_text(
            json.dumps(
                {
                    "source": "youtube_auto_generated_transcript_api",
                    "language": str(selected.language_code or "en"),
                    "video_id": video_id,
                    "segment_count": len(segments),
                    "segments": segments,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(
            f"[YouTube CC] Transcript API fallback 成功："
            f"{selected.language_code} / {len(segments)} cues",
            flush=True,
        )
        return out
    except Exception as exc:
        print(
            f"[YouTube CC] Transcript API fallback 失敗："
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        return None


def _download_english_auto_cc(info: dict, workdir: Path, video_url: str = ""):
    lang_key, caption = _select_english_auto_caption(info)
    if not caption:
        print(
            "[YouTube CC] metadata 沒帶回 English auto-generated；"
            "改用 explicit yt-dlp 字幕下載。",
            flush=True,
        )
        explicit = _download_english_cc_explicit_ytdlp(video_url, workdir)
        if explicit:
            return explicit
        print("[YouTube CC] explicit yt-dlp 失敗；再試 Transcript API。")
        explicit = _download_english_cc_explicit_ytdlp(video_url, workdir)
        if explicit:
            return explicit
        return _download_english_cc_via_transcript_api(
            str(info.get("id") or ""),
            workdir,
        )

    url = str(caption.get("url") or "").strip()
    if not url:
        return None

    try:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
    except Exception as exc:
        print(
            f"[YouTube CC] English CC 直連下載失敗：{type(exc).__name__}: {exc}；"
            "改試 Transcript API。",
            flush=True,
        )
        return _download_english_cc_via_transcript_api(
            str(info.get("id") or ""),
            workdir,
        )

    ext = str(caption.get("ext") or "").lower()
    segments = []

    if ext == "json3":
        try:
            segments = _segments_from_json3_bytes(raw)
        except Exception as exc:
            print(
                f"[YouTube CC] json3 解析失敗：{type(exc).__name__}: {exc}",
                flush=True,
            )

    if not segments:
        # 若 yt-dlp 沒提供 json3，保留原始字幕檔供後續診斷，
        # 但不讓解析失敗阻斷 ASR。
        raw_path = workdir / f"youtube.en.{ext or 'subtitle'}"
        raw_path.write_bytes(raw)
        print(
            f"[YouTube CC] 已抓到 English auto-generated ({lang_key})，"
            f"但目前格式={ext or 'unknown'}，先保存原檔：{raw_path.name}；"
            "改試 Transcript API 轉成統一 JSON。",
            flush=True,
        )
        explicit = _download_english_cc_explicit_ytdlp(video_url, workdir)
        if explicit:
            return explicit
        return _download_english_cc_via_transcript_api(
            str(info.get("id") or ""),
            workdir,
        )

    out = workdir / "youtube.en.json"
    out.write_text(
        json.dumps(
            {
                "source": "youtube_auto_generated",
                "language": str(lang_key or "en"),
                "video_id": info.get("id"),
                "segment_count": len(segments),
                "segments": segments,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        f"[YouTube CC] English auto-generated 已抓取："
        f"{lang_key} / {len(segments)} cues",
        flush=True,
    )
    return out


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

    english_cc_path = _download_english_auto_cc(info, workdir, video_url=url)

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
        "english_cc_path": str(english_cc_path) if english_cc_path else "",
    }


def save_metadata_json(metadata: dict, path: Path):
    path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
