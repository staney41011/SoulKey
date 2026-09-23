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
from youtube_io import download_english_cc


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
        message="補抓 YouTube English CC",
        progress=5,
    )

    try:
        workdir = Path("/kaggle/working/soulkey-cc-refresh") / args.task_id
        workdir.mkdir(parents=True, exist_ok=True)

        print(f"[CC] 任務：{args.task_id}")
        print(f"[CC] URL：{task['youtube_url']}")

        cc_path = download_english_cc(task["youtube_url"], workdir)
        if not cc_path or not Path(cc_path).exists():
            raise RuntimeError(
                "YouTube English auto-generated CC 仍抓取失敗。"
                "請確認影片字幕選單確實存在 English (auto-generated)。"
            )

        folders = resolve_lesson_folders(
            drive,
            sheets,
            task["period"],
            task["lesson"],
        )
        upload_or_replace_file(
            drive,
            folders["source"],
            cc_path,
            "youtube.en.json",
        )
        print("[CC] youtube.en.json 已更新到 Drive 來源資料夾")

        review_path = workdir / "zh-TW.review-cache.json"
        download_review_cache(args.task_id, review_path)
        attach_english_cc(review_path, Path(cc_path))

        payload = json.loads(review_path.read_text(encoding="utf-8"))
        available = sum(
            1 for x in payload.get("segments", [])
            if str(x.get("source_en") or "").strip()
        )
        if available < 1:
            raise RuntimeError("CC 已下載，但沒有任何 cue 對齊到中文段落")

        publish_review_cache(args.task_id, review_path)

        mark_done(
            args.task_id,
            "cc",
            sheets=sheets,
            run_id=run_id,
            message=f"English CC 補抓完成；已對齊 {available} 段",
        )
        print(
            f"[CC] 完成：{available}/"
            f"{len(payload.get('segments', []))} 段有 English CC"
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
