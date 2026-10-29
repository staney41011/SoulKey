"""SoulKey's legacy Gemini production quality gates, adapted for Cloud Run.

Reuse the existing gemini_engine.local_language_issue and original numeric QA
rules rather than replacing them with a weaker ad-hoc translation check.
No credentials, network IO, or user data is stored by this module.
"""
import json
import re
import sys
import unicodedata
from decimal import Decimal,InvalidOperation
from pathlib import Path

_LEGACY=Path(__file__).resolve().parents[1]/"translation-system"
if str(_LEGACY) not in sys.path:sys.path.insert(0,str(_LEGACY))
from gemini_engine import local_language_issue

def normalize_unicode_digits(text):
    out = []
    for ch in str(text or ""):
        try:
            if ch.isdigit():
                out.append(str(unicodedata.digit(ch)))
            else:
                out.append(ch)
        except (TypeError, ValueError):
            out.append(ch)
    return "".join(out)


_ENGLISH_SCALED_NUMBER = re.compile(
    r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s+"
    r"(billion|million|trillion|thousand)\b",
    flags=re.IGNORECASE,
)
_CJK_SCALED_NUMBER = re.compile(
    r"(?<![\d.])(\d[\d,]*(?:\.\d+)?)\s*"
    r"(億|亿|억|萬|万|만|兆|조)"
)
_ENGLISH_UNITS = {"thousand":1e3,"million":1e6,"billion":1e9,"trillion":1e12}
_CJK_UNITS = {
    "萬":1e4,"万":1e4,"만":1e4,
    "億":1e8,"亿":1e8,"억":1e8,
    "兆":1e12,"조":1e12,
}


# Italian and Portuguese use a comma as a decimal separator and a dot as
# the thousands separator. Numeric QA must compare values, not substrings:
# 2.5 == 2,5, but 2.5 != 12,5 or 25.
_LOCALE_SOURCE_NUMBER = re.compile(
    r"(?<![\\w])(?:\\d{1,3}(?:,\\d{3})+(?:\\.\\d+)?|\\d+(?:\\.\\d+)?)(?![\\w])"
)
_LOCALE_TARGET_NUMBER = re.compile(r"(?<![\\w])\\d+(?:[.,]\\d+)*(?![\\w])")


def _decimal_localized_number(token):
    """Parse pt/it number tokens conservatively; 2.500 is 2500."""
    value = str(token)
    if "," in value and "." in value:
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    elif "," in value:
        value = value.replace(",", ".")
    elif "." in value:
        parts = value.split(".")
        if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]):
            value = "".join(parts)
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _locale_number_issues(english, target):
    normalized_target = normalize_unicode_digits(target)
    expected = [
        (match.group(), Decimal(match.group().replace(",", "")))
        for match in _LOCALE_SOURCE_NUMBER.finditer(normalize_unicode_digits(english))
    ]
    observed = set()
    for match in _LOCALE_TARGET_NUMBER.finditer(normalized_target):
        token = match.group()
        parsed = _decimal_localized_number(token)
        if parsed is not None:
            observed.add(parsed)
        # The untranslated English decimal spelling is also unambiguous.
        if "." in token and "," not in token:
            parts = token.split(".")
            grouping = len(parts) > 1 and all(len(part) == 3 for part in parts[1:])
            if not grouping:
                try:
                    observed.add(Decimal(token))
                except InvalidOperation:
                    pass
    return [
        f"missing_number:{original}"
        for original, value in expected
        if value not in observed
    ]


def translated_number_issues(english,target,lang):
    """Preserve ACTUAL values, including correct localized magnitudes.

    English 2.5 billion means 25億 / 25억 (2,500,000,000), not
    2.5億 / 2.5억 (250,000,000). A glyph-only check wrongly rejects
    correct 25億 because the literal text "2.5" disappears.
    """
    if lang in {"it", "pt"}:
        return _locale_number_issues(english, target)
    normalized=normalize_unicode_digits(target)
    numbers=re.findall(r"\d+(?:\.\d+)?",english)
    if lang not in {"ja","ko"}:
        return [f"missing_number:{v}" for v in numbers if v not in normalized]

    localized=[
        (float(digits.replace(",",""))*_CJK_UNITS[unit],digits,unit)
        for digits,unit in _CJK_SCALED_NUMBER.findall(normalized)
    ]
    scaled=list(_ENGLISH_SCALED_NUMBER.finditer(english))
    covered=set()
    issues=[]
    for item in scaled:
        digits=item.group(1).replace(",","")
        number=item.group(1)
        unit=item.group(2).lower()
        expected=float(digits)*_ENGLISH_UNITS[unit]
        covered.add(item.start(1))
        if localized:
            correct=any(abs(amount-expected)<=max(1.0,expected*1e-8)
                        for amount,_,_ in localized)
            if not correct:
                issues.append(f"incorrect_number_scale:{number} {unit}")
        elif number not in normalized:
            issues.append(f"missing_number:{number}")
    # Validate every other literal number, but exempt numbers whose value has
    # already been checked after conversion to local units.
    plain=[x for x in re.finditer(r"\d+(?:\.\d+)?",english)
           if x.start() not in covered]
    for item in plain:
        if item.group() not in normalized:
            issues.append(f"missing_number:{item.group()}")
    return issues




