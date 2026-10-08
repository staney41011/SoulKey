import argparse
import json
import os
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from config import (
    COL,
    GLOSSARY_RANGE,
    SPREADSHEET_ID,
    TASK_SHEET_RANGE,
    TIMEZONE,
)
from gemini_engine import DEFAULT_VIDEO_MODEL, GeminiAPIError, GeminiClient
from google_io import (
    build_google_services,
    get_secret,
    read_values,
    update_cells,
    upload_or_replace_file,
)
from lesson_paths import digits, resolve_lesson_folders
from status_io import new_run_id, mark_done, mark_error, mark_running


TRANSCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "text": {"type": "string"},
                },
                "required": ["id", "start", "end", "text"],
            },
        }
    },
    "required": ["segments"],
}


def now_text():
    return datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")


def pad_row(row, length=20):
    return list(row) + [""] * max(0, length - len(row))


def row_to_task(raw, sheet_row):
    row = pad_row(raw, 20)
    return {
        "sheet_row": sheet_row,
        "task_id": str(row[COL["task_id"]] or "").strip(),
        "period": digits(row[COL["period"]]),
        "lesson": str(row[COL["lesson"]] or "").strip(),
        "youtube_url": str(row[COL["youtube_url"]] or "").strip(),
    }


def find_task(sheets, task_id):
    for index, raw in enumerate(
        read_values(sheets, SPREADSHEET_ID, TASK_SHEET_RANGE),
        start=2,
    ):
        task = row_to_task(raw, index)
        if task["task_id"] == task_id:
            return task
    return None


def get_glossary_terms(sheets):
    rows = read_values(sheets, SPREADSHEET_ID, GLOSSARY_RANGE)
    return [
        str(row[0]).strip()
        for row in rows
        if row and str(row[0]).strip()
    ][:100]


def update_task(sheets, row, *, asr=None, note=None):
    updates = {f"任務佇列!S{row}": now_text()}
    if asr is not None:
        updates[f"任務佇列!H{row}"] = asr
    if note:
        updates[f"任務佇列!T{row}"] = str(note)[:450]
    update_cells(sheets, SPREADSHEET_ID, updates)


def format_srt_time(seconds):
    ms = max(0, int(round(float(seconds) * 1000)))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, milli = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{milli:03d}"


def normalize_transcript(rows):
    cleaned = []
    for idx, item in enumerate(rows or []):
        text = re.sub(r"\s+", " ", str(item.get("text") or "")).strip()
        if not text:
            continue
        start = max(0.0, float(item.get("start") or 0))
        end = max(start + 0.2, float(item.get("end") or start + 0.2))
        cleaned.append({
            "id": idx,
            "start": round(start, 3),
            "end": round(end, 3),
            "text": text,
        })

    if not cleaned:
        raise RuntimeError("Gemini 沒有回傳任何逐字稿 segments")

    cleaned.sort(key=lambda x: (x["start"], x["end"]))
    for idx, item in enumerate(cleaned):
        item["id"] = idx
        if idx and item["start"] < cleaned[idx - 1]["start"]:
            raise RuntimeError("Gemini transcript timestamp 排序錯誤")
    return cleaned


def video_model_candidates(primary, configured=None):
    """The second model is a real video-capable Gemini model, not a text-only fallback."""
    configured = configured if configured is not None else os.getenv(
        "GEMINI_VIDEO_FALLBACK_MODELS", "gemini-3.1-flash-lite"
    )
    names = [str(primary).strip()]
    names.extend(name.strip() for name in str(configured).split(","))
    # Keep order, avoid duplicate requests, and allow disabling fallback via "".
    return list(dict.fromkeys(name for name in names if name))


def transient_video_error(exc):
    """Only switch models for overload, rate limits, or unavailable models."""
    reason = str(exc)
    return bool(re.search(
        r"HTTP\s+(?:408|409|429|500|502|503|504)\b|"
        r"HTTP\s+404\b|"
        r"timeout|temporarily unavailable|high demand",
        reason, flags=re.IGNORECASE
    ))


def transcribe_youtube_with_model_fallback(client, url, prompt, schema,
                                           primary=DEFAULT_VIDEO_MODEL,
                                           fallback_models=None):
    models = video_model_candidates(primary, fallback_models)
    for index, model in enumerate(models):
        try:
            print(f"[GEMINI VIDEO] 嘗試影片模型 {model} ({index+1}/{len(models)})",
                  flush=True)
            payload, usage = client.structured_video(
                url, prompt, schema, model=model, thinking_level="low"
            )
            if not payload.get("segments"):
                raise GeminiAPIError("Gemini Video Structured Output 沒有 segments")
            return payload, usage, model
        except GeminiAPIError as exc:
            if index + 1 >= len(models) or not transient_video_error(exc):
                raise
            print(
                f"[GEMINI VIDEO] {model} 暫不可用；"
                f"15 秒後改用備援 {models[index+1]}。",
                flush=True
            )
            import time
            time.sleep(15)
    raise RuntimeError("Gemini 影片模型均無法使用")


