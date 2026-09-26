import argparse
import json
import os
from pathlib import Path

from gemini_engine import (
    GeminiClient,
    LANGUAGE_NAMES,
    QA_SCHEMA,
    semantic_polish_zh,
    save_json,
    translate_and_qa,
)


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(
        description="SoulKey Gemini Shadow Runner — 不寫入正式 Drive 輸出"
    )
    parser.add_argument(
        "--mode",
        choices=["smoke", "translate", "polish", "tts"],
        required=True,
    )
    parser.add_argument("--source-json")
    parser.add_argument("--glossary-json")
    parser.add_argument("--lang", choices=list(LANGUAGE_NAMES))
    parser.add_argument("--output-dir", default="/kaggle/working/gemini-shadow")
    parser.add_argument("--text")
    parser.add_argument("--voice", default="Kore")
    parser.add_argument("--with-tts", action="store_true")
    args = parser.parse_args()

    client = GeminiClient()
    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    if args.mode == "smoke":
        parsed, usage = client.structured(
            "Return one QA item for id=1 and mark pass=true. "
            "This is an API connectivity test only.",
            QA_SCHEMA,
            system_instruction="Return schema-compliant JSON only.",
            thinking_level="low",
        )
        save_json(outdir / "smoke.json", {
            "ok": True,
            "model": client.text_model,
            "response": parsed,
            "usage": usage.__dict__,
        })
        print("[GEMINI-SHADOW] text smoke PASS")

        if args.with_tts:
            audio, mime, tts_usage = client.tts(
                "This is a SoulKey Gemini shadow test.",
                voice=args.voice,
                style="calm and clear",
            )
            (outdir / "smoke.wav").write_bytes(audio)
            save_json(outdir / "smoke-tts.json", {
                "ok": True,
                "model": client.tts_model,
                "mime_type": mime,
                "bytes": len(audio),
                "usage": tts_usage.__dict__,
            })
            print("[GEMINI-SHADOW] tts smoke PASS")
        return 0

    if args.mode == "tts":
        text = str(args.text or "").strip()
        if not text:
            parser.error("--mode tts 需要 --text")
        audio, mime, usage = client.tts(text, voice=args.voice)
        (outdir / "shadow.wav").write_bytes(audio)
        save_json(outdir / "shadow-tts.json", {
            "model": client.tts_model,
            "mime_type": mime,
            "bytes": len(audio),
            "usage": usage.__dict__,
        })
        print("[GEMINI-SHADOW] TTS PASS")
        return 0

    if not args.source_json:
        parser.error("--mode translate/polish 需要 --source-json")
    payload = load_json(args.source_json)
    glossary = []
    if args.glossary_json:
        glossary = load_json(args.glossary_json)
        if isinstance(glossary, dict):
            glossary = glossary.get("rows") or glossary.get("values") or []

    if args.mode == "translate":
        if not args.lang or args.lang == "en":
            parser.error("--mode translate 需要非英文 --lang")
        result = translate_and_qa(
            client,
            payload,
            args.lang,
            glossary_rows=glossary,
        )
        save_json(outdir / f"{args.lang}.shadow.json", result)
        print(
            f"[GEMINI-SHADOW] {args.lang} QA "
            f"PASS={result['qa_pass_count']} FAIL={result['qa_fail_count']}"
        )
        return 0 if result["qa_fail_count"] == 0 else 2

    result = semantic_polish_zh(
        client,
        payload,
        glossary_rows=glossary,
    )
    save_json(outdir / "zh.semantic.shadow.json", result)
    print(
        f"[GEMINI-SHADOW] 中文第二層校稿完成："
        f"changed={result['changed_count']} "
        f"candidate_terms={len(result['term_candidates'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
