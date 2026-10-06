import argparse
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from config import (
    COL,
    SPREADSHEET_ID,
    TASK_SHEET_RANGE,
    TIMEZONE,
    TTS_MODELS,
)
from drive_naming import formal_drive_name
from google_io import (
    build_google_services,
    download_drive_file,
    find_file,
    read_values,
    update_cells,
    upload_or_replace_file,
)
from lesson_paths import digits, resolve_lesson_folders
from youtube_io import download_multilingual_audio_tracks

LANGUAGE_NAMES = {
    "en": "English",
    "th": "Thai",
    "es": "Spanish",
    "id": "Indonesian",
    "vi": "Vietnamese",
    "hi": "Hindi",
    "ta": "Tamil",
}
from tts_engine import segments_fingerprint, synthesize_language
from status_io import new_run_id, mark_running, mark_done, mark_needs_review, mark_error


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
        "title": str(row[COL["title"]] or "").strip(),
        "lecturer": str(row[COL["lecturer"]] or "").strip(),
        "youtube_url": str(row[COL["youtube_url"]] or "").strip(),
        "en": str(row[COL["en"]] or "").strip(),
        "th": str(row[COL["th"]] or "").strip(),
        "es": str(row[COL["es"]] or "").strip(),
        "id": str(row[COL["id"]] or "").strip(),
        "vi": str(row[COL["vi"]] or "").strip(),
        "audio": str(row[COL["audio"]] or "").strip(),
    }


def update_audio_status(sheets, row, status, note):
    update_cells(
        sheets,
        SPREADSHEET_ID,
        {
            f"任務佇列!P{row}": status,
            f"任務佇列!S{row}": now_text(),
            f"任務佇列!T{row}": note[:450],
        },
    )


def _english_overlap_key(token):
    import re
    return re.sub(
        r"^[^a-z0-9]+|[^a-z0-9]+$",
        "",
        str(token or "").lower(),
    )


def _trim_english_segment_overlap(previous_text, next_text):
    import re
    previous = re.sub(r"\s+", " ", str(previous_text or "")).strip().split()
    current = re.sub(r"\s+", " ", str(next_text or "")).strip().split()
    maximum = min(len(previous), len(current), 40)

    for size in range(maximum, 2, -1):
        left = [_english_overlap_key(x) for x in previous[-size:]]
        right = [_english_overlap_key(x) for x in current[:size]]
        if not all(left) or not all(right):
            continue
        if len(" ".join(left)) < 12:
            continue
        if left == right:
            return " ".join(current[size:]).strip()
    return " ".join(current).strip()


def _dedupe_english_segments_for_tts(segments):
    cleaned = []
    history = ""

    for index, source in enumerate(segments or []):
        item = dict(source)
        text = _trim_english_segment_overlap(
            history,
            item.get("text") or "",
        )
        if not text:
            continue
        item["text"] = text
        cleaned.append(item)
        history = (history + " " + text).strip()
        # Only a bounded suffix is needed for rolling-caption overlap checks.
        history = " ".join(history.split()[-120:])

    if len(cleaned) != len(segments or []):
        print(
            f"[TTS:en] rolling overlap cleanup: "
            f"{len(segments or [])} -> {len(cleaned)} segments",
            flush=True,
        )
    return cleaned


