import re


LANGUAGE_LABELS = {
    "zh-Hant": "中文",
    "zh-TW": "中文",
    "zh": "中文",
    "en": "英文",
    "en-US": "英文",
    "en-GB": "英文",
    "th": "泰文",
    "es": "西班牙文",
    "es-419": "西班牙文",
    "id": "印尼文",
    "vi": "越南文",
    "hi": "印地語",
    "ta": "泰米爾文",
    "ja": "日文",
    "ko": "韓文",
}


def _clean(value, fallback):
    text = str(value or "").strip()
    if not text:
        text = fallback
    text = re.sub(r'[\\/:*?"<>|]+', " ", text)
    text = re.sub(r"\s+", " ", text).strip(" ._-")
    return text or fallback


def _lesson_number(value):
    match = re.search(r"(\d+)", str(value or ""))
    return int(match.group(1)) if match else 0


def course_title(task):
    raw = str((task or {}).get("title") or "").strip()
    parts = [x.strip() for x in re.split(r"[|｜丨]", raw) if x.strip()]
    if parts:
        raw = parts[0]
    return _clean(raw, "未命名課程")


def lecturer_name(task):
    title = str((task or {}).get("title") or "").strip()
    parts = [x.strip() for x in re.split(r"[|｜丨]", title) if x.strip()]
    if len(parts) >= 2:
        return _clean(parts[1], "未標示講師")
    return _clean((task or {}).get("lecturer"), "未標示講師")


def formal_prefix(task):
    period = int((task or {}).get("period") or 0)
    lesson = _lesson_number((task or {}).get("lesson"))
    return (
        f"第{period}期_第{lesson}堂課_"
        f"{course_title(task)}_{lecturer_name(task)}"
    )


def _lang_label(code):
    code = str(code or "")
    return LANGUAGE_LABELS.get(
        code,
        LANGUAGE_LABELS.get(code.split("-", 1)[0], code or "未知語言"),
    )


def output_label(canonical_name):
    name = str(canonical_name or "").strip()

    fixed = {
        "source_info.json": "來源資訊.json",
        "segments.json": "中文ASR資料.json",
        "zh-TW.txt": "中文ASR時間軸.txt",
        "zh-TW.transcript.txt": "中文純逐字稿.txt",
        "zh-TW.srt": "中文ASR字幕.srt",
        "zh-TW.polished.json": "中文潤稿資料.json",
        "zh-TW.polished.txt": "中文潤稿時間軸.txt",
        "zh-TW.polished.srt": "中文潤稿字幕.srt",
        "zh-TW.readable.txt": "中文潤稿純逐字稿.txt",
        "polish_report.json": "中文潤稿報告.json",
        "zh-TW.final.json": "中文人工定稿資料.json",
        "zh-TW.final.txt": "中文人工定稿時間軸.txt",
        "zh-TW.final.srt": "中文人工定稿字幕.srt",
        "zh-TW.vernacular.json": "白話文稿資料.json",
        "zh-TW.vernacular.txt": "白話文稿時間軸.txt",
        "zh-TW.vernacular.srt": "白話文稿字幕.srt",
        "zh-TW.vernacular.final.json": "白話文人工定稿資料.json",
        "zh-TW.vernacular.final.txt": "白話文人工定稿時間軸.txt",
        "zh-TW.vernacular.final.srt": "白話文人工定稿字幕.srt",
        "youtube-audio-manifest.json": "YouTube音軌清單.json",
        "subtitle_manifest.json": "字幕清單.json",
        "gemini.qa.json": "多語翻譯QA報告.json",
        "gemini-shadow-checkpoint.json": "多語翻譯檢查點.json",
        "zh-TW.review.manifest.json": "中文人工校稿清單.json",
    }
    if name in fixed:
        return fixed[name]

    match = re.fullmatch(
        r"youtube\.([^.]+)\.(transcript\.txt|json|txt|srt|mp3)",
        name,
    )
    if match:
        lang = _lang_label(match.group(1))
        suffix = match.group(2)
        labels = {
            "json": "CC資料.json",
            "txt": "CC時間軸.txt",
            "transcript.txt": "CC純逐字稿.txt",
            "srt": "CC字幕.srt",
            "mp3": "YouTube音軌.mp3",
        }
        return f"{lang}{labels[suffix]}"

    match = re.fullmatch(r"([A-Za-z-]+)\.final\.(json|txt|srt)", name)
    if match:
        lang = _lang_label(match.group(1))
        ext = match.group(2)
        labels = {
            "json": "人工定稿資料.json",
            "txt": "人工定稿時間軸.txt",
            "srt": "人工定稿字幕.srt",
        }
        return f"{lang}{labels[ext]}"

    match = re.fullmatch(r"([A-Za-z-]+)\.(json|txt|srt)", name)
    if match:
        lang = _lang_label(match.group(1))
        ext = match.group(2)
        labels = {
            "json": "翻譯稿資料.json",
            "txt": "翻譯稿時間軸.txt",
            "srt": "翻譯稿字幕.srt",
        }
        return f"{lang}{labels[ext]}"

    match = re.fullmatch(r"([A-Za-z-]+)\.preview\.mp3", name)
    if match:
        return f"{_lang_label(match.group(1))}自然試聽版.mp3"

    match = re.fullmatch(r"([A-Za-z-]+)\.alignment_report\.json", name)
    if match:
        return f"{_lang_label(match.group(1))}TTS對齊報告.json"

    match = re.fullmatch(r"([A-Za-z-]+)\.(mp3|wav)", name)
    if match:
        return f"{_lang_label(match.group(1))}TTS音檔.{match.group(2)}"

    match = re.fullmatch(r"([A-Za-z-]+)\.tts_manifest\.json", name)
    if match:
        return f"{_lang_label(match.group(1))}TTS清單.json"

    match = re.fullmatch(r"([A-Za-z-]+)\.segments\.zip", name)
    if match:
        return f"{_lang_label(match.group(1))}TTS分段音檔.zip"

    match = re.fullmatch(r"zh-TW\.review\.(\d+)\.json", name)
    if match:
        return f"中文人工校稿第{int(match.group(1))}段.json"

    return _clean(name, "輸出檔案")