def _normalize(source,results):
    expected=[str(x["id"]) for x in source]
    if len(expected)!=len(set(expected)):
        raise ValueError("duplicate_source_segment_ids")
    found={}
    for x in results:
        sid=str(x.get("id",""))
        value=str(x.get("text","")).strip()
        if sid not in expected or sid in found or not value:
            raise ValueError("invalid_or_duplicate_translated_segment")
        found[sid]=value
    if set(found)!=set(expected):raise ValueError("incomplete_translation_segments")
    return found

def _failed_pairs(source,translation,lang,gemini_request):
    local={}
    for item in source:
        sid=str(item["id"]);english=str(item["text"]);target=translation[sid]
        issues=[]
        check=local_language_issue(target,english,lang)
        if check:issues.append(check)
        issues.extend(translated_number_issues(english,target,lang))
        if issues:local[sid]=issues
    # Original production semantic audit: don't flag natural rewording.
    payload=[{"segment_id":item["id"],"english":item["text"],
              "translation":translation[str(item["id"])]} for item in source]
    prompt=("Audit translation accuracy against the approved English source. "
      "Target language="+lang+". Return ONLY a JSON object with key failures, "
      "an array of {segment_id,issue}. Return failures=[] when correct. "
      "Flag ONLY important missing meaning, invented doctrine, wrong numbers, "
      "wrong language or major terminology mistakes. Accept fluent paraphrases "
      "and translated units expressing the same mathematical magnitude. "
      "Never infer outside facts or add ungrounded criticisms.\nDATA:\n"+
      json.dumps(payload,ensure_ascii=False))
    audit=gemini_request(prompt)
    if not isinstance(audit,dict) or not isinstance(audit.get("failures"),list):
        raise ValueError("gemini_semantic_qa_invalid_response")
    semantic={}
    for fail in audit["failures"]:
        sid=str(fail.get("segment_id",""))
        if sid not in translation:raise ValueError("qa_unknown_segment_id")
        reason=str(fail.get("issue","semantic_qa_fail")).strip()
        if reason:semantic.setdefault(sid,[]).append(reason[:300])
    merged={key:list(dict.fromkeys(local.get(key,[])+semantic.get(key,[])))
       for key in (local.keys()|semantic.keys())}
    return merged,len(local),len(semantic)

def audit_and_repair(source,results,language,gemini_request,glossary="",max_rounds=4):
    """Semantic + local QA; only failed pairs repaired. Never publish unresolved QA."""
    translated=_normalize(source,results)
    seenRepairs=0;qaBatches=0
    for start in range(0,len(source),8):
        batch=source[start:start+8]
        ids={str(item["id"]) for item in batch}
        view={sid:translated[sid] for sid in ids}
        failures,localCount,semanticCount=_failed_pairs(batch,view,language,gemini_request)
        qaBatches+=1
        for roundNo in range(1,max_rounds+1):
            if not failures:break
            items=[{"segment_id":x["id"],"english":x["text"],
                "current_translation":view[str(x["id"])],
                "issues":failures[str(x["id"])]}
              for x in batch if str(x["id"]) in failures]
            prompt=("Repair ONLY the listed translations to natural, accurate target language "+
               language+". Preserve every source idea, number, person and example; "
               "no added doctrine and no omissions. Keep source segment IDs. "
               "Follow locked terminology in glossary. Return JSON with key repairs "
               "containing exactly one {id,text} per listed segment.\nGlossary:\n"+
               str(glossary)[:12000]+"\nFAILED:\n"+json.dumps(items,ensure_ascii=False))
            response=gemini_request(prompt)
            repairs=response.get("repairs") if isinstance(response,dict) else None
            if not isinstance(repairs,list):raise ValueError("gemini_repair_invalid_response")
            idsNeeded=set(failures)
            got={}
            for x in repairs:
                sid=str(x.get("id",x.get("segment_id","")))
                txt=str(x.get("text","")).strip()
                if sid not in idsNeeded or sid in got or not txt:
                    raise ValueError("gemini_repair_invalid_segment")
                got[sid]=txt
            if set(got)!=idsNeeded:raise ValueError("gemini_repair_incomplete")
            view.update(got)
            seenRepairs+=len(got)
            failures,localCount,semanticCount=_failed_pairs(batch,view,language,gemini_request)
            qaBatches+=1
        if failures:
            raise ValueError("unresolved_translation_qa_"+language+"_"+
                ",".join(sorted(failures)))
        translated.update(view)
    checked=[{"id":item["id"],"text":translated[str(item["id"])]} for item in source]
    return checked,{"qa_batches":qaBatches,"repairs":seenRepairs,
        "model_quality":"gemini-semantic-and-legacy-local","unresolved":0}
