from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable

from natural_tts_config import DEFAULT_GAP_SPLIT_SECONDS, NATURAL_TTS_PROFILES

_STRONG_END = re.compile(r'[.!?。！？…]+["\'”’）】》]?$')
_PREFIX = re.compile(r'^\s*(?:>>+|[-–—]\s+)')


@dataclass
class SpeechBlock:
    index: int
    segment_ids: list[int]
    source_start: float
    source_end: float
    text: str
    text_sha256: str


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sanitize_text(text: str) -> str:
    value = _PREFIX.sub("", str(text or ""))
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"([!?！？。])\1{2,}", r"\1\1", value)
    return value.strip()


def _trim_token_overlap(previous: str, current: str) -> tuple[str, str]:
    left = previous.split()
    right = current.split()
    for size in range(min(len(left), len(right), 40), 2, -1):
        if left[-size:] == right[:size]:
            removed = " ".join(right[:size])
            if len(removed) >= 12:
                return " ".join(right[size:]).strip(), removed
    return current, ""


def _trim_char_overlap(previous: str, current: str) -> tuple[str, str]:
    for size in range(min(len(previous), len(current), 160), 11, -1):
        if previous[-size:] == current[:size]:
            return current[size:].lstrip(), current[:size]
    return current, ""


def trim_exact_overlap(previous: str, current: str) -> tuple[str, str]:
    previous = sanitize_text(previous)
    current = sanitize_text(current)
    if not previous or not current:
        return current, ""

    text, removed = _trim_token_overlap(previous, current)
    if removed:
        return text, removed
    return _trim_char_overlap(previous, current)


def clean_segments(segments: Iterable[dict]) -> tuple[list[dict], list[dict]]:
    cleaned = []
    report = []
    history = ""

    for order, source in enumerate(segments or []):
        item = dict(source)
        original = sanitize_text(item.get("text") or "")
        text, removed = trim_exact_overlap(history, original)

        if not text:
            report.append({
                "segment_id": int(item.get("id", order)),
                "removed_overlap": removed or original,
                "dropped": True,
            })
            continue

        item["text"] = text
        cleaned.append(item)

        if removed:
            report.append({
                "segment_id": int(item.get("id", order)),
                "removed_overlap": removed,
                "overlap_characters": len(removed),
                "dropped": False,
            })

        history = sanitize_text((history + " " + text).strip())
        history = history[-1200:]

    return cleaned, report


def build_speech_blocks(
    segments: Iterable[dict],
    lang: str,
    gap_split_seconds: float = DEFAULT_GAP_SPLIT_SECONDS,
) -> tuple[list[SpeechBlock], list[dict]]:
    profile = NATURAL_TTS_PROFILES[lang]
    max_chars = int(profile["max_chars"])
    min_chars = int(profile["min_chars"])
    cleaned, overlap_report = clean_segments(segments)

    blocks = []
    current = []
    current_chars = 0

    def flush():
        nonlocal current, current_chars
        if not current:
            return
        text = " ".join(x["text"] for x in current if x.get("text"))
        if text:
            blocks.append(SpeechBlock(
                index=len(blocks) + 1,
                segment_ids=[int(x.get("id", i)) for i, x in enumerate(current)],
                source_start=float(current[0].get("start") or 0),
                source_end=float(current[-1].get("end") or 0),
                text=text,
                text_sha256=_sha(text),
            ))
        current = []
        current_chars = 0

    for idx, seg in enumerate(cleaned):
        text = sanitize_text(seg.get("text") or "")
        if not text:
            continue

        if current and current_chars + len(text) + 1 > max_chars:
            flush()

        current.append(seg)
        current_chars += len(text) + 1

        next_seg = cleaned[idx + 1] if idx + 1 < len(cleaned) else None
        if next_seg is None:
            flush()
            continue

        gap = max(
            0.0,
            float(next_seg.get("start") or 0) - float(seg.get("end") or 0),
        )
        if gap >= gap_split_seconds:
            flush()
        elif _STRONG_END.search(text) and current_chars >= min_chars:
            flush()

    return blocks, overlap_report
