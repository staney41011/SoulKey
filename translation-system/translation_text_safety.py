from __future__ import annotations

def has_spoken_content(text: object) -> bool:
    """True for real Unicode letters/numbers; false for symbols and punctuation.

    Any meaningful word, non-Latin script, or numeric text must be preserved.
    Empty strings, whitespace, standalone periods, and subtitle punctuation
    cannot be synthesized as independently spoken sentences.
    """
    return any(character.isalnum() for character in str(text or ""))


def filter_nonspoken_segments(segments: list[dict]) -> tuple[list[dict], list[dict]]:
    """Exclude punctuation-only lines from published target-language manuscripts.

    Keep all surviving source segment IDs and timestamps exactly unchanged.
    The omitted metadata has no spoken text; retain IDs/times for QA auditing.
    """
    spoken, omitted = [], []
    for row in segments:
        if has_spoken_content(row.get("text", "")):
            spoken.append(row)
        else:
            omitted.append({
                "id": row["id"],
                "start": row["start"],
                "end": row["end"],
                "reason": "non_spoken_punctuation_or_symbols",
                # Long punctuation-only windows can hide an upstream
                # transcription gap. Do not invent missing lecture text.
                "source_review_recommended": (
                    float(row["end"]) - float(row["start"]) >= 3.0
                ),
            })
    return spoken, omitted
