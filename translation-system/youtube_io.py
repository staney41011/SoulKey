import base64
import json
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
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
BGUTIL_SERVER_MARKER = Path("/kaggle/working/bgutil_server_home.txt")
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


def _bgutil_profile(client: str):
    if not BGUTIL_SERVER_MARKER.exists():
        return None

    server_home = BGUTIL_SERVER_MARKER.read_text(
        encoding="utf-8"
    ).strip()
    if not server_home or not Path(server_home).exists():
        return None

    return {
        "youtube": {
            "player_client": [client],
            "fetch_pot": ["always"],
            "pot_trace": ["true"],
        },
        "youtubepot-bgutilscript": {
            "server_home": [server_home],
        },
    }


def _anonymous_profiles():
    # Public-video fallback clients. Keep these cookie-free so a stale account
    # session cannot force LOGIN_REQUIRED / bot-check responses.
    return [
        {
            "youtube": {
                "player_client": ["android_vr"],
            }
        },
        {
            "youtube": {
                "player_client": ["web_embedded"],
            }
        },
        {
            "youtube": {
                "player_client": ["android_vr", "web_embedded"],
                "player_skip": ["webpage"],
            }
        },
    ]


def _without_cookiefile(options: dict):
    clean = dict(options)
    clean.pop("cookiefile", None)
    return clean


def _bgutil_audio_profiles():
    # yt-dlp's current PO Token guidance recommends mweb + a provider for GVS.
    # web_safari is a useful second web client; android_vr remains a no-POT
    # fallback below.
    profiles = []
    for client in ("mweb", "web_safari", "web"):
        profile = _bgutil_profile(client)
        if profile:
            profiles.append((client, profile))
    return profiles


def _extract_info(url: str, options: dict, download: bool, has_cookies: bool):
    last_error = None

    # 1) Primary public-video path: bgutil PO Token provider without account
    # cookies. This is deliberately first because stale YouTube account cookies
    # commonly turn an otherwise public video into LOGIN_REQUIRED / bot-check.
    bgutil_profiles = _bgutil_audio_profiles()
    if bgutil_profiles:
        for client, extractor_args in bgutil_profiles:
            attempt = _without_cookiefile(options)
            attempt["extractor_args"] = extractor_args
            print(
                f"[YouTube] bgutil 主力模式：{client} + dynamic PO Token "
                "(guest session)",
                flush=True,
            )
            try:
                with YoutubeDL(attempt) as ydl:
                    return ydl.extract_info(url, download=download)
            except DownloadError as exc:
                last_error = exc
                print(
                    f"[YouTube] bgutil {client} 失敗，改試下一個 client。",
                    flush=True,
                )
    else:
        print(
            "[YouTube] bgutil provider 尚未準備；改走其他 fallback。",
            flush=True,
        )

    # 2) Cookie-free clients that currently do not require the same GVS POT
    # path. These are useful when the Kaggle egress IP is accepted but a web
    # client is challenged.
    for index, extractor_args in enumerate(_anonymous_profiles(), start=1):
        attempt = _without_cookiefile(options)
        attempt["extractor_args"] = extractor_args
        print(
            f"[YouTube] 匿名 fallback 第 {index} 層："
            f"{extractor_args['youtube']['player_client']}",
            flush=True,
        )
        try:
            with YoutubeDL(attempt) as ydl:
                return ydl.extract_info(url, download=download)
        except DownloadError as exc:
            last_error = exc
            print(
                f"[YouTube] 匿名 fallback 第 {index} 層失敗。",
                flush=True,
            )

    # 3) WPC provider as an independent guest-session attestation path.
    wpc = _wpc_profile()
    if wpc:
        attempt = _without_cookiefile(options)
        attempt["extractor_args"] = wpc
        print(
            "[YouTube] WPC fallback：mweb + Chromium WebPoClient "
            "(guest session)",
            flush=True,
        )
        try:
            with YoutubeDL(attempt) as ydl:
                return ydl.extract_info(url, download=download)
        except DownloadError as exc:
            last_error = exc
            print(
                "[YouTube] WPC guest 模式失敗，最後才嘗試帳號 Cookies。",
                flush=True,
            )

    # 4) Cookies are now a last-resort path for account-required videos.
    # Combine cookies with bgutil first so the stream request still receives a
    # fresh video-bound PO Token.
    if has_cookies:
        for client, extractor_args in bgutil_profiles:
            attempt = dict(options)
            attempt["extractor_args"] = extractor_args
            print(
                f"[YouTube] Cookies + bgutil fallback：{client}",
                flush=True,
            )
            try:
                with YoutubeDL(attempt) as ydl:
                    return ydl.extract_info(url, download=download)
            except DownloadError as exc:
                last_error = exc
                print(
                    f"[YouTube] Cookies + bgutil {client} 失敗。",
                    flush=True,
                )

        if wpc:
            attempt = dict(options)
            attempt["extractor_args"] = wpc
            print("[YouTube] Cookies + WPC fallback：mweb", flush=True)
            try:
                with YoutubeDL(attempt) as ydl:
                    return ydl.extract_info(url, download=download)
            except DownloadError as exc:
                last_error = exc
                print("[YouTube] Cookies + WPC 失敗。", flush=True)

        print("[YouTube] Cookies 最終 direct fallback。", flush=True)
        try:
            with YoutubeDL(dict(options)) as ydl:
                return ydl.extract_info(url, download=download)
        except DownloadError as exc:
            last_error = exc
            print("[YouTube] Cookies direct 最終 fallback 失敗。", flush=True)

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



