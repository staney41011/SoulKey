import re
from urllib.parse import urlparse, parse_qs

from youtube_transcript_api import YouTubeTranscriptApi

from config import SPREADSHEET_ID, TASK_SHEET_RANGE
from google_io import build_google_services, read_values


def video_id_from_url(url: str):
    url = (url or "").strip()
    if not url:
        return None

    parsed = urlparse(url)

    if parsed.netloc in {"youtu.be", "www.youtu.be"}:
        return parsed.path.strip("/").split("/")[0]

    if "youtube.com" in parsed.netloc:
        if parsed.path == "/watch":
            return parse_qs(parsed.query).get("v", [None])[0]
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"}:
            return parts[1]

    match = re.search(r"(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{6,})", url)
    return match.group(1) if match else None


def main():
    print("=" * 72)
    print("YouTube Transcript Probe｜零儲存字幕測試")
    print("=" * 72)

    _, sheets = build_google_services()
    rows = read_values(sheets, SPREADSHEET_ID, TASK_SHEET_RANGE)

    first_url = None
    for row in rows:
        if len(row) > 4 and row[4]:
            first_url = row[4]
            break

    if not first_url:
        raise RuntimeError("控制中心找不到 YouTube URL")

    video_id = video_id_from_url(first_url)
    if not video_id:
        raise RuntimeError(f"無法解析影片 ID：{first_url}")

    print(f"URL: {first_url}")
    print(f"Video ID: {video_id}")

    api = YouTubeTranscriptApi()
    transcript_list = api.list(video_id)

    available = []
    for transcript in transcript_list:
        available.append(
            {
                "language": transcript.language,
                "language_code": transcript.language_code,
                "is_generated": transcript.is_generated,
                "is_translatable": transcript.is_translatable,
            }
        )

    print("")
    print("✅ 可用字幕軌：")
    for item in available:
        print(
            f"- {item['language']} ({item['language_code']})"
            f" | generated={item['is_generated']}"
            f" | translatable={item['is_translatable']}"
        )

    preferred = [
        "zh-TW",
        "zh-Hant",
        "zh",
        "zh-Hans",
        "cmn-Hant-TW",
        "cmn",
    ]

    selected = None
    for finder in (
        transcript_list.find_manually_created_transcript,
        transcript_list.find_generated_transcript,
        transcript_list.find_transcript,
    ):
        try:
            selected = finder(preferred)
            break
        except Exception:
            pass

    if selected is None:
        print("")
        print("⚠️ 找不到中文/華語字幕軌，但影片可能有其他語言字幕。")
        return 2

    fetched = selected.fetch()

    print("")
    print(
        f"✅ 已取得字幕：{selected.language} "
        f"({selected.language_code}) generated={selected.is_generated}"
    )
    print(f"字幕段數：{len(fetched)}")
    print("")
    print("前 8 段：")

    for snippet in list(fetched)[:8]:
        end = snippet.start + snippet.duration
        print(
            f"[{snippet.start:8.2f} - {end:8.2f}] "
            f"{snippet.text}"
        )

    print("")
    print("🎉 零儲存字幕路徑可用。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
