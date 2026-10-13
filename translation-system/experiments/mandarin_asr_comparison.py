"""Independent Kaggle GPU control experiment for SoulKey's ASR choice.

Uses the SAME synthetic Mandarin samples as the EmbeddingGemma retrieval PoC.
Measures actual transcription character error rate (CER), unlike embeddings.
Does not write back to SoulKey Drive, Studio, transcript or production jobs.
"""
import argparse
import asyncio
import json
import re
import shutil
import time
import unicodedata
from pathlib import Path

from embeddinggemma2_kaggle_poc import SAMPLE_PAIRS, create_synthetic_audio

MODELS = (
    ("production_taigi", "shooding/taiwan-breeze-asr-26"),
    ("mandarin_zhTW", "shooding/faster-whisper-large-v3-zh-TW"),
)


def canonical(text):
    value = unicodedata.normalize("NFKC", str(text))
    try:
        from opencc import OpenCC
        value = OpenCC("s2t").convert(value)
    except ImportError:
        pass
    return "".join(re.findall(r"[\w]", value)).casefold()


def edit_distance(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def benchmark(model, examples):
    from faster_whisper import WhisperModel
    import torch
    import ctranslate2
    gpu_count = torch.cuda.device_count()
    if not gpu_count:
        raise RuntimeError("No Kaggle GPU; refusing to use CPU for ASR timing")
    if ctranslate2.get_cuda_device_count() < 1:
        raise RuntimeError("CTranslate2 cannot access Kaggle CUDA GPUs")
    cuda_id = 1 if gpu_count >= 2 else 0
    warmup_start = time.monotonic()
    asr = WhisperModel(
        model, device="cuda", device_index=cuda_id,
        compute_type="int8_float16",
        download_root="/tmp/soulkey-zh-asr-model-cache",
    )
    load_seconds = round(time.monotonic() - warmup_start, 3)
    samples = []
    cumulative = 0
    infer_start = time.monotonic()
    for i, (audio, expected_text, duration) in enumerate(examples, 1):
        tick = time.monotonic()
        segments, info = asr.transcribe(
            str(audio), language="zh", task="transcribe",
            beam_size=3, best_of=3,
            vad_filter=False, condition_on_previous_text=False,
        )
        output = "".join(x.text for x in segments)
        elapsed = time.monotonic() - tick
        reference = canonical(expected_text)
        hypothesis = canonical(output)
        edits = edit_distance(reference, hypothesis)
        cumulative += edits
        samples.append({
            "sample_id": i,
            "audio_seconds": round(duration, 2),
            "processing_seconds": round(elapsed, 3),
            "reference_characters": len(reference),
            "edit_distance": edits,
            "cer": round(edits / max(1, len(reference)), 4),
        })
        print(
            f"[ASR-TEST] model={model} sample={i} cer={samples[-1]['cer']:.3f}",
            flush=True,
        )
    elapsed = time.monotonic() - infer_start
    return {
        "model": model,
        "cuda_device_index": cuda_id,
        "load_seconds": load_seconds,
        "inference_seconds": round(elapsed, 3),
        "audio_seconds": round(sum(x[2] for x in examples), 3),
        "realtime_factor": round(sum(x[2] for x in examples) / elapsed, 3),
        "cer": round(cumulative / sum(x["reference_characters"] for x in samples), 4),
        "samples": samples,
        "passed": True,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    args = p.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    source_dir = out / "synthetic"
    source_dir.mkdir(exist_ok=True)
    report = {
        "scope": "8 synthetic Taiwan-Mandarin TTS sentences, no real lecture data",
        "benchmark_type": "actual_Chinese_ASR_CER",
        "asr_models": {},
        "all_models_passed": False,
    }
    try:
        import torch
        import ctranslate2
        report["hardware"] = {
            "cuda_available": torch.cuda.is_available(),
            "torch_gpu_count": torch.cuda.device_count(),
            "ctranslate2_gpu_count": ctranslate2.get_cuda_device_count(),
            "gpu_names": [torch.cuda.get_device_name(i)
                          for i in range(torch.cuda.device_count())],
        }
        paths, durations = asyncio.run(create_synthetic_audio(source_dir))
        examples = [(audio, SAMPLE_PAIRS[i][0], durations[i])
                    for i, audio in enumerate(paths)]
        for label, model in MODELS:
            try:
                report["asr_models"][label] = benchmark(model, examples)
            except Exception as exc:
                report["asr_models"][label] = {
                    "passed": False,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc).split("token=")[0][:320],
                }
                print(
                    "[ASR-FAIL]", label, type(exc).__name__,
                    str(exc).split("token=")[0][:160], flush=True,
                )
        report["all_models_passed"] = all(
            x.get("passed") for x in report["asr_models"].values()
        )
        print("[ASR-REPORT]", json.dumps({
            k: {field: v.get(field) for field in
                ("passed","cer","realtime_factor","error_type")}
            for k,v in report["asr_models"].items()
        }), flush=True)
    finally:
        (out / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        shutil.rmtree(source_dir, ignore_errors=True)
    if not report["all_models_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
