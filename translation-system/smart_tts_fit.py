"""Opt-in SoulKey A+B smart narration fitter.

Complete translation remains immutable. Only independently audited, shorter
spoken variants replace the corresponding TTS block. Never omit stories,
examples, doctrine, quotations, names, or numerical claims to hit a deadline.
Three bounded passes; no forced tempo change or end-of-speech cutting.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
import unicodedata
from dataclasses import replace
from pathlib import Path

from natural_tts_assemble import assemble_preview, _wav_duration
from natural_tts_edge import render_blocks
from translation_text_safety import has_spoken_content

MAX_REWRITE_ROUNDS = 3
MAX_BLOCKS_PER_ROUND = 8
SAFETY_SECONDS = 0.16

_REWRITE_SCHEMA = {
    "type": "object",
    "properties": {"items": {
        "type": "array", "items": {
            "type": "object",
            "properties": {
                "index": {"type": "integer"},
                "text": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["index", "text", "reason"],
        }
    }},
    "required": ["items"],
}
_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {"items": {
        "type": "array", "items": {
            "type": "object",
            "properties": {
                "index": {"type": "integer"},
                "approved": {"type": "boolean"},
                "reason": {"type": "string"},
            },
            "required": ["index", "approved", "reason"],
        }
    }},
    "required": ["items"],
}


def _numbers(text):
    """Preserve written digits across Unicode numeral sets and punctuation."""
    standardized = []
    for c in str(text):
        if unicodedata.category(c) == "Nd":
            standardized.append(str(unicodedata.digit(c)))
        else:
            standardized.append(c)
    return re.findall(r"\d+(?:[.,]\d+)*", "".join(standardized))


def safe_candidate(original, candidate):
    candidate = str(candidate or "").strip()
    original = str(original or "").strip()
    if not has_spoken_content(candidate):
        return False, "empty_or_punctuation_only"
    if len(candidate) >= len(original) * 0.985:
        return False, "insufficient_text_reduction"
    if sorted(_numbers(original)) != sorted(_numbers(candidate)):
        return False, "numeric_claim_changed"
    return True, "local_checks_passed"


def semantic_pauses(blocks):
    """Small pauses only at natural structural boundaries; never pad the end."""
    pauses = []
    for current, following in zip(blocks, blocks[1:]):
        source_gap = max(0.0, float(following.source_start) - float(current.source_end))
        if source_gap >= 3.0:
            pause = 0.55
        elif source_gap >= 1.0:
            pause = 0.35
        elif re.search(r'[.!?。！？]["\'”’）)]?$', current.text.strip()):
            pause = 0.18
        else:
            pause = 0.12
        pauses.append(pause)
    return pauses


def _duration(blocks, wav_parts):
    return sum(_wav_duration(Path(p)) for p in wav_parts) + sum(semantic_pauses(blocks))


def _anchors(blocks, wav_parts):
    cursor = 0.0
    rows = []
    pauses = semantic_pauses(blocks)
    for i, (block, path) in enumerate(zip(blocks, wav_parts)):
        cursor += _wav_duration(Path(path))
        delta = cursor - float(block.source_end)
        rows.append({
            "block_index": block.index,
            "segment_ids": list(block.segment_ids),
            "source_end": round(float(block.source_end), 3),
            "narration_end": round(cursor, 3),
            "end_offset_seconds": round(delta, 3),
        })
        if i < len(pauses):
            cursor += pauses[i]
    return rows


def _invoke(client, prompt, schema, system_instruction, model=None):
    # Actual Gemini credentials are provisioned outside this module.
    # Respect SoulKey's 5-requests/minute operating quota; mock clients
    # intentionally have no API transport and need no artificial waiting.
    if hasattr(client, "_request"):
        last = getattr(client, "_soulkey_smart_last_call", None)
        now = time.monotonic()
        if last is not None:
            wait = max(0.0, 15.0 - (now - last))
            if wait:
                time.sleep(wait)
        client._soulkey_smart_last_call = time.monotonic()
    kwargs = {"system_instruction": system_instruction, "thinking_level": "low"}
    if model:
        kwargs["model"] = model
    data, _usage = client.structured(
        json.dumps(prompt, ensure_ascii=False), schema, **kwargs,
    )
    return data


def _propose(client, language, originals, current, measured, round_no, over_seconds):
    payload = {
        "language": language,
        "revision_round": round_no,
        "whole_lecture_excess_seconds": round(over_seconds, 2),
        "items": [{
            "index": block.index,
            "original_full_translation": originals[block.index],
            "current_narration": block.text,
            "current_audio_seconds": round(measured[block.index], 2),
        } for block in current],
    }
    data = _invoke(client, payload, _REWRITE_SCHEMA, (
        "You are a native-language narration editor, NOT a summarizer. "
        "Rephrase long sentences into natural concise spoken language. "
        "Keep EVERY story, its sequence and causal chain, ALL doctrine, "
        "illustrations, analogies, exact quotations, named people, places, "
        "numbers, and conclusions. Never merge/delete substantive teaching. "
        "Do not invent content. Do not change script/language. "
        "Leave text unchanged if no safe shortening is possible. "
        "Produce a single revised text for each provided index; "
        "do not swap material between indexes."
    ))
    by_idx = {int(item["index"]): item for item in data.get("items", [])}
    return {
        block.index: by_idx[block.index]
        for block in current if block.index in by_idx
    }


def _audit(client, language, originals, candidates):
    payload = {
        "language": language,
        "items": [{
            "index": idx,
            "original_full_translation": originals[idx],
            "revised_narration": item["text"],
        } for idx, item in candidates.items()],
    }
    review = _invoke(client, payload, _REVIEW_SCHEMA, (
        "You are a separate independent completeness auditor. "
        "Approve ONLY if every original story, sequence, causal detail, "
        "Buddhist/Dao teaching, argument, example, speaker emphasis, "
        "name, entity, number, and conclusion remains faithfully conveyed. "
        "Also reject translation errors, changed speaker meaning, "
        "removed clauses with unique information, or unnatural speech. "
        "Concision without loss is allowed. When uncertain reject. "
        "Return independent approval per index."
    ), model=os.getenv("SOULKEY_SMART_TTS_AUDIT_MODEL", "gemini-3.8-flash"))
    return {int(x["index"]): x for x in review.get("items", [])}


def prepare_smart_narration(
    *,
    language,
    blocks,
    block_results,
    wav_parts,
    source_duration,
    output_dir,
    client_factory=None,
    render_callback=None,
):
    """Build smart WAV preview using approved local revisions only.

    render_callback async signature mirrors natural_tts_edge.render_blocks.
    Original block PCM and checkpoint files are untouched; candidates render
    into isolated round directories and can be rejected without regressions.
    """
    output_dir = Path(output_dir)
    original = {b.index: b.text for b in blocks}
    current = list(blocks)
    paths = [Path(x) for x in wav_parts]
    results = [dict(x) for x in block_results]
    changes = []
    rounds = []
    client = None
    error = ""
    render_callback = render_callback or render_blocks
    source_duration = float(source_duration)

    for number in range(1, MAX_REWRITE_ROUNDS + 1):
        before = _duration(current, paths)
        excess = before + SAFETY_SECONDS - source_duration
        if excess <= 0:
            break
        eligible = [
            (b, _wav_duration(p))
            for b, p in zip(current, paths)
            if len(b.text) >= 95 and has_spoken_content(b.text)
        ]
        eligible.sort(key=lambda pair: pair[1], reverse=True)
        selected = eligible[:MAX_BLOCKS_PER_ROUND]
        if not selected:
            error = "no_editable_long_speech_blocks"
            break
        if client is None:
            try:
                if client_factory is None:
                    raise RuntimeError("Gemini client not configured")
                client = client_factory()
            except Exception as exc:
                error = "editor_unavailable:" + type(exc).__name__
                break
        chosen = [b for b, _ in selected]
        measured = {b.index: seconds for b, seconds in selected}
        try:
            proposed = _propose(
                client, language, original, chosen, measured, number, excess
            )
            candidates = {}
            rejected = []
            for block in chosen:
                item = proposed.get(block.index)
                if not item:
                    rejected.append({"index": block.index, "reason": "missing_proposal"})
                    continue
                valid, reason = safe_candidate(block.text, item.get("text"))
                if valid:
                    candidates[block.index] = item
                else:
                    rejected.append({"index": block.index, "reason": reason})
            if not candidates:
                rounds.append({"round": number, "accepted": [], "rejected": rejected})
                error = "no_safe_shortening_proposed"
                break
            decisions = _audit(client, language, original, candidates)
            approved = {}
            for idx, item in candidates.items():
                verdict = decisions.get(idx, {})
                if verdict.get("approved") is True:
                    approved[idx] = item
                else:
                    rejected.append({
                        "index": idx, "reason": "semantic_review_rejected",
                        "detail": str(verdict.get("reason") or "")[:200],
                    })
            if not approved:
                rounds.append({"round": number, "accepted": [], "rejected": rejected})
                error = "independent_semantic_review_rejected_all"
                break
            staged = [
                replace(b, text=approved[b.index]["text"].strip(),
                        text_sha256=hashlib.sha256(
                            approved[b.index]["text"].strip().encode("utf-8")
                        ).hexdigest())
                for b in current if b.index in approved
            ]
            metas, files = asyncio.run(render_callback(
                lang=language, blocks=staged,
                output_dir=output_dir / f"smart-round-{number}",
                checkpoint_store=None,
            ))
            replacements = {b.index: (b, dict(m), Path(path))
                            for b, m, path in zip(staged, metas, files)}
            accepted = []
            for pos, previous in enumerate(current):
                replacement = replacements.get(previous.index)
                if not replacement:
                    continue
                new_block, meta, trial_path = replacement
                old_sec = _wav_duration(paths[pos])
                new_sec = _wav_duration(trial_path)
                if new_sec >= old_sec - 0.10:
                    rejected.append({
                        "index": previous.index,
                        "reason": "no_measured_audio_saving",
                    })
                    continue
                current[pos] = new_block
                paths[pos] = trial_path
                meta["smart_rewritten"] = True
                results[pos] = meta
                accepted.append(previous.index)
                changes.append({
                    "round": number, "block_index": previous.index,
                    "segment_ids": previous.segment_ids,
                    "before_text": previous.text,
                    "after_text": new_block.text,
                    "reason": str(approved[previous.index].get("reason") or "")[:240],
                    "saved_audio_seconds": round(old_sec - new_sec, 3),
                    "independent_qa": "approved",
                })
            rounds.append({
                "round": number, "accepted": accepted, "rejected": rejected,
                "before_seconds": round(before, 3),
                "after_seconds": round(_duration(current, paths), 3),
            })
            if not accepted:
                error = "revisions_did_not_reduce_audio"
                break
        except Exception as exc:
            error = f"rewrite_round_{number}_failed:{type(exc).__name__}"
            break

    preview_wav = output_dir / f"{language}.preview.wav"
    pauses = semantic_pauses(current)
    preview = assemble_preview(paths, preview_wav, pause_seconds=pauses)
    anchors = _anchors(current, paths)
    worst = max((abs(a["end_offset_seconds"]) for a in anchors), default=0)
    fit = preview["duration"] + SAFETY_SECONDS <= source_duration
    report = {
        "version": "soulkey-a-b-pilot-1",
        "language": language,
        "source_duration_seconds": source_duration,
        "preview_duration_seconds": preview["duration"],
        "within_source_limit_with_margin": fit,
        "passes": rounds,
        "max_passes": MAX_REWRITE_ROUNDS,
        "modified_blocks": len(changes),
        "changes": changes,
        "semantic_pauses_seconds": [round(v, 3) for v in pauses],
        "worst_anchor_offset_seconds": round(worst, 3),
        "anchor_warning": worst > 30.0,
        "anchors": anchors,
        "needs_review_reason": error if not fit else "",
        "original_translation_modified": False,
    }
    script = {
        "language": language,
        "kind": "reviewed_spoken_narration",
        "source_translation_unchanged": True,
        "blocks": [{
            "index": b.index,
            "segment_ids": list(b.segment_ids),
            "source_start": b.source_start,
            "source_end": b.source_end,
            "text": b.text,
            "rewritten": b.text != original[b.index],
        } for b in current],
    }
    script_path = output_dir / f"{language}.narration_script.json"
    report_path = output_dir / f"{language}.smart_fit_report.json"
    script_path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "preview_wav": preview_wav,
        "preview": preview,
        "blocks": current,
        "wav_parts": paths,
        "block_results": results,
        "report": report,
        "report_path": report_path,
        "script_path": script_path,
    }