def formal_drive_name(task, canonical_name):
    return f"{formal_prefix(task)}_{output_label(canonical_name)}"


def canonical_marker(canonical_name):
    return f"SOULKEY_CANONICAL_NAME:{str(canonical_name or '').strip()}"


def canonical_from_description(description):
    text = str(description or "")
    match = re.search(
        r"(?:^|\n)SOULKEY_CANONICAL_NAME:([^\n]+)",
        text,
    )
    return match.group(1).strip() if match else ""


_CANONICAL_FIXED = {
    "source_info.json",
    "segments.json",
    "zh-TW.txt",
    "zh-TW.transcript.txt",
    "zh-TW.srt",
    "zh-TW.polished.json",
    "zh-TW.polished.txt",
    "zh-TW.polished.srt",
    "zh-TW.readable.txt",
    "polish_report.json",
    "zh-TW.final.json",
    "zh-TW.final.txt",
    "zh-TW.final.srt",
    "zh-TW.vernacular.json",
    "zh-TW.vernacular.txt",
    "zh-TW.vernacular.srt",
    "zh-TW.vernacular.final.json",
    "zh-TW.vernacular.final.txt",
    "zh-TW.vernacular.final.srt",
    "youtube-audio-manifest.json",
    "subtitle_manifest.json",
    "gemini.qa.json",
    "gemini-shadow-checkpoint.json",
    "zh-TW.review.manifest.json",
}


def is_canonical_output_name(name):
    value = str(name or "").strip()
    if value in _CANONICAL_FIXED:
        return True
    patterns = (
        r"youtube\.[^.]+\.(?:json|txt|srt|mp3)",
        r"youtube\.[^.]+\.transcript\.txt",
        r"[A-Za-z-]+\.final\.(?:json|txt|srt)",
        r"[A-Za-z-]+\.(?:json|txt|srt|mp3|wav)",
        r"[A-Za-z-]+\.tts_manifest\.json",
        r"[A-Za-z-]+\.segments\.zip",
        r"zh-TW\.review\.\d+\.json",
    )
    return any(re.fullmatch(pattern, value) for pattern in patterns)


def rename_existing_outputs(drive, parent_id, task):
    """Rename legacy technical Drive files without touching their bytes."""
    query = f"'{parent_id}' in parents and trashed = false"
    page_token = None
    renamed = 0
    marked = 0

    while True:
        result = (
            drive.files()
            .list(
                q=query,
                spaces="drive",
                fields="nextPageToken,files(id,name,description)",
                pageSize=200,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        for item in result.get("files", []):
            current = str(item.get("name") or "")
            canonical = (
                canonical_from_description(item.get("description"))
                or (current if is_canonical_output_name(current) else "")
            )
            if not canonical:
                continue

            desired = formal_drive_name(task, canonical)
            marker = canonical_marker(canonical)
            body = {}
            if current != desired:
                body["name"] = desired
                renamed += 1
            if str(item.get("description") or "") != marker:
                body["description"] = marker
                marked += 1
            if body:
                drive.files().update(
                    fileId=item["id"],
                    body=body,
                    fields="id,name,description",
                    supportsAllDrives=True,
                ).execute()

        page_token = result.get("nextPageToken")
        if not page_token:
            break

    return {"renamed": renamed, "marked": marked}