AUTO_CC_TARGETS = ("en", "th", "es", "id", "vi", "sd", "ta")


def _caption_language_candidates(target: str):
    target = str(target or "").strip()
    mapping = {
        "zh-Hant": ["zh-Hant", "zh-TW", "zh-HK", "zh"],
        "en": ["en", "en-US", "en-GB"],
        "th": ["th"],
        "es": ["es", "es-419", "es-US", "es-ES"],
        "id": ["id"],
        "vi": ["vi"],
        "sd": ["sd"],
        "ta": ["ta"],
    }
    return mapping.get(target, [target])


def _select_auto_caption(info: dict, target: str):
    captions = info.get("automatic_captions") or {}
    if not isinstance(captions, dict) or not captions:
        return None, None

    aliases = [x.lower().replace("_", "-") for x in _caption_language_candidates(target)]
    ranked = []
    for key in captions:
        normalized = str(key or "").lower().replace("_", "-")
        score = None
        for index, alias in enumerate(aliases):
            if normalized == alias:
                score = index
                break
            if normalized.startswith(alias + "-"):
                score = 20 + index
                break
        if score is not None:
            ranked.append((score, str(key)))

    if not ranked:
        return None, None

    ranked.sort(key=lambda x: (x[0], x[1]))
    lang_key = ranked[0][1]
    formats = captions.get(lang_key) or []
    if not isinstance(formats, list):
        return lang_key, None

    preferred = None
    for ext in ("json3", "vtt", "srv3", "ttml"):
        for item in formats:
            if (
                isinstance(item, dict)
                and str(item.get("ext") or "").lower() == ext
                and item.get("url")
            ):
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


