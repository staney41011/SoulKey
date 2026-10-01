import argparse
import json
import re
from pathlib import Path

from config import COL, SPREADSHEET_ID, TASK_SHEET_RANGE
from drive_naming import formal_drive_name, rename_existing_outputs
from google_io import (
    build_google_services,
    read_values,
    update_cells,
    upload_or_replace_file,
)
from lesson_paths import resolve_lesson_folders
from status_io import new_run_id, mark_done, mark_error, mark_running
from youtube_io import download_multilingual_audio_tracks, extract_metadata


def digits(value):
    match = re.search(r"(\d+)", str(value or ""))
    return int(match.group(1)) if match else None


def pad_row(row, length=20):
    return list(row) + [""] * max(0, length - len(row))


def find_task(sheets, task_id):
    rows = read_values(sheets, SPREADSHEET_ID, TASK_SHEET_RANGE)
    for index, raw in enumerate(rows, start=2):
        row = pad_row(raw, 20)
        if str(row[COL["task_id"]] or "").strip() != task_id:
            continue
        return {
            "sheet_row": index,
            "task_id": task_id,
            "period": digits(row[COL["period"]]),
            "lesson": str(row[COL["lesson"]] or "").strip(),
            "title": str(row[COL["title"]] or "").strip(),
            "youtube_url": str(row[COL["youtube_url"]] or "").strip(),
            "lecturer": str(row[COL["lecturer"]] or "").strip(),
        }
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    parser.add_argument(
        "--langs",
        default="all",
        help="all 或逗號分隔語言代碼，例如 en,es,th",
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

    langs = [x.strip() for x in args.langs.split(",") if x.strip()]
    if not langs:
        langs = ["all"]

    run_id = new_run_id(args.task_id, "youtube-audio")
    mark_running(
        args.task_id,
        "youtube-audio",
        sheets=sheets,
        run_id=run_id,
        message="正在偵測並下載 YouTube 多語音軌",
        progress=5,
    )

    try:
        workdir = Path("/kaggle/working/soulkey-youtube-multiaudio") / args.task_id
        workdir.mkdir(parents=True, exist_ok=True)

        if not task.get("title"):
            try:
                meta = extract_metadata(
                    task["youtube_url"],
                    workdir / "metadata",
                )
                task["title"] = str(meta.get("title") or "").strip()
                task["lecturer"] = str(meta.get("lecturer") or "").strip()
                if task["title"]:
                    update_cells(
                        sheets,
                        SPREADSHEET_ID,
                        {
                            f"任務佇列!D{task['sheet_row']}": task["title"],
                            f"任務佇列!F{task['sheet_row']}": task["lecturer"],
                        },
                    )
                    print(
                        f"[YOUTUBE-AUDIO] 已補齊 metadata：{task['title']}",
                        flush=True,
                    )
            except Exception as exc:
                print(
                    f"[YOUTUBE-AUDIO] metadata 補抓失敗："
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )

        folders = resolve_lesson_folders(
            drive,
            sheets,
            int(task["period"]),
            task["lesson"],
        )
        rename_existing_outputs(
            drive,
            folders["audio"],
            task,
        )

        manifest, manifest_path = download_multilingual_audio_tracks(
            task["youtube_url"],
            workdir,
            requested_languages=langs,
            preferred_codec="mp3",
        )

        folders = resolve_lesson_folders(
            drive,
            sheets,
            int(task["period"]),
            task["lesson"],
        )

        uploaded = []
        for item in manifest.get("downloaded") or []:
            local_path = Path(item["path"])
            drive_name = local_path.name
            upload_or_replace_file(
                drive,
                folders["audio"],
                local_path,
                drive_name,
                display_name=formal_drive_name(task, drive_name),
            )
            uploaded.append({
                "language": item["language"],
                "file": drive_name,
            })

        final_manifest = dict(manifest)
        final_manifest["uploaded"] = uploaded
        manifest_path.write_text(
            json.dumps(final_manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        upload_or_replace_file(
            drive,
            folders["audio"],
            manifest_path,
            "youtube-audio-manifest.json",
            display_name=formal_drive_name(
                task,
                "youtube-audio-manifest.json",
            ),
        )

        if not uploaded:
            raise RuntimeError("沒有任何多語音軌成功下載")

        languages = ",".join(x["language"] for x in uploaded)
        failure_count = len(manifest.get("failures") or [])
        message = (
            f"YouTube 多語音軌完成：{languages}"
            + (f"；失敗 {failure_count} 軌" if failure_count else "")
        )
        mark_done(
            args.task_id,
            "youtube-audio",
            sheets=sheets,
            run_id=run_id,
            message=message,
        )
        print("[YOUTUBE-MULTIAUDIO DONE] " + message, flush=True)
        return 0

    except Exception as exc:
        mark_error(
            args.task_id,
            "youtube-audio",
            sheets=sheets,
            run_id=run_id,
            message=f"{type(exc).__name__}: {exc}",
        )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
