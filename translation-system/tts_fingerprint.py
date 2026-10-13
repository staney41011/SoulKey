"""Stable source-revision fingerprint shared by CPU and GPU TTS.

No numpy/torch/scipy/transformers imports: Edge Neural audio must work with
only the lightweight Google API/Edge TTS dependencies.
Keep semantics identical to tts_engine.segments_fingerprint.
"""
from __future__ import annotations

import hashlib
import json


def segments_fingerprint(segments):
    canonical = []
    for i, seg in enumerate(segments or []):
        if not isinstance(seg, dict):
            continue
        text = str(seg.get("text") or "").strip()
        if not text:
            continue
        canonical.append({
            "id": int(seg.get("id", i)),
            "start": float(seg.get("start", 0) or 0),
            "end": float(seg.get("end", 0) or 0),
            "text": text,
        })
    raw = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