def _cc_plain_time(seconds: float):
    total = max(0, int(float(seconds or 0)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _cc_srt_time(seconds: float):
    milliseconds = max(0, int(round(float(seconds or 0) * 1000)))
    hours, rem = divmod(milliseconds, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _write_cc_companion_files(
    workdir: Path,
    target: str,
    segments,
):
    """Write human-readable TXT/SRT beside the normalized JSON."""
    if not segments:
        return {}

    txt_path = workdir / f"youtube.{target}.txt"
    transcript_path = workdir / f"youtube.{target}.transcript.txt"
    srt_path = workdir / f"youtube.{target}.srt"

    plain_lines = [
        str(x.get("text") or "").strip()
        for x in segments
        if str(x.get("text") or "").strip()
    ]

    txt_lines = [
        f"[{_cc_plain_time(x.get('start'))} - "
        f"{_cc_plain_time(x.get('end'))}] {str(x.get('text') or '').strip()}"
        for x in segments
        if str(x.get("text") or "").strip()
    ]
    txt_path.write_text(
        "\n".join(txt_lines) + ("\n" if txt_lines else ""),
        encoding="utf-8",
    )
    transcript_path.write_text(
        "\n".join(plain_lines) + ("\n" if plain_lines else ""),
        encoding="utf-8",
    )

    srt_lines = []
    for index, item in enumerate(segments, start=1):
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        srt_lines.extend([
            str(index),
            f"{_cc_srt_time(item.get('start'))} --> "
            f"{_cc_srt_time(item.get('end'))}",
            text,
            "",
        ])
    srt_path.write_text("\n".join(srt_lines), encoding="utf-8")
    return {
        "txt": txt_path,
        "transcript": transcript_path,
        "srt": srt_path,
    }


def write_cc_readable_files_from_json(json_path: Path, workdir: Path = None, target: str = None):
    """Generate timeline TXT, plain transcript TXT and SRT from an existing CC JSON."""
    json_path = Path(json_path)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    segments = payload.get("segments") or []
    if not isinstance(segments, list) or not segments:
        raise RuntimeError(f"CC JSON 沒有可用 segments：{json_path.name}")

    if not target:
        match = re.match(r"^youtube\.([^.]+)\.json$", json_path.name)
        target = match.group(1) if match else str(payload.get("language") or "unknown")

    destination = Path(workdir) if workdir else json_path.parent
    destination.mkdir(parents=True, exist_ok=True)
    return _write_cc_companion_files(destination, target, segments)


def _write_auto_cc_json(
    workdir: Path,
    target: str,
    segments,
    video_id: str,
    language: str,
    source: str = "youtube_auto_generated",
):
    if not segments:
        return None

    duration = max(
        (float(x.get("end") or 0) for x in segments),
        default=0.0,
    )
    out = workdir / f"youtube.{target}.json"
    out.write_text(
        json.dumps(
            {
                # Keep the same core shape as SoulKey ASR segments.json so
                # downstream tools and humans can inspect both consistently.
                "model": "youtube-auto-caption",
                "language": target,
                "language_probability": None,
                "duration": round(duration, 3),
                "duration_after_vad": None,
                "segments": segments,
                # YouTube-specific provenance stays additive and does not
                # change the ASR-compatible core fields above.
                "source": source,
                "youtube_language": str(language or target),
                "video_id": video_id,
                "segment_count": len(segments),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_cc_companion_files(workdir, target, segments)
    return out


def _fetch_cc_bytes_with_backoff(url: str, label: str, waits=(0, 20, 60)):
    """Fetch one timedtext URL with bounded retry for YouTube throttling."""
    last_error = None
    for attempt, wait_seconds in enumerate(waits, start=1):
        if wait_seconds:
            print(
                f"[YouTube CC] {label}: 等待 {wait_seconds}s 後重試 "
                f"({attempt}/{len(waits)})",
                flush=True,
            )
            time.sleep(wait_seconds)
        try:
            return _fetch_bytes(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/153.0.0.0 Safari/537.36"
                    ),
                    "Accept-Language": "en-US,en;q=0.9",
                    "Cache-Control": "no-cache",
                },
                timeout=30,
            )
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code == 429 and attempt < len(waits):
                print(
                    f"[YouTube CC] {label}: HTTP 429，進入退避重試。",
                    flush=True,
                )
                continue
            break
        except Exception as exc:
            last_error = exc
            if attempt < len(waits):
                continue
            break

    print(
        f"[YouTube CC] {label}: 最終下載失敗："
        f"{type(last_error).__name__}: {last_error}",
        flush=True,
    )
    return None


def _translation_seed_from_info(info: dict):
    """Pick one caption URL that can be reused with YouTube's tlang parameter."""
    captions = info.get("automatic_captions") or {}
    if not isinstance(captions, dict):
        return None

    ranked = []
    for language, formats in captions.items():
        if not isinstance(formats, list):
            continue
        normalized = str(language or "").lower().replace("_", "-")
        language_rank = 0 if normalized == "en" else 1 if normalized.startswith("en-") else 5
        for item in formats:
            if not isinstance(item, dict) or not item.get("url"):
                continue
            ext = str(item.get("ext") or "").lower()
            format_rank = 0 if ext == "json3" else 5
            ranked.append((language_rank, format_rank, str(language), item))

    if not ranked:
        return None
    ranked.sort(key=lambda x: (x[0], x[1], x[2]))
    _, _, language, item = ranked[0]
    return {
        "language": language,
        "url": str(item.get("url") or "").strip(),
    }


def _translation_seed_from_watch_page(video_id: str):
    tracks = _caption_tracks_from_watch_page(video_id)
    ranked = []
    for track in tracks:
        if not isinstance(track, dict):
            continue
        base_url = str(track.get("baseUrl") or "").strip()
        if not base_url:
            continue
        language = str(track.get("languageCode") or "")
        normalized = language.lower().replace("_", "-")
        is_translatable = bool(track.get("isTranslatable", True))
        if not is_translatable:
            continue
        rank = 0 if normalized == "en" else 1 if normalized.startswith("en-") else 5
        if str(track.get("kind") or "").lower() == "asr":
            rank -= 0.1
        ranked.append((rank, language, base_url))

    if not ranked:
        return None
    ranked.sort(key=lambda x: (x[0], x[1]))
    _, language, base_url = ranked[0]
    return {"language": language, "url": base_url}


def _translated_caption_url(base_url: str, target: str):
    parts = urllib.parse.urlsplit(str(base_url or ""))
    query = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
    query["fmt"] = "json3"
    query["tlang"] = target
    return urllib.parse.urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urllib.parse.urlencode(query),
            parts.fragment,
        )
    )


def _download_missing_auto_translations(
    info: dict,
    workdir: Path,
    missing_targets,
):
    """Use one available caption track + YouTube tlang to fill missing languages."""
    missing_targets = [
        x for x in missing_targets
        if x in AUTO_CC_TARGETS
    ]
    if not missing_targets:
        return {}

    video_id = str(info.get("id") or "").strip()
    seed = _translation_seed_from_info(info)
    if not seed and video_id:
        seed = _translation_seed_from_watch_page(video_id)
    if not seed:
        print(
            "[YouTube CC] 找不到可供 tlang 自動翻譯的基礎字幕軌。",
            flush=True,
        )
        return {}

    print(
        f"[YouTube CC] tlang 補齊模式：基礎字幕={seed['language']}；"
        f"待補={','.join(missing_targets)}",
        flush=True,
    )

    results = {}
    for index, target in enumerate(missing_targets):
        # A small gap is deliberate.  YouTube timedtext endpoints throttle
        # bursts much more aggressively than normal page requests.
        if index:
            time.sleep(8)

        translated_url = _translated_caption_url(seed["url"], target)
        raw = _fetch_cc_bytes_with_backoff(
            translated_url,
            f"tlang {seed['language']}->{target}",
        )
        if not raw:
            continue
        try:
            segments = _segments_from_json3_bytes(raw)
        except Exception as exc:
            print(
                f"[YouTube CC] tlang {target} JSON3 parse failed: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
            continue
        if not segments:
            print(
                f"[YouTube CC] tlang {target}: 回傳成功但沒有字幕內容。",
                flush=True,
            )
            continue

        out = _write_auto_cc_json(
            workdir,
            target,
            segments,
            video_id,
            target,
            source="youtube_auto_translated_tlang",
        )
        if out:
            results[target] = out
            print(
                f"[YouTube CC] ✅ tlang {target}: {len(segments)} cues",
                flush=True,
            )

    return results


def _download_multilingual_auto_cc_from_info(
    info: dict,
    workdir: Path,
    targets=AUTO_CC_TARGETS,
):
    """Download every requested auto-caption language exposed by yt-dlp metadata.

    Missing languages are intentionally non-fatal. YouTube decides which
    auto-generated / auto-translated caption languages are available.
    """
    results = {}
    video_id = str(info.get("id") or "").strip()

    for target in targets:
        lang_key, caption = _select_auto_caption(info, target)
        if not caption:
            print(
                f"[YouTube CC] {target}: automatic caption not exposed by metadata",
                flush=True,
            )
            continue

        url = str(caption.get("url") or "").strip()
        if not url:
            continue

        raw = _fetch_cc_bytes_with_backoff(
            url,
            f"{target}/{lang_key}",
        )
        if not raw:
            continue

        ext = str(caption.get("ext") or "").lower()
        if ext != "json3":
            print(
                f"[YouTube CC] {target}/{lang_key}: format={ext or 'unknown'}; "
                "skip because normalized JSON3 is unavailable",
                flush=True,
            )
            continue

        try:
            segments = _segments_from_json3_bytes(raw)
        except Exception as exc:
            print(
                f"[YouTube CC] {target}/{lang_key} JSON3 parse failed: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
            continue

        out = _write_auto_cc_json(
            workdir,
            target,
            segments,
            video_id,
            lang_key,
        )
        if out:
            results[target] = out
            print(
                f"[YouTube CC] ✅ {target} <- {lang_key}: "
                f"{len(segments)} cues",
                flush=True,
            )
            time.sleep(8)

    return results


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


def _download_english_cc_bgutil_retry(
    video_url: str,
    workdir: Path,
    max_rounds: int = 8,
):
    if not video_url:
        return None

    profile_probe = _bgutil_profile("web")
    if not profile_probe:
        print(
            "[YouTube CC] bgutil subs provider 尚未準備，略過主力重試。",
            flush=True,
        )
        return None

    # 目前 yt-dlp PO Token 文件：web 字幕可能需要 subs token。
    # mweb / embedded 作為 client fallback；所有嘗試優先不用舊 cookies，
    # 避免過期帳號 session 反而觸發 LOGIN_REQUIRED。
    clients = ["web", "web_safari", "mweb", "web_embedded"]
    waits = [5, 8, 12, 18, 25, 35, 45, 45]

    for round_no in range(1, max_rounds + 1):
        print(
            f"[YouTube CC] bgutil PO Token 重試輪次 "
            f"{round_no}/{max_rounds}",
            flush=True,
        )

        for client in clients:
            for old in workdir.glob("youtube_bgutil_cc*.json3"):
                try:
                    old.unlink()
                except Exception:
                    pass

            try:
                options, _ = _base_options(workdir, quiet=False)
                # Public captions: guest session first. Stale account cookies
                # are a common source of LOGIN_REQUIRED and token mismatch.
                options.pop("cookiefile", None)
                options.update(
                    {
                        "skip_download": True,
                        "writeautomaticsub": True,
                        "writesubtitles": False,
                        "subtitleslangs": ["en.*"],
                        "subtitlesformat": "json3",
                        "outtmpl": str(
                            workdir / "youtube_bgutil_cc.%(ext)s"
                        ),
                        "extractor_args": _bgutil_profile(client),
                    }
                )

                print(
                    f"[YouTube CC] bgutil client={client} "
                    f"fetch_pot=always / target=en.*",
                    flush=True,
                )

                with YoutubeDL(options) as ydl:
                    info = ydl.extract_info(video_url, download=True)

                candidates = list(
                    workdir.glob("youtube_bgutil_cc*.json3")
                )
                candidates.sort(key=lambda p: p.name)

                for candidate in candidates:
                    try:
                        segments = _segments_from_json3_bytes(
                            candidate.read_bytes()
                        )
                    except Exception as exc:
                        print(
                            f"[YouTube CC] bgutil 解析 "
                            f"{candidate.name} 失敗："
                            f"{type(exc).__name__}: {exc}",
                            flush=True,
                        )
                        continue

                    if not segments:
                        continue

                    language = "en"
                    name = candidate.name
                    match = re.search(
                        r"\.([A-Za-z]{2}(?:-[A-Za-z0-9]+)?)\.json3$",
                        name,
                    )
                    if match:
                        language = match.group(1)

                    out = _write_english_cc_json(
                        workdir,
                        segments,
                        str((info or {}).get("id") or ""),
                        language,
                        "youtube_auto_generated_bgutil_subs_pot",
                    )
                    print(
                        f"[YouTube CC] ✅ bgutil 成功："
                        f"client={client} / {language} / "
                        f"{len(segments)} cues",
                        flush=True,
                    )
                    return out

                print(
                    f"[YouTube CC] bgutil client={client} "
                    "沒有產生 English json3。",
                    flush=True,
                )
            except Exception as exc:
                print(
                    f"[YouTube CC] bgutil client={client} 失敗："
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )

        if round_no < max_rounds:
            wait_seconds = waits[
                min(round_no - 1, len(waits) - 1)
            ]
            print(
                f"[YouTube CC] 本輪全部失敗，"
                f"{wait_seconds} 秒後再試下一輪。",
                flush=True,
            )
            time.sleep(wait_seconds)

    print(
        "[YouTube CC] bgutil 多輪重試仍未成功，"
        "進入 WPC / player / timedtext / Transcript API 備援。",
        flush=True,
    )
    return None


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


def _fetch_bytes(url: str, headers=None, timeout=30):
    request = urllib.request.Request(
        url,
        headers=headers or {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/153.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _json_after_marker(text: str, marker: str):
    index = text.find(marker)
    if index < 0:
        return None
    start = index + len(marker)
    while start < len(text) and text[start] in " \t\r\n:=":
        start += 1
    try:
        value, _ = json.JSONDecoder().raw_decode(text[start:])
        return value
    except Exception:
        return None


def _caption_tracks_from_watch_page(video_id: str):
    if not video_id:
        return []

    watch_url = (
        "https://www.youtube.com/watch?"
        + urllib.parse.urlencode({"v": video_id, "hl": "en"})
    )
    try:
        raw = _fetch_bytes(
            watch_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/153.0.0.0 Safari/537.36"
                ),
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/avif,image/webp,*/*;q=0.8"
                ),
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "no-cache",
            },
            timeout=30,
        )
        html = raw.decode("utf-8", errors="replace")
    except Exception as exc:
        print(
            f"[YouTube CC] watch page 讀取失敗："
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        return []

    player = None
    for marker in (
        "ytInitialPlayerResponse =",
        "var ytInitialPlayerResponse =",
        'window["ytInitialPlayerResponse"] =',
        '"ytInitialPlayerResponse":',
    ):
        player = _json_after_marker(html, marker)
        if isinstance(player, dict):
            break

    tracks = []
    if isinstance(player, dict):
        tracks = (
            player.get("captions", {})
            .get("playerCaptionsTracklistRenderer", {})
            .get("captionTracks", [])
        ) or []

    if not tracks:
        marker = '"captionTracks":'
        index = html.find(marker)
        if index >= 0:
            start = index + len(marker)
            while start < len(html) and html[start] in " \t\r\n":
                start += 1
            try:
                decoded, _ = json.JSONDecoder().raw_decode(html[start:])
                if isinstance(decoded, list):
                    tracks = decoded
            except Exception:
                pass

    print(
        f"[YouTube CC] watch page captionTracks：{len(tracks)} 軌",
        flush=True,
    )
    return tracks


def _download_english_cc_from_watch_page(video_id: str, workdir: Path):
    tracks = _caption_tracks_from_watch_page(video_id)
    if not tracks:
        return None

    ranked = []
    for track in tracks:
        if not isinstance(track, dict):
            continue
        language = str(track.get("languageCode") or "").lower()
        vss_id = str(track.get("vssId") or "").lower()
        kind = str(track.get("kind") or "").lower()
        base_url = str(track.get("baseUrl") or "").strip()
        if not base_url:
            continue
        if language == "en":
            rank = 0
        elif language in {"en-us", "en_us"}:
            rank = 1
        elif language.startswith("en-") or language.startswith("en_"):
            rank = 2
        elif vss_id in {".en", "a.en"} or vss_id.endswith(".en"):
            rank = 3
        else:
            continue
        if kind == "asr" or vss_id.startswith("a."):
            rank -= 0.25
        ranked.append((rank, track))

    if not ranked:
        print(
            "[YouTube CC] watch page 有字幕軌，但沒有 English 軌。",
            flush=True,
        )
        return None

    ranked.sort(key=lambda x: x[0])
    for _, track in ranked:
        base_url = str(track.get("baseUrl") or "").strip()
        language = str(track.get("languageCode") or "en")
        try:
            parts = urllib.parse.urlsplit(base_url)
            query = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
            query["fmt"] = "json3"
            json3_url = urllib.parse.urlunsplit(
                (
                    parts.scheme,
                    parts.netloc,
                    parts.path,
                    urllib.parse.urlencode(query),
                    parts.fragment,
                )
            )
            raw = _fetch_bytes(json3_url, timeout=30)
            segments = _segments_from_json3_bytes(raw)
            if not segments:
                continue
            out = _write_english_cc_json(
                workdir,
                segments,
                video_id,
                language,
                "youtube_auto_generated_watch_page",
            )
            print(
                f"[YouTube CC] watch page captionTracks 成功："
                f"{language} / {len(segments)} cues",
                flush=True,
            )
            return out
        except Exception as exc:
            print(
                f"[YouTube CC] watch page English 軌下載失敗："
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

    return None


def _download_english_cc_direct_timedtext(video_id: str, workdir: Path):
    if not video_id:
        return None

    variants = [
        {"v": video_id, "lang": "en", "fmt": "json3", "kind": "asr"},
        {
            "v": video_id,
            "lang": "en",
            "fmt": "json3",
            "kind": "asr",
            "caps": "asr",
            "xorb": "2",
            "xorp": "true",
        },
        {"v": video_id, "lang": "en-US", "fmt": "json3", "kind": "asr"},
        {"v": video_id, "lang": "en", "fmt": "json3"},
    ]

    for params in variants:
        url = (
            "https://www.youtube.com/api/timedtext?"
            + urllib.parse.urlencode(params)
        )
        try:
            raw = _fetch_bytes(url, timeout=20)
            if not raw or len(raw) < 8:
                continue
            segments = _segments_from_json3_bytes(raw)
            if not segments:
                continue
            out = _write_english_cc_json(
                workdir,
                segments,
                video_id,
                str(params.get("lang") or "en"),
                "youtube_auto_generated_direct_timedtext",
            )
            print(
                f"[YouTube CC] direct timedtext 成功："
                f"{len(segments)} cues",
                flush=True,
            )
            return out
        except Exception as exc:
            print(
                f"[YouTube CC] direct timedtext variant 失敗："
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
            "先試 bgutil Subs PO Token。",
            flush=True,
        )
        bgutil = _download_english_cc_bgutil_retry(
            video_url,
            workdir,
            max_rounds=3,
        )
        if bgutil:
            return bgutil

        print(
            "[YouTube CC] bgutil 未成功；改用 explicit yt-dlp。",
            flush=True,
        )
        explicit = _download_english_cc_explicit_ytdlp(video_url, workdir)
        if explicit:
            return explicit

        video_id = str(info.get("id") or "") or _video_id_from_url(video_url)
        print("[YouTube CC] explicit yt-dlp 失敗；改讀播放器 captionTracks。")
        browser_cc = _download_english_cc_from_watch_page(video_id, workdir)
        if browser_cc:
            return browser_cc

        timedtext = _download_english_cc_direct_timedtext(video_id, workdir)
        if timedtext:
            return timedtext

        print("[YouTube CC] 播放器／timedtext 仍失敗；最後試 Transcript API。")
        return _download_english_cc_via_transcript_api(
            video_id,
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
        video_id = str(info.get("id") or "") or _video_id_from_url(video_url)
        browser_cc = _download_english_cc_from_watch_page(video_id, workdir)
        if browser_cc:
            return browser_cc
        timedtext = _download_english_cc_direct_timedtext(video_id, workdir)
        if timedtext:
            return timedtext
        return _download_english_cc_via_transcript_api(
            video_id,
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
        video_id = str(info.get("id") or "") or _video_id_from_url(video_url)
        browser_cc = _download_english_cc_from_watch_page(video_id, workdir)
        if browser_cc:
            return browser_cc
        timedtext = _download_english_cc_direct_timedtext(video_id, workdir)
        if timedtext:
            return timedtext
        return _download_english_cc_via_transcript_api(
            video_id,
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



def _video_id_from_url(url: str):
    text = str(url or "").strip()
    patterns = [
        r"(?:youtu\.be/)([A-Za-z0-9_-]{6,})",
        r"(?:[?&]v=)([A-Za-z0-9_-]{6,})",
        r"(?:youtube\.com/(?:embed|shorts|live)/)([A-Za-z0-9_-]{6,})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return ""



def download_multilingual_cc(
    url: str,
    workdir: Path,
    targets=AUTO_CC_TARGETS,
):
    """Fetch all available SoulKey auto-caption languages without audio."""
    workdir.mkdir(parents=True, exist_ok=True)
    targets = tuple(dict.fromkeys(str(x).strip() for x in targets if str(x).strip()))
    results = {}

    options, has_cookies = _base_options(workdir, quiet=False)
    options["skip_download"] = True

    try:
        info = _extract_info(
            url=url,
            options=options,
            download=False,
            has_cookies=has_cookies,
        )
        results.update(
            _download_multilingual_auto_cc_from_info(
                info,
                workdir,
                targets=targets,
            )
        )
    except Exception as exc:
        print(
            f"[YouTube CC] multilingual metadata fetch failed: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )

    # Keep the mature English fallback chain for backward compatibility.
    if "en" in targets and "en" not in results:
        english = download_english_cc(url, workdir)
        if english:
            english = Path(english)
            results["en"] = english
            try:
                payload = json.loads(english.read_text(encoding="utf-8"))
                _write_cc_companion_files(
                    workdir,
                    "en",
                    payload.get("segments") or [],
                )
            except Exception as exc:
                print(
                    f"[YouTube CC] English readable files failed: "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )

    missing = [target for target in targets if target not in results]
    if missing:
        results.update(
            _download_missing_auto_translations(
                info if 'info' in locals() and isinstance(info, dict) else {},
                workdir,
                missing,
            )
        )

    print(
        "[YouTube CC] multilingual result: "
        + (",".join(results.keys()) if results else "none"),
        flush=True,
    )
    return results


def download_english_cc(url: str, workdir: Path):
    """Fetch only English auto-generated CC without downloading audio."""
    workdir.mkdir(parents=True, exist_ok=True)

    # 2026 主路徑：bgutil 自動取得 web Subs PO Token。
    bgutil = _download_english_cc_bgutil_retry(
        url,
        workdir,
        max_rounds=8,
    )
    if bgutil:
        return bgutil

    options, has_cookies = _base_options(workdir, quiet=False)
    options["skip_download"] = True

    try:
        info = _extract_info(
            url=url,
            options=options,
            download=False,
            has_cookies=has_cookies,
        )
        result = _download_english_auto_cc(
            info,
            workdir,
            video_url=url,
        )
        if result:
            return result
    except Exception as exc:
        print(
            f"[YouTube CC] yt-dlp metadata 最終仍失敗："
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )

    video_id = _video_id_from_url(url)
    if video_id:
        print(
            "[YouTube CC] 改以播放器頁面直接找 captionTracks。",
            flush=True,
        )
        result = _download_english_cc_from_watch_page(video_id, workdir)
        if result:
            return result

        result = _download_english_cc_direct_timedtext(video_id, workdir)
        if result:
            return result

        print(
            "[YouTube CC] 播放器路徑仍失敗；最後嘗試 Transcript API。",
            flush=True,
        )
        result = _download_english_cc_via_transcript_api(
            video_id,
            workdir,
        )
        if result:
            return result

    return None


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

    auto_cc_paths = _download_multilingual_auto_cc_from_info(
        info,
        workdir,
        targets=AUTO_CC_TARGETS,
    )
    english_cc_path = auto_cc_paths.get("en")
    if not english_cc_path:
        english_cc_path = _download_english_auto_cc(info, workdir, video_url=url)
        if english_cc_path:
            auto_cc_paths["en"] = Path(english_cc_path)

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
        "auto_cc_paths": {
            code: str(path)
            for code, path in auto_cc_paths.items()
            if path
        },
    }



def _normalize_audio_language(value: str):
    text = str(value or "").strip().replace("_", "-")
    if not text or text.lower() in {"und", "unknown", "none"}:
        return ""
    return text


def _safe_audio_language(value: str):
    text = _normalize_audio_language(value)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-")
    return safe or "unknown"


def _audio_format_score(fmt: dict):
    """Prefer audio-only and higher-bitrate non-DRM tracks."""
    audio_only = 1 if str(fmt.get("vcodec") or "none") == "none" else 0
    drm_penalty = -1 if fmt.get("has_drm") else 0
    abr = float(fmt.get("abr") or 0)
    tbr = float(fmt.get("tbr") or 0)
    preference = float(fmt.get("preference") or 0)
    source_preference = float(fmt.get("source_preference") or 0)
    return (
        drm_penalty,
        audio_only,
        source_preference,
        preference,
        abr,
        tbr,
    )


def discover_multilingual_audio_tracks(url: str, workdir: Path):
    """Return the best downloadable audio-bearing format for every language tag."""
    workdir.mkdir(parents=True, exist_ok=True)
    options, has_cookies = _base_options(workdir, quiet=False)
    options["skip_download"] = True

    info = _extract_info(
        url=url,
        options=options,
        download=False,
        has_cookies=has_cookies,
    )

    groups = {}
    for fmt in info.get("formats") or []:
        acodec = str(fmt.get("acodec") or "none")
        if acodec == "none":
            continue
        lang = _normalize_audio_language(fmt.get("language"))
        if not lang:
            continue
        groups.setdefault(lang, []).append(fmt)

    tracks = []
    for lang, formats in groups.items():
        usable = [x for x in formats if not x.get("has_drm")]
        candidates = usable or formats
        best = max(candidates, key=_audio_format_score)
        note = str(best.get("format_note") or "")
        track_name = str(best.get("format") or best.get("format_id") or lang)
        combined = (note + " " + track_name).lower()
        tracks.append({
            "language": lang,
            "format_id": str(best.get("format_id") or ""),
            "ext": str(best.get("ext") or ""),
            "acodec": str(best.get("acodec") or ""),
            "vcodec": str(best.get("vcodec") or ""),
            "abr": best.get("abr"),
            "tbr": best.get("tbr"),
            "format_note": note,
            "is_audio_only": str(best.get("vcodec") or "none") == "none",
            "is_dubbed_hint": ("dub" in combined),
        })

    tracks.sort(key=lambda x: x["language"].lower())
    return {
        "video_id": str(info.get("id") or ""),
        "title": str(info.get("title") or ""),
        "webpage_url": str(info.get("webpage_url") or url),
        "original_language": _normalize_audio_language(
            info.get("language") or info.get("original_language")
        ),
        "tracks": tracks,
    }


def _match_requested_audio_tracks(tracks, requested):
    requested = [
        _normalize_audio_language(x)
        for x in (requested or [])
        if _normalize_audio_language(x)
    ]
    if not requested or any(x.lower() == "all" for x in requested):
        return list(tracks)

    selected = []
    seen = set()
    for wanted in requested:
        wanted_low = wanted.lower()
        exact = [
            x for x in tracks
            if str(x.get("language") or "").lower() == wanted_low
        ]
        base = [
            x for x in tracks
            if str(x.get("language") or "").lower().split("-", 1)[0]
            == wanted_low.split("-", 1)[0]
        ]
        for item in (exact or base):
            key = str(item.get("language") or "").lower()
            if key and key not in seen:
                seen.add(key)
                selected.append(item)
    return selected


def download_multilingual_audio_tracks(
    url: str,
    workdir: Path,
    requested_languages=None,
    preferred_codec="mp3",
):
    """Discover and download YouTube language audio tracks independently."""
    workdir.mkdir(parents=True, exist_ok=True)
    discovery = discover_multilingual_audio_tracks(url, workdir)
    tracks = discovery.get("tracks") or []
    selected = _match_requested_audio_tracks(tracks, requested_languages)

    if not tracks:
        raise RuntimeError(
            "yt-dlp 沒有偵測到帶 language 標籤的 YouTube 音軌。"
            "這支影片可能尚未提供多語配音，或目前播放器 client 沒有暴露音軌。"
        )
    if not selected:
        wanted = ",".join(requested_languages or []) or "all"
        available = ",".join(x["language"] for x in tracks)
        raise RuntimeError(
            f"找不到指定語言音軌：{wanted}；目前可用：{available}"
        )

    downloaded = []
    failures = []

    for track in selected:
        lang = str(track["language"])
        safe_lang = _safe_audio_language(lang)
        format_id = str(track.get("format_id") or "").strip()
        if not format_id:
            failures.append({"language": lang, "error": "missing_format_id"})
            continue

        target_stem = f"youtube.{safe_lang}"
        out_template = str(workdir / f"{target_stem}.%(ext)s")
        options, has_cookies = _base_options(workdir, quiet=False)
        options.update({
            "format": format_id,
            "outtmpl": out_template,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": preferred_codec,
                "preferredquality": "192",
            }],
        })

        print(
            f"[YouTube MultiAudio] download {lang} (format={format_id})",
            flush=True,
        )

        try:
            _extract_info(
                url=url,
                options=options,
                download=True,
                has_cookies=has_cookies,
            )
            expected = workdir / f"{target_stem}.{preferred_codec}"
            if not expected.exists():
                candidates = sorted(workdir.glob(f"{target_stem}.*"))
                if not candidates:
                    raise RuntimeError("下載完成但找不到輸出音檔")
                expected = candidates[0]

            downloaded.append({
                **track,
                "file": expected.name,
                "path": str(expected),
            })
        except Exception as exc:
            failures.append({
                "language": lang,
                "format_id": format_id,
                "error": f"{type(exc).__name__}: {exc}",
            })
            print(
                f"[YouTube MultiAudio] {lang} failed: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

    manifest = {
        **discovery,
        "requested_languages": list(requested_languages or ["all"]),
        "downloaded": downloaded,
        "failures": failures,
    }
    manifest_path = workdir / "youtube-audio-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest, manifest_path


def save_metadata_json(metadata: dict, path: Path):
    path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
