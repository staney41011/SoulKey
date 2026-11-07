"""Pure, fail-closed checks for the Sheets-first / Gemma-4 QA lane.

No credentials, Google clients or network calls here. Used by the production
worker and by offline deterministic regression tests.
"""
from __future__ import annotations
import hashlib
import json
import re
import unicodedata

LANG_CODES = ("th","es","id","vi","hi","ta","ja","ko","km","bn","ne","lo","my","it","pt")
QA_VERSION = "sheets-gemma-risk-qa-v1"
# 3 guaranteed unbiased samples / language, in addition to mandatory risk checks
RANDOM_SAMPLE_MIN = 3
BATCH_SIZE = 3
SCRIPT_RANGES = {
    "th": ((0x0E00,0x0E7F),), "hi": ((0x0900,0x097F),),
    "ta": ((0x0B80,0x0BFF),), "ja": ((0x3040,0x30FF),(0x4E00,0x9FFF)),
    "ko": ((0xAC00,0xD7AF),(0x1100,0x11FF)),
    "km": ((0x1780,0x17FF),), "bn": ((0x0980,0x09FF),),
    "ne": ((0x0900,0x097F),), "lo": ((0x0E80,0x0EFF),),
    "my": ((0x1000,0x109F),(0xAA60,0xAA7F)),
}
NUMBERS = re.compile(r"(?<!\w)\d+(?:[.,]\d+)?(?!\w)", re.UNICODE)

def stable_sha(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True,
                                     separators=(",",":")).encode("utf8")).hexdigest()

def text_sha(text):
    return hashlib.sha256(str(text or "").encode("utf8")).hexdigest()

def normalized_numbers(text):
    result=[]
    for token in NUMBERS.findall(str(text or "")):
        val="".join(str(unicodedata.decimal(c)) if c.isdecimal() else c
                    for c in token)
        result.append(val.replace(",", ""))
    return sorted(result)

def _target_script_count(text, language):
    ranges=SCRIPT_RANGES.get(language)
    if not ranges:
        return None
    return sum(any(lo <= ord(ch) <= hi for lo,hi in ranges) for ch in text)

def glossary_hits(english, glossary, lang):
    hits=[]
    for term in glossary:
        en=str(term.get("en") or "").strip()
        if en and len(en)>=3 and en.casefold() in english.casefold():
            hits.append({"term":en,"target":str(term.get(lang) or "").strip(),
                         "locked":bool(term.get("locked")),
                         "note":str(term.get("description") or "")[:160]})
    return hits[:8]

def audit_segment(source, target, language, glossary):
    english=str(source.get("text") or "").strip()
    translated=str(target.get("text") or "").strip()
    hard=[]
    risk=[]
    try:
        if int(source["id"]) != int(target["id"]):
            hard.append("segment_id_mismatch")
        if abs(float(source["start"])-float(target["start"]))>.06 or (
           abs(float(source["end"])-float(target["end"]))>.06):
            hard.append("timeline_changed")
        if float(source["end"])<=float(source["start"]):
            hard.append("bad_source_timing")
    except (TypeError,ValueError,KeyError):
        hard.append("invalid_segment_structure")
    if text_sha(english) != str(target.get("source_hash") or ""):
        hard.append("english_revision_hash_mismatch")
    if not translated:
        hard.append("translation_empty")
    if english and translated.casefold()==english.casefold() and len(english)>=20:
        risk.append("source_language_copied")
    if english and len(translated) < max(6,round(len(english)*.10)):
        risk.append("possible_omission_or_truncation")
    if english and len(translated) > len(english)*4.2 and len(english)>35:
        risk.append("possible_hallucination_or_repetition")
    original_numbers=normalized_numbers(english)
    target_numbers=normalized_numbers(translated)
    # A mismatch can be spelled-out numbers; never silently "repair" digits.
    if original_numbers and original_numbers!=target_numbers:
        risk.append("numeric_semantics_require_review")
    script_count=_target_script_count(translated,language)
    if script_count is not None and len(translated)>=20 and script_count<4:
        risk.append("wrong_or_missing_target_script")
    hits=glossary_hits(english,glossary,language)
    for hit in hits:
        if hit["locked"] and hit["target"] and (
                hit["target"].casefold() not in translated.casefold()):
            risk.append("locked_glossary_term_requires_review:"+hit["term"])
    if hits:
        risk.append("course_specific_terminology")
    return {
        "id":int(source.get("id",-1)), "hard_errors":sorted(set(hard)),
        "risk_flags":sorted(set(risk)),
        "glossary":hits, "source_numbers":original_numbers,
        "target_numbers":target_numbers,
        "source_hash":text_sha(english), "target_hash":text_sha(translated),
    }

def selected_for_review(audits, task_id, lang):
    # Stable uniform samples remain reproducible across retries. Risk is
    # always selected. Structural hard-errors are blocked before model calls.
    selected={a["id"] for a in audits if a["risk_flags"] and not a["hard_errors"]}
    eligible=[a for a in audits if not a["hard_errors"]]
    ranked=sorted(eligible,key=lambda a:hashlib.sha256(
        f"{task_id}|{lang}|{a['id']}|sampling-v1".encode()).digest())
    selected.update(a["id"] for a in ranked[:min(RANDOM_SAMPLE_MIN,len(ranked))])
    return selected

