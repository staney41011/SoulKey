import os

SPREADSHEET_ID = os.getenv(
    "TRANSLATE_SHEET_ID",
    "1AwPqTqZSzW7Q-gLW4J5d-28dQZwVksyDnvsxNRF2uu8",
)

TASK_SHEET_RANGE = "任務佇列!A2:T"
STATUS_SHEET_NAME = "執行狀態"
STATUS_SHEET_RANGE = "執行狀態!A2:M"
PERIOD_SHEET_RANGE = "期數設定!A2:H"
GLOSSARY_RANGE = "專有名詞庫!A2:A200"
GLOSSARY_FULL_RANGE = "專有名詞庫!A2:J500"

ASR_MODEL = os.getenv(
    "ASR_MODEL",
    "shooding/taiwan-breeze-asr-26",
)

POLISH_MODEL = os.getenv(
    "POLISH_MODEL",
    "Qwen/Qwen3-4B",
)

TRANSLATION_MODEL = os.getenv(
    "TRANSLATION_MODEL",
    "Qwen/Qwen3-4B",
)

TTS_MODELS = {
    "en": "facebook/mms-tts-eng",
    "th": "facebook/mms-tts-tha",
    "es": "facebook/mms-tts-spa",
    "id": "facebook/mms-tts-ind",
    "vi": "facebook/mms-tts-vie",
    "sd": "facebook/mms-tts-snd",
    "ta": "facebook/mms-tts-tam",
}

TIMEZONE = "Asia/Taipei"

# 任務佇列欄位（週次已移除）
COL = {
    "task_id": 0,
    "period": 1,
    "lesson": 2,
    "title": 3,
    "youtube_url": 4,
    "lecturer": 5,
    "source_language": 6,
    "asr": 7,
    "zh_review": 8,
    "en": 9,
    "th": 10,
    "es": 11,
    "id": 12,
    "vi": 13,
    "subtitle": 14,
    "audio": 15,
    "video": 16,
    "progress": 17,
    "updated_at": 18,
    "note": 19,
}
