from __future__ import annotations

EDGE_TTS_VERSION = "7.2.8"
NATURAL_TTS_PROFILE_REVISION = "2026-10-07-accent-tone-v2"

LANGUAGE_NAMES = {
    "en": "English",
    "th": "Thai",
    "es": "Spanish",
    "id": "Indonesian",
    "vi": "Vietnamese",
    "hi": "Hindi",
    "ta": "Tamil",
    "ja": "Japanese",
    "ko": "Korean",
}

NATURAL_TTS_PROFILES = {
    "en": {
        "engine": "edge",
        "voice": "en-US-AndrewMultilingualNeural",
        "rate": "-4%",
        "pitch": "-2Hz",
        "max_chars": 460,
        "min_chars": 150,
    },
    "th": {
        "engine": "edge",
        "voice": "th-TH-NiwatNeural",
        "rate": "-3%",
        "pitch": "-1Hz",
        "max_chars": 330,
        "min_chars": 120,
    },
    "es": {
        "engine": "edge",
        "voice": "es-US-AlonsoNeural",
        "rate": "-3%",
        "pitch": "-1Hz",
        "max_chars": 460,
        "min_chars": 150,
    },
    "id": {
        "engine": "edge",
        "voice": "id-ID-ArdiNeural",
        "rate": "-3%",
        "pitch": "-1Hz",
        "max_chars": 440,
        "min_chars": 145,
    },
    "vi": {
        "engine": "edge",
        "voice": "vi-VN-NamMinhNeural",
        "rate": "-3%",
        "pitch": "-1Hz",
        "max_chars": 420,
        "min_chars": 140,
    },
    "ta": {
        "engine": "edge",
        "voice": "ta-IN-ValluvarNeural",
        "rate": "-3%",
        "pitch": "-1Hz",
        "max_chars": 360,
        "min_chars": 120,
    },
    "hi": {
        "engine": "edge",
        "voice": "hi-IN-MadhurNeural",
        "rate": "-3%",
        "pitch": "-1Hz",
        "max_chars": 420,
        "min_chars": 140,
    },
    "ja": {
        "engine": "edge",
        "voice": "ja-JP-KeitaNeural",
        "rate": "-3%",
        "pitch": "-1Hz",
        "max_chars": 260,
        "min_chars": 85,
    },
    "ko": {
        "engine": "edge",
        "voice": "ko-KR-InJoonNeural",
        "rate": "-3%",
        "pitch": "-1Hz",
        "max_chars": 300,
        "min_chars": 100,
    },
}

EDGE_LANGS = tuple(
    lang for lang, profile in NATURAL_TTS_PROFILES.items()
    if profile["engine"] == "edge"
)

GPU_REQUIRED_LANGS = tuple(
    lang for lang, profile in NATURAL_TTS_PROFILES.items()
    if profile["engine"] == "mms"
)

DEFAULT_GAP_SPLIT_SECONDS = 1.5
DEFAULT_BLOCK_PAUSE_SECONDS = 0.12
DEFAULT_TIMELINE_PAUSE_SECONDS = 0.08
MAX_DRIFT_SECONDS = 5.0
MAX_OVER_SOURCE_SECONDS = 3.0
MAX_SPEEDUP = 1.08
# Japanese/Korean neural voices require slightly faster delivery to fit a
# fixed-length lecture. Caps remain language-specific to avoid unnecessary
# acceleration of the other seven languages.
MAX_SPEEDUP_BY_LANGUAGE = {
    "ja": 1.12,
    "ko": 1.16,
}