def load_translation_from_drive(drive, folder_id, lang, workdir):
    # English 已經有人工 Final，TTS 必須讀 en.final.json。
    # 其他目標語言則直接讀 AI 翻譯輸出的 <lang>.json。
    candidates = (
        ["en.final.json", "en.json"]
        if lang == "en"
        else [f"{lang}.json"]
    )

    item = None
    selected_name = ""
    for name in candidates:
        item = find_file(drive, folder_id, name)
        if item:
            selected_name = name
            break

    if not item:
        raise RuntimeError(
            "找不到翻譯檔：" + " / ".join(candidates)
        )

    path = workdir / selected_name
    download_drive_file(drive, item["id"], path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    segments = payload.get("segments") or []
    if not segments:
        raise RuntimeError(f"{selected_name} 沒有 segments")

    if lang == "en":
        segments = _dedupe_english_segments_for_tts(segments)
        if not segments:
            raise RuntimeError(f"{selected_name} 去除重複後沒有可朗讀內容")

    print(
        f"[TTS:{lang}] 使用翻譯稿：{selected_name}",
        flush=True,
    )
    return segments


def _base_language(value):
    return str(value or "").strip().lower().replace("_", "-").split("-", 1)[0]


def _youtube_audio_for_requested(downloaded, requested_lang):
    wanted = _base_language(requested_lang)
    if not wanted:
        return None

    exact = [
        item for item in downloaded
        if str(item.get("language") or "").strip().lower() == str(requested_lang).lower()
    ]
    if exact:
        return exact[0]

    for item in downloaded:
        if _base_language(item.get("language")) == wanted:
            return item
    return None


def acquire_youtube_audio_first(task, langs, workdir):
    """Try YouTube language audio before any TTS model is loaded.

    YouTube CC text itself has no audio.  What we can reuse is the video's
    alternate / auto-dubbed language audio track exposed by yt-dlp.  Any
    requested language found here becomes the authoritative audio source and
    must not be synthesized again.
    """
    url = str(task.get("youtube_url") or "").strip()
    if not url:
        return {}, None, "任務沒有 YouTube URL"

    youtube_dir = workdir / "youtube-audio"
    youtube_dir.mkdir(parents=True, exist_ok=True)

    try:
        manifest, manifest_path = download_multilingual_audio_tracks(
            url,
            youtube_dir,
            requested_languages=langs,
            preferred_codec="mp3",
        )
    except Exception as exc:
        return {}, None, f"{type(exc).__name__}: {exc}"

    downloaded = list(manifest.get("downloaded") or [])
    matched = {}
    for lang in langs:
        item = _youtube_audio_for_requested(downloaded, lang)
        if item:
            matched[lang] = item

    available = [
        str(item.get("language") or "").strip()
        for item in (manifest.get("tracks") or [])
        if str(item.get("language") or "").strip()
    ]
    failures = list(manifest.get("failures") or [])
    parts = []
    if available:
        parts.append("可見音軌=" + ",".join(available))
    else:
        parts.append("可見音軌=無")
    if failures:
        failure_text = ",".join(
            str(x.get("language") or "?") + ":" +
            str(x.get("error") or "download_failed")[:90]
            for x in failures[:6]
        )
        parts.append("下載失敗=" + failure_text)

    diagnostic = "；".join(parts)
    return matched, (manifest, manifest_path), diagnostic


def upload_youtube_audio_outputs(
    drive,
    audio_folder,
    task,
    matched,
    manifest_bundle,
):
    uploaded = {}
    for requested_lang, item in matched.items():
        path = Path(item["path"])
        actual_lang = str(item.get("language") or requested_lang).strip()
        # Never trust a legacy local filename such as "youtube.mp3".
        # The canonical Drive name must always retain the discovered language.
        canonical_name = f"youtube.{actual_lang}.mp3"
        upload_or_replace_file(
            drive,
            audio_folder,
            path,
            canonical_name,
            display_name=formal_drive_name(task, canonical_name),
        )
        uploaded[requested_lang] = {
            "language": actual_lang,
            "canonical_name": canonical_name,
            "format_id": item.get("format_id") or "",
            "is_dubbed_hint": bool(item.get("is_dubbed_hint")),
        }

    if manifest_bundle:
        manifest, manifest_path = manifest_bundle
        final_manifest = dict(manifest)
        final_manifest["selected_as_primary_audio"] = uploaded
        manifest_path.write_text(
            json.dumps(final_manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        upload_or_replace_file(
            drive,
            audio_folder,
            manifest_path,
            "youtube-audio-manifest.json",
            display_name=formal_drive_name(task, "youtube-audio-manifest.json"),
        )

    return uploaded


def upload_tts_outputs(drive, audio_folder, result, task):
    for key in ("mp3", "wav", "manifest", "segments_zip"):
        path = result[key]
        canonical_name = Path(path).name
        upload_or_replace_file(
            drive,
            audio_folder,
            path,
            canonical_name,
            display_name=formal_drive_name(task, canonical_name),
        )


def existing_mms_output(drive, audio_folder, lang, source_sha256):
    manifest_item = find_file(
        drive,
        audio_folder,
        f"{lang}.tts_manifest.json",
    )
    if not manifest_item:
        return False

    temp = Path("/kaggle/working/translate-system-tts-cache") / (
        f"{lang}.tts_manifest.json"
    )
    temp.parent.mkdir(parents=True, exist_ok=True)
    try:
        download_drive_file(drive, manifest_item["id"], temp)
        manifest = json.loads(temp.read_text(encoding="utf-8"))
    except Exception:
        return False

    if str(manifest.get("model") or "") != TTS_MODELS[lang]:
        return False
    if str(manifest.get("source_sha256") or "") != str(source_sha256 or ""):
        return False

    return bool(
        find_file(drive, audio_folder, f"{lang}.wav")
        and find_file(drive, audio_folder, f"{lang}.mp3")
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", default=None)
    parser.add_argument("--period", type=int, default=None)
    parser.add_argument("--lang", choices=list(LANGUAGE_NAMES), default=None)
    parser.add_argument(
        "--langs",
        default=None,
        help="逗號分隔多語言，例如 en,es；只處理指定語言",
    )
    parser.add_argument("--all-langs", action="store_true")
    parser.add_argument("--max-tasks", type=int, default=1)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if sum(bool(x) for x in [args.lang, args.langs, args.all_langs]) != 1:
        parser.error("請擇一指定 --lang、--langs en,es 或 --all-langs")

    if args.all_langs:
        langs = list(LANGUAGE_NAMES)
    elif args.langs:
        langs = [x.strip() for x in args.langs.split(",") if x.strip()]
        invalid = [x for x in langs if x not in LANGUAGE_NAMES]
        if invalid:
            parser.error("不支援的語言代碼：" + ",".join(invalid))
        # 去重但保留順序
        langs = list(dict.fromkeys(langs))
    else:
        langs = [args.lang]

    print("=" * 72)
    print("打開心靈的鎖匙｜多語 TTS")
    print("引擎：Meta MMS-TTS / VITS（全語言本地模型推論）")
    print("=" * 72)

    drive, sheets = build_google_services()
    rows = read_values(sheets, SPREADSHEET_ID, TASK_SHEET_RANGE)

    tasks = []
    for index, raw in enumerate(rows, start=2):
        task = row_to_task(raw, index)
        if not task["task_id"] or task["period"] is None or not task["lesson"]:
            continue
        if args.period is not None and task["period"] != args.period:
            continue
        if args.task_id and task["task_id"] != args.task_id:
            continue
        tasks.append(task)

    if not tasks:
        print("沒有符合條件的任務。")
        return 0

    processed = 0
    any_failed = False
    for task in tasks:
        if processed >= args.max_tasks:
            break

        print("")
        print("-" * 72)
        print(f"[TASK] {task['task_id']} / 第{task['period']}期 / {task['lesson']}")

        status_stage = "tts"
        run_id = new_run_id(task["task_id"], status_stage)
        mark_running(
            task["task_id"],
            status_stage,
            sheets=sheets,
            run_id=run_id,
            message="音檔生成中：" + ",".join(langs),
            progress=0,
        )

        try:
            folders = resolve_lesson_folders(
                drive,
                sheets,
                task["period"],
                task["lesson"],
            )
            workdir = Path("/kaggle/working/translate-system-tts") / task["task_id"]
            workdir.mkdir(parents=True, exist_ok=True)

            update_audio_status(
                sheets,
                task["sheet_row"],
                "處理中",
                "多語音檔生成中",
            )

            completed = []
            failed = []
            over_duration = []
            youtube_completed = []
            tts_completed = []

            # Priority 1: YouTube alternate / auto-dubbed audio tracks.
            # This runs once for all requested languages before translations or
            # TTS models are loaded.  Missing languages fall through to TTS.
            youtube_matches, youtube_manifest_bundle, youtube_probe_error = (
                acquire_youtube_audio_first(task, langs, workdir)
            )
            youtube_uploaded = {}
            if youtube_matches:
                youtube_uploaded = upload_youtube_audio_outputs(
                    drive,
                    folders["audio"],
                    task,
                    youtube_matches,
                    youtube_manifest_bundle,
                )
                print(
                    "[YOUTUBE-AUDIO] 作為正式音檔來源：" +
                    ",".join(youtube_uploaded.keys()),
                    flush=True,
                )
                if youtube_probe_error:
                    print(
                        "[YOUTUBE-AUDIO] 探測摘要：" + youtube_probe_error,
                        flush=True,
                    )
            elif youtube_probe_error:
                print(
                    "[YOUTUBE-AUDIO] 沒有可用的指定語言音軌；"
                    "缺少語言才進本地 TTS。原因=" + youtube_probe_error,
                    flush=True,
                )

            for lang in langs:
                lang_stage = f"tts:{lang}"
                lang_run_id = new_run_id(task["task_id"], lang_stage)
                mark_running(
                    task["task_id"],
                    lang_stage,
                    sheets=sheets,
                    run_id=lang_run_id,
                    message=f"{LANGUAGE_NAMES[lang]} 音檔生成中",
                    progress=0,
                )

                try:
                    if lang in youtube_uploaded:
                        selected = youtube_uploaded[lang]
                        completed.append(lang)
                        youtube_completed.append(lang)
                        actual_lang = selected.get("language") or lang
                        canonical_name = selected.get("canonical_name") or ""
                        message = (
                            f"{LANGUAGE_NAMES[lang]} 使用 YouTube "
                            f"{actual_lang} 多語／自動配音音軌；"
                            "不產生 TTS"
                        )
                        print(
                            f"[YOUTUBE-AUDIO:{lang}] {canonical_name}；skip TTS",
                            flush=True,
                        )
                        mark_done(
                            task["task_id"],
                            lang_stage,
                            sheets=sheets,
                            run_id=lang_run_id,
                            message=message,
                        )
                        continue

                    # Only languages missing a YouTube audio track enter TTS.
                    # Resume is valid only when the stored manifest was built
                    # from exactly this text/timing revision.
                    segments = load_translation_from_drive(
                        drive,
                        folders["translation"],
                        lang,
                        workdir,
                    )
                    source_sha256 = segments_fingerprint(segments)

                    if (
                        not args.force
                        and existing_mms_output(
                            drive,
                            folders["audio"],
                            lang,
                            source_sha256,
                        )
                    ):
                        print(
                            f"[TTS:{lang}] Drive 已有相同來源版本的完整 Meta MMS 音檔，略過重做",
                            flush=True,
                        )
                        completed.append(lang)
                        tts_completed.append(lang)
                        mark_done(
                            task["task_id"],
                            lang_stage,
                            sheets=sheets,
                            run_id=lang_run_id,
                            message=(
                                f"{LANGUAGE_NAMES[lang]} Meta MMS 音檔來源版本一致，略過重做"
                            ),
                        )
                        continue

                    print(f"[TTS] {LANGUAGE_NAMES[lang]} ({lang})")
                    source_duration = max(
                        float(seg.get("end", 0) or 0)
                        for seg in segments
                    )
                    result = synthesize_language(
                        segments=segments,
                        lang=lang,
                        model_id=TTS_MODELS[lang],
                        output_dir=workdir / f"tts-{lang}",
                        target_duration=source_duration,
                    )
                    upload_tts_outputs(drive, folders["audio"], result, task)
                    completed.append(lang)
                    tts_completed.append(lang)

                    if not result["within_source_duration"]:
                        over_duration.append({
                            "lang": lang,
                            "over": result["over_by_seconds"],
                        })
                        lang_note = (
                            f"{LANGUAGE_NAMES[lang]} 音檔已產生；"
                            f"自然朗讀超過原片 {result['over_by_seconds']:.1f}s；"
                            "未調速、未截斷"
                        )
                        print(
                            f"[WARN] {lang}: 自然朗讀超過原片 "
                            f"{result['over_by_seconds']:.1f}s；未調速、未截斷。"
                        )
                        mark_needs_review(
                            task["task_id"],
                            lang_stage,
                            sheets=sheets,
                            run_id=lang_run_id,
                            message=lang_note,
                        )
                    else:
                        lang_note = (
                            f"{LANGUAGE_NAMES[lang]} 音檔完成；"
                            f"speech={result['speech_duration']:.1f}s；"
                            f"target={result['target_duration']:.1f}s"
                        )
                        print(
                            f"[DONE] {lang}: speech={result['speech_duration']:.1f}s / "
                            f"target={result['target_duration']:.1f}s / "
                            f"尾端靜音={result['remaining_silence']:.1f}s"
                        )
                        mark_done(
                            task["task_id"],
                            lang_stage,
                            sheets=sheets,
                            run_id=lang_run_id,
                            message=lang_note,
                        )

                except Exception as lang_exc:
                    lang_message = (
                        f"{type(lang_exc).__name__}: {lang_exc}"
                    )
                    failed.append({
                        "lang": lang,
                        "error": lang_message,
                    })
                    print(
                        f"[ERROR] TTS:{lang} 失敗，但其他語言繼續："
                        f"{lang_message}",
                        file=sys.stderr,
                        flush=True,
                    )
                    mark_error(
                        task["task_id"],
                        lang_stage,
                        sheets=sheets,
                        run_id=lang_run_id,
                        exc=lang_exc,
                    )
                    continue

            youtube_probe_note = (
                youtube_probe_error[:220]
                if youtube_probe_error
                else ""
            )

            if failed:
                status = "部分完成"
                failure_details = "｜".join(
                    f"{item['lang']}={item['error']}"
                    for item in failed
                )
                note = (
                    f"音檔完成：{','.join(completed) or '無'}；"
                    f"YouTube優先：{','.join(youtube_completed) or '無'}；"
                    f"YouTube偵測：{youtube_probe_note or '未提供摘要'}；"
                    f"TTS補缺：{','.join(tts_completed) or '無'}；"
                    f"失敗：{','.join(x['lang'] for x in failed)}；"
                    f"原因：{failure_details}；"
                    "單一語言錯誤不阻擋其他語言"
                )
                if over_duration:
                    note += "；另有超時：" + ",".join(
                        f"{item['lang']}+{item['over']:.1f}s"
                        for item in over_duration
                    )
            elif over_duration:
                status = "待人工確認"
                over_text = ",".join(
                    f"{item['lang']}+{item['over']:.1f}s"
                    for item in over_duration
                )
                note = (
                    f"音檔完成：{','.join(completed)}；"
                    f"YouTube優先：{','.join(youtube_completed) or '無'}；"
                    f"YouTube偵測：{youtube_probe_note or '未提供摘要'}；"
                    f"TTS補缺：{','.join(tts_completed) or '無'}；"
                    f"超過原片總長：{over_text}；"
                    "未調速、未截斷，請先處理超時語言"
                )
            elif len(completed) == len(langs):
                status = "完成"
                note = (
                    f"音檔完成：{','.join(completed)}；"
                    f"YouTube優先：{','.join(youtube_completed) or '無'}；"
                    f"YouTube偵測：{youtube_probe_note or '未提供摘要'}；"
                    f"TTS補缺：{','.join(tts_completed) or '無'}"
                )
            else:
                status = "部分完成"
                note = (
                    f"音檔完成：{','.join(completed)}；"
                    f"YouTube優先：{','.join(youtube_completed) or '無'}；"
                    f"YouTube偵測：{youtube_probe_note or '未提供摘要'}；"
                    f"TTS補缺：{','.join(tts_completed) or '無'}"
                )

            update_audio_status(
                sheets,
                task["sheet_row"],
                status,
                note,
            )

            if failed:
                # A single language can fail while the other requested
                # languages remain valid deliverables. Keep the aggregate
                # audio stage as needs_review / partial instead of turning the
                # entire Kaggle worker into a technical failure. The failed
                # language keeps its own tts:<lang> error status.
                mark_needs_review(
                    task["task_id"],
                    status_stage,
                    sheets=sheets,
                    run_id=run_id,
                    message=note,
                )
            elif status == "完成":
                mark_done(
                    task["task_id"],
                    status_stage,
                    sheets=sheets,
                    run_id=run_id,
                    message=note,
                )
            else:
                mark_needs_review(
                    task["task_id"],
                    status_stage,
                    sheets=sheets,
                    run_id=run_id,
                    message=note,
                )

            processed += 1

        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            print(f"[ERROR] {message}", file=sys.stderr)
            traceback.print_exc()
            update_audio_status(
                sheets,
                task["sheet_row"],
                "錯誤",
                message,
            )
            mark_error(
                task["task_id"],
                status_stage,
                sheets=sheets,
                run_id=run_id,
                exc=exc,
            )
            any_failed = True
            processed += 1

    print("")
    print("TTS 本次處理完成。")
    if any_failed:
        print(
            "[TTS ERROR] 發生工作層級錯誤；請查看狀態與 log。",
            file=sys.stderr,
            flush=True,
        )
        return 1

    print(
        "[TTS] 音檔階段結束；單一語言若失敗會保留為 needs_review，"
        "不再讓整個 Kaggle Job 失敗。",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
