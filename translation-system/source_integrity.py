"""Pure timeline checks for SoulKey human-approved manuscripts.

A completed transcription/translation is not evidence of coverage of the
actual lesson. Never silently extend a speech track based on a different
source's timestamps. These checks do not edit human-approved text.
"""
from __future__ import annotations
import math


def bounds(segments):
    if not isinstance(segments, list) or not segments:
        raise ValueError("Empty or invalid timed manuscript")
    first = float("inf")
    last = 0.0
    for row in segments:
        if not isinstance(row, dict):
            raise ValueError("Malformed manuscript segment")
        start = float(row.get("start", -1))
        end = float(row.get("end", -1))
        if not (math.isfinite(start) and math.isfinite(end)
                and 0 <= start < end <= 21600):
            raise ValueError("Invalid manuscript timestamps")
        first = min(first, start)
        last = max(last, end)
    return first, last


def check_english_coverage(english_segments, duration_seconds):
    """Fail closed if the English final cannot represent this source video."""
    source = float(duration_seconds)
    if not math.isfinite(source) or source < 60:
        raise ValueError("Invalid verified video/caption duration")
    start, end = bounds(english_segments)
    if start > 120:
        raise ValueError("English final has no lecture opening")
    if end > source + 12:
        raise ValueError(
            f"English final extends beyond source evidence: {end:.2f}s > "
            f"{source:.2f}s (+12s allowed)"
        )
    if end < source * 0.70:
        raise ValueError(
            f"English final has too little source coverage: {end:.2f}s / "
            f"{source:.2f}s"
        )
    return {"english_end": end, "duration_evidence": source,
            "coverage_ratio": round(min(end / source, 1), 4)}


def compare_chinese_english_end(zh_segments, english_segments, tolerance=90):
    """Report differing source timebases without replacing approved content."""
    _, chinese_end = bounds(zh_segments)
    _, english_end = bounds(english_segments)
    delta = chinese_end - english_end
    return {"needs_review": abs(delta) > float(tolerance),
            "zh_end": round(chinese_end, 3),
            "en_end": round(english_end, 3),
            "difference_seconds": round(delta, 3)}
