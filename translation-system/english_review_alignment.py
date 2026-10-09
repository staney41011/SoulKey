"""Sentence-aligned English CC review paragraphs paired with Chinese Final.

Deterministic, zero-AI, zero-GPU alignment. It never rewrites the source CC
or Chinese Final; original cue order and every Chinese segment are retained.
"""
from __future__ import annotations
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def _clock(seconds):
    seconds = int(max(0, float(seconds)))
    return f"{seconds//3600:02d}:{seconds//60%60:02d}:{seconds%60:02d}"


def _english_sentences(cues):
    sentences = []
    current = []
    last_start = None
    for cue in sorted(cues, key=lambda x: float(x.get("start", 0))):
        text = " ".join(str(cue.get("text") or "").split())
        if not text:
            continue
        start = float(cue.get("start") or 0)
        end = max(start, float(cue.get("end") or start))
        # A CC cue may end with "Policy. There is insurance..." -- split it
        # by its actual sentence punctuation rather than cue boundaries.
        offsets = [0] + [
            m.start() for m in re.finditer(
                r'(?<=[.!?])(?=[\s\"”]|$)', text
            ) if 0 < m.start() < len(text)
        ] + [len(text)]
        for a, b in zip(offsets, offsets[1:]):
            part = text[a:b].strip()
            if not part:
                continue
            from_t = start + (end-start) * a/len(text)
            to_t = start + (end-start) * b/len(text)
            current.append((from_t, to_t, part))
            if re.search(r'[.!?][\"”]*$', part):
                sentences.append({
                    "start": current[0][0],
                    "end": current[-1][1],
                    "text": " ".join(x[2] for x in current),
                })
                current = []
    if current:
        sentences.append({
            "start": current[0][0],
            "end": current[-1][1],
            "text": " ".join(x[2] for x in current),
        })
    return sentences


def _english_paragraphs(sentences, target=22, maximum=35):
    groups = []
    index = 0
    while index < len(sentences):
        first = index
        last = first
        while (
            last + 1 < len(sentences)
            and sentences[last]["end"] - sentences[first]["start"] < target
            and sentences[last+1]["end"] - sentences[first]["start"] <= maximum
        ):
            last += 1
        groups.append({
            "start": sentences[first]["start"],
            "end": sentences[last]["end"],
            "text": " ".join(s["text"] for s in sentences[first:last+1])
        })
        index = last + 1
    return groups


def align_english_review(chinese, english_cc, *, task_id, zh_finalized_at="", source_video_id=""):
    if not chinese or not english_cc:
        raise ValueError("Chinese Final and English CC are both required")
    if any(float(b["start"]) < float(a["start"]) for a, b in zip(chinese, chinese[1:])):
        raise ValueError("Chinese segments must be chronological")
    sentences = _english_sentences(english_cc)
    groups = _english_paragraphs(sentences)
    if not groups:
        raise ValueError("No English sentences found")
    if len(groups) > len(chinese):
        raise ValueError("Cannot assign one or more Chinese segments per paragraph")

    aligned = []
    previous_end = -1
    for group_i, eng in enumerate(groups):
        if group_i == len(groups)-1:
            zh_end = len(chinese)-1
        else:
            expected = eng["end"]
            remaining = len(groups)-group_i-1
            choices = range(previous_end+1, len(chinese)-remaining)
            def boundary_score(i):
                row = chinese[i]
                end_time = float(row["end"])
                next_time = float(chinese[i+1]["start"])
                gap = min(3.0, max(0, next_time-end_time))
                completed = str(row.get("text") or "").rstrip().endswith(
                    ("。", "？", "！", ".", "?", "!")
                )
                return abs(end_time-expected) - (0.18*gap) - (0.5 if completed else 0)
            zh_end = min(choices, key=boundary_score)
        chunk = chinese[previous_end+1:zh_end+1]
        if not chunk:
            raise AssertionError("No Chinese text assigned")
        chinese_text = "".join(str(s.get("text") or "").strip() for s in chunk)
        start = float(chunk[0]["start"])
        end = float(chunk[-1]["end"])
        aligned.append({
            "id": int(chunk[0].get("id", previous_end+1)),
            "start": start,
            "end": end,
            "time": _clock(start),
            "text": chinese_text,
            "source_en": eng["text"],
            "en_text": eng["text"],
            "en_confirmed": False,
            "pre_aligned": True,
            "zh_ids": [int(s.get("id", i)) for i,s in enumerate(chunk, previous_end+1)],
            "cc_start": round(eng["start"], 3),
            "cc_end": round(eng["end"], 3),
        })
        previous_end = zh_end

    # Guardrails: preserve all content and exact order, with no duplication.
    source_zh = "".join(str(s.get("text") or "").strip() for s in chinese)
    output_zh = "".join(s["text"] for s in aligned)
    if source_zh != output_zh:
        raise AssertionError("Chinese content mismatch")
    source_en = " ".join(s["text"] for s in sentences)
    output_en = " ".join(s["en_text"] for s in aligned)
    if source_en != output_en:
        raise AssertionError("English content mismatch")
    if any(not x["en_text"] for x in aligned):
        raise AssertionError("Empty English paragraph")
    return {
        "version": 6,
        "task_id": task_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "zh_finalized_at": zh_finalized_at,
        "alignment_method": "english_sentence_chinese_time_v1",
        "source_video_id": source_video_id,
        "total_segments": len(aligned),
        "original_zh_segments": len(chinese),
        "original_en_cc_cues": len(english_cc),
        "segments": aligned,
    }


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--zh", required=True)
    p.add_argument("--en-cc", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--task-id", required=True)
    args = p.parse_args()
    zh = json.loads(Path(args.zh).read_text(encoding="utf-8"))
    en = json.loads(Path(args.en_cc).read_text(encoding="utf-8"))
    result = align_english_review(
        zh["segments"], en["segments"],
        task_id=args.task_id,
        zh_finalized_at=zh.get("finalized_at", ""),
        source_video_id=en.get("video_id", ""),
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("ENGLISH_REVIEW_ALIGNMENT", args.task_id,
          "groups=", result["total_segments"],
          "zh=", result["original_zh_segments"],
          "cc=", result["original_en_cc_cues"])
    for x in result["segments"][:4]:
        print(x["time"], "ZH:", x["text"][:65], "EN:", x["en_text"][:100])


if __name__ == "__main__":
    main()
