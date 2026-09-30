import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

from config import COL, SPREADSHEET_ID, TASK_SHEET_RANGE
from google_io import (
    build_google_services,
    read_values,
    upload_or_replace_file,
)
from runner import resolve_lesson_folders
from polish_runner import attach_english_cc
from github_review_cache import publish_review_cache
from status_io import new_run_id, mark_running, mark_done, mark_error
from youtube_io import download_multilingual_cc


RAW_REVIEW_BASE = (
    "https://raw.githubusercontent.com/"
    "staney41011/SoulKey/main/studio-review-cache"
)


def digits(value):
    match = re.search(r"(\d+)", str(value or ""))
    return int(match.group(1)) if match else None


def pad_row(row, length=20):
    return list(row) + [""] * max(0, length - len(row))


def find_task(sheets, task_id):
    rows = read_values(sheets, SPREADSHEET_ID, TASK_SHEET_RANGE)
    for index, raw in enumerate(rows, start=2):
        row = pad_row(raw, 20)
        current = str(row[COL["task_id"]] or "").strip()
        if current != task_id:
            continue
        return {
            "sheet_row": index,
            "task_id": current,
            "period": digits(row[COL["period"]]),
            "lesson": str(row[COL["lesson"]] or "").strip(),
            "youtube_url": str(row[COL["youtube_url"]] or "").strip(),
        }
    return None


def download_review_cache(task_id, destination):
    url = f"{RAW_REVIEW_BASE}/{task_id}/zh.json?_cc_refresh=1"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "SoulKey-CC-Refresh",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        destination.write_bytes(response.read())
    payload = json.loads(destination.read_text(encoding="utf-8"))
    if not isinstance(payload.get("segments"), list) or not payload["segments"]:
        raise RuntimeError("GitHub review cache 沒有中文 segments")
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    parser.add_argument(
        "--refresh-english-review",
        action="store_true",
        help="English 定稿頁專用：抓完 CC 後同步更新中文 review cache 的 source_en",
    )
    args = parser.parse_args()

    drive, sheets = build_google_services()
    task = find_task(sheets, args.task_id)
    if not task:
        raise RuntimeError(f"找不到任務：{args.task_id}")
    if not task["period"] or not task["lesson"]:
        raise RuntimeError("任務缺少期數或堂次")
    if not task["youtube_url"]:
        raise RuntimeError("任務缺少 YouTube URL")

    run_id = new_run_id(args.task_id, "cc")
    mark_running(
        args.task_id,
        "cc",
        sheets=sheets,
        run_id=run_id,
        message=(
            "補抓 YouTube English CC 並更新人工校稿"
            if args.refresh_english_review
            else "抓取 YouTube 多語自動 CC"
        ),
        progress=5,
    )

    try:
        workdir = Path("/kaggle/working/soulkey-cc-refresh") / args.task_id
        workdir.mkdir(parents=True, exist_ok=True)

        print(f"[CC] 任務：{args.task_id}")
        print(f"[CC] URL：{task['youtube_url']}")

        cc_paths = download_multilingual_cc(task["youtube_url"], workdir)
        if not cc_paths:
            raise RuntimeError(
                "YouTube 沒有抓到任何可用的自動字幕。"
            )

        folders = resolve_lesson_folders(
            drive,
            sheets,
            task["period"],
            task["lesson"],
        )
        uploaded_languages = []
        for lang, cc_path in cc_paths.items():
            cc_path = Path(cc_path)
            if not cc_path.exists():
                continue
            drive_name = f"youtube.{lang}.json"
            upload_or_replace_file(
                drive,
                folders["source"],
                cc_path,
                drive_name,
            )
            uploaded_languages.append(lang)
            print(f"[CC] {drive_name} 已更新到 Drive 來源資料夾")

        if not uploaded_languages:
            raise RuntimeError("CC 已取得，但沒有任何字幕檔成功上傳到 Drive。")

        # Standalone YouTube capture must be independent from Studio review cache.
        # Uploading available captions is already a successful job.
        if not args.refresh_english_review:
            mark_done(
                args.task_id,
                "cc",
                sheets=sheets,
                run_id=run_id,
                message=f"YouTube CC 抓取完成：{','.join(uploaded_languages)}",
            )
            print(
                f"[CC] 抓取完成：語言={','.join(uploaded_languages)}；"
                "已上傳 00_來源資訊，不要求人工校稿快取。",
                flush=True,
            )
            return 0

        # English-review refresh keeps the previous stricter contract.
        english_cc = cc_paths.get("en")
        if not english_cc or not Path(english_cc).exists():
            raise RuntimeError(
                "English CC 補抓模式需要 English auto-generated CC，"
                "但本次 YouTube 沒有取得英文字幕。"
            )

        review_path = workdir / "zh-TW.review-cache.json"
        download_review_cache(args.task_id, review_path)
        attach_english_cc(review_path, Path(english_cc))

        payload = json.loads(review_path.read_text(encoding="utf-8"))
        available = sum(
            1 for x in payload.get("segments", [])
            if str(x.get("source_en") or "").strip()
        )
        if available < 1:
            raise RuntimeError("English CC 已下載，但沒有任何 cue 對齊到中文段落")

        publish_review_cache(args.task_id, review_path)

        mark_done(
            args.task_id,
            "cc",
            sheets=sheets,
            run_id=run_id,
            message=f"English CC 補抓完成；已對齊 {available} 段",
        )
        print(
            f"[CC] English review refresh 完成："
            f"{available}/{len(payload.get('segments', []))} 段有 English CC"
        )
        return 0
    except Exception as exc:
        mark_error(
            args.task_id,
            "cc",
            sheets=sheets,
            run_id=run_id,
            message=f"{type(exc).__name__}: {exc}",
        )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