def save_outputs(workdir, task_id, youtube_url, segments, model=DEFAULT_VIDEO_MODEL):
    workdir.mkdir(parents=True, exist_ok=True)

    json_path = workdir / "segments.json"
    txt_path = workdir / "zh-TW.txt"
    srt_path = workdir / "zh-TW.srt"

    json_path.write_text(
        json.dumps(
            {
                "task_id": task_id,
                "language": "zh-TW",
                "transcript_source": "gemini_youtube",
                "model": model,
                "youtube_url": youtube_url,
                "segments": segments,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    txt_path.write_text(
        "\n".join(x["text"] for x in segments) + "\n",
        encoding="utf-8",
    )

    blocks = []
    for order, seg in enumerate(segments, start=1):
        blocks.append(
            f"{order}\n"
            f"{format_srt_time(seg['start'])} --> {format_srt_time(seg['end'])}\n"
            f"{seg['text']}"
        )
    srt_path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")

    return {
        "json": json_path,
        "txt": txt_path,
        "srt": srt_path,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    drive, sheets = build_google_services()
    task = find_task(sheets, args.task_id)
    if not task:
        raise RuntimeError(f"找不到任務：{args.task_id}")
    if task["period"] is None or not task["lesson"]:
        raise RuntimeError("任務缺少期數或堂次")
    if not task["youtube_url"]:
        raise RuntimeError("任務缺少 YouTube URL")

    run_id = new_run_id(args.task_id, "asr")
    mark_running(
        args.task_id,
        "asr",
        sheets=sheets,
        run_id=run_id,
        message="Gemini 直接讀取 YouTube 產生繁中逐字稿",
        progress=5,
    )
    update_task(
        sheets,
        task["sheet_row"],
        asr="處理中",
        note="Gemini YouTube transcript 執行中",
    )

    try:
        api_key = str(os.environ.get("GEMINI_API_KEY") or "").strip()
        if not api_key:
            api_key = get_secret("GEMINI_API_KEY")

        glossary = get_glossary_terms(sheets)
        prompt = f"""
請完整轉錄這支公開 YouTube 課程影片的實際中文口語內容。

要求：
1. 輸出繁體中文。
2. 忠實逐字，不摘要、不改寫、不補充。
3. 保留講者原意、數字、人名、佛堂與道場專有名詞。
4. 依語意與停頓切成約 15–35 秒一段。
5. start / end 為影片中的秒數，必須遞增。
6. 不要因為字幕或語音不清楚而自行發明內容。
7. 若聽不清楚，保留最保守的可辨識文字。
8. 每個 segment 都必須有 id、start、end、text。
9. 只輸出 schema 要求的 JSON。

優先辨識的專有名詞：
{json.dumps(glossary, ensure_ascii=False)}
"""

        client = GeminiClient(
            api_key=api_key,
            text_model=DEFAULT_VIDEO_MODEL,
            max_attempts=4,
            timeout=240,
        )

        parsed, usage, selected_model = transcribe_youtube_with_model_fallback(
            client, task["youtube_url"], prompt, TRANSCRIPT_SCHEMA
        )

        segments = normalize_transcript(parsed.get("segments") or [])
        workdir = Path("/kaggle/working/gemini-source") / args.task_id
        outputs = save_outputs(
            workdir,
            args.task_id,
            task["youtube_url"],
            segments,
            model=selected_model,
        )

        folders = resolve_lesson_folders(
            drive,
            sheets,
            int(task["period"]),
            task["lesson"],
        )
        for key, name in [
            ("json", "segments.json"),
            ("txt", "zh-TW.txt"),
            ("srt", "zh-TW.srt"),
        ]:
            upload_or_replace_file(
                drive,
                folders["transcript"],
                outputs[key],
                name,
            )

        note = (
            f"Gemini YouTube逐字稿完成；{len(segments)}段；"
            f"model={selected_model}；"
            f"tokens={usage.total_tokens}"
        )
        update_task(
            sheets,
            task["sheet_row"],
            asr="完成",
            note=note,
        )
        mark_done(
            args.task_id,
            "asr",
            sheets=sheets,
            run_id=run_id,
            message=note,
        )
        print(f"[DONE] {note}")
        return 0

    except Exception as exc:
        update_task(
            sheets,
            task["sheet_row"],
            asr="錯誤",
            note=f"Gemini YouTube transcript 失敗：{type(exc).__name__}: {exc}",
        )
        mark_error(
            args.task_id,
            "asr",
            sheets=sheets,
            run_id=run_id,
            exc=exc,
        )
        print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