def review_prompt(language, entries):
    """Explain role, original context, mandatory term decisions and hard rules."""
    return (
      "You are the independent language-quality reviewer of a Taiwanese "
      "spiritual-education lecture. Google Translate created the TARGET, "
      "not you. Compare each TARGET strictly with approved English SOURCE; "
      "also use Chinese context when present. Verify meaning, omissions, "
      "addition/hallucinations, numbers/dates, cultural concepts, respectful "
      "spiritual terminology, wrong-language fragments and fluent speech. "
      "Glossary is mandatory only when term marked locked and used in SOURCE. "
      "A numeric mismatch may be correctly written as words: judge meaning. "
      "Do NOT mistrust legitimate romanized proper nouns. Return JSON items "
      "for exactly these IDs, no extras. Grade A = faithful, B = unambiguous "
      "correctable mistake (include complete corrected_text), "
      "C = serious ambiguity/incorrect religious meaning or uncertain "
      "translation requiring manual review. Never invent words or delete "
      "sentences. Plain explanation in English. If uncertain, grade C. "
      "One output per ID, every expected ID mandatory.\n"
      f"TARGET LANGUAGE: {language}\nDATA:\n" +
      json.dumps(entries,ensure_ascii=False,separators=(",",":"))
    )

QA_SCHEMA = {
    "type":"object",
    "properties":{"items":{"type":"array","items":{"type":"object",
        "properties":{
            "id":{"type":"integer"}, "grade":{"type":"string"},
            "reason":{"type":"string"}, "corrected_text":{"type":"string"}
        },
        "required":["id","grade","reason","corrected_text"]
    }}},
    "required":["items"]
}

def parse_model_result(raw, expected_ids):
    rows=raw.get("items")
    if not isinstance(rows,list) or len(rows)!=len(expected_ids):
        raise ValueError("Gemma QA returned missing/extra items")
    by={}
    for x in rows:
        if not isinstance(x,dict) or type(x.get("id")) is not int:
            raise ValueError("Gemma QA segment ID missing")
        sid=x["id"]
        if sid in by or sid not in expected_ids or x.get("grade") not in {"A","B","C"}:
            raise ValueError("Gemma QA invalid or duplicate ID/grade")
        if x["grade"]=="B" and not str(x.get("corrected_text") or "").strip():
            raise ValueError("Gemma proposed empty correction")
        by[sid]={"grade":x["grade"],
                 "reason":str(x.get("reason") or "")[:800],
                 "corrected_text":str(x.get("corrected_text") or "")}
    if set(by)!=set(expected_ids):
        raise ValueError("Gemma QA missing IDs")
    return by

def check_repair(original, proposed, language, audit):
    proposed=str(proposed or "").strip()
    if not proposed or len(proposed)<4:
        return False
    if proposed == str(original.get("text") or ""):
        return False
    if _target_script_count(proposed,language) is not None and (
            _target_script_count(proposed,language)<4 and len(proposed)>20):
        return False
    # Stronger consistency than model alone: locked terminology must survive.
    for hit in audit["glossary"]:
        if hit["locked"] and hit["target"] and (
                hit["target"].casefold() not in proposed.casefold()):
            return False
    return True

def summarize_language(audits, decisions):
    hard_ids=[x["id"] for x in audits if x["hard_errors"]]
    selected_ids={x["id"] for x in audits if x.get("selected_for_ai")}
    reviewed_ids={int(k) for k,v in decisions.items() if v.get("grade")=="A" or
                  v.get("grade")=="B_verified"}
    pending=sorted(selected_ids-reviewed_ids)
    blockers=sorted(set(hard_ids)|set(pending))
    return {
        "state":"approved_risk_based" if not blockers else "needs_review",
        "review_scope":"all_segments_structural_plus_risk_based_gemma4_sample",
        "all_structural_checked":len(audits),
        "model_review_required":len(selected_ids),
        "model_reviewed_pass":len(reviewed_ids & selected_ids),
        "model_not_reviewed_count":len(audits)-len(selected_ids),
        "blocked_segment_ids":blockers,
        "corrected_ids":sorted(int(k) for k,v in decisions.items()
                               if v.get("grade")=="B_verified"),
    }

def gate_ready(records, required_languages):
    blockers=[]
    for lang in required_languages:
        rec=records.get(lang) or {}
        if rec.get("state")!="approved_risk_based":
            blockers.append({"lang":lang,"reason":"semantic_review_incomplete_or_blocked"})
        elif rec.get("review_scope") != "all_segments_structural_plus_risk_based_gemma4_sample":
            blockers.append({"lang":lang,"reason":"review_scope_invalid"})
    return {"ready":not blockers,"scope":"risk_based_not_full_semantic_review",
            "blocked":blockers}
