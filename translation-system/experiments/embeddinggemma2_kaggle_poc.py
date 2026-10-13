"""SoulKey isolated Kaggle T4 EmbeddingGemma 2 cross-modal audio experiment.

Safety: SYNTHETIC Mandarin sentences only; never reads lesson transcripts,
Google Drive, worker nonce, OAuth tokens, or production checkpoint files.
Output: JSON measurements only; not a transcription engine / not a CER test.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

SAMPLE_PAIRS = [
    ("修行不是離開生活，而是在日常中練習覺察自己的起心動念。",
     "日常生活中的修行和自我覺察"),
    ("感恩父母的養育之恩，用溫柔的心對待家人。",
     "感謝父母和關懷家人"),
    ("當發生意見衝突時，先仔細聆聽，再表達自己的想法。",
     "與人發生爭執時先聽對方說話"),
    ("愛護地球從節約用水、減少浪費和垃圾分類開始。",
     "環境保護與減少資源浪費"),
    ("我們每週三舉辦青年班，透過桌遊學習團隊合作。",
     "青年班的桌遊活動和團隊合作"),
    ("學會放下執著，才能在困難之中保持平靜。",
     "放下執念以維持內心平靜"),
    ("人工智慧可以協助課程製作不同國家的字幕與配音。",
     "使用 AI 自動翻譯字幕和語音"),
    ("遇到壓力時透過深呼吸，讓身體和心情慢慢安定。",
     "利用呼吸放鬆與緩解壓力"),
]


def record(report, stage):
    report["stage"] = stage
    print("[EG2-POC]", stage, flush=True)


async def create_synthetic_audio(folder):
    import edge_tts
    import edge_tts.communicate as communicate
    from edge_tts.constants import TRUSTED_CLIENT_TOKEN

    communicate.WSS_URL = (
        "wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1"
        "?Ocp-Apim-Subscription-Key=" + TRUSTED_CLIENT_TOKEN
    )
    paths = []
    durations = []
    for index, (text, _) in enumerate(SAMPLE_PAIRS, 1):
        mp3 = folder / f"synthetic_{index:02d}.mp3"
        wav = folder / f"synthetic_{index:02d}.wav"
        for attempt in (1, 2, 3):
            try:
                await edge_tts.Communicate(
                    text, voice="zh-TW-YunJheNeural",
                    rate="-3%", pitch="-1Hz",
                ).save(str(mp3))
                subprocess.run([
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-i", str(mp3), "-ar", "16000", "-ac", "1",
                    "-c:a", "pcm_s16le", str(wav),
                ], check=True, timeout=60)
                result = subprocess.check_output([
                    "ffprobe", "-v", "error", "-show_entries",
                    "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                    str(wav),
                ], timeout=20, text=True)
                duration = float(result.strip())
                if not (duration > 0.5 and wav.stat().st_size > 1024):
                    raise RuntimeError("synthetic audio empty")
                paths.append(wav)
                durations.append(duration)
                print(f"[EG2-AUDIO] sample={index} duration={duration:.2f}s", flush=True)
                break
            except Exception as exc:
                print(f"[EG2-AUDIO] retry={attempt} sample={index} error={type(exc).__name__}", flush=True)
                if attempt == 3:
                    raise
                await asyncio.sleep(2 * attempt)
    return paths, durations


def norm_matrix(matrix):
    import numpy as np
    result = np.asarray(matrix, dtype=np.float32)
    if result.ndim == 1:
        result = result.reshape(1, -1)
    result = result / np.maximum(np.linalg.norm(result, axis=1, keepdims=True), 1e-12)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    output = Path(args.out)
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "scope": "synthetic Traditional-Chinese audio/text retrieval; NOT ASR",
        "model": "google/embeddinggemma-2",
        "task": "audio_text_retrieval",
        "language": "zh-TW",
        "total_candidates": len(SAMPLE_PAIRS),
        "hardware": {},
        "passed": False,
    }
    scratch = output / "scratch"
    scratch.mkdir(exist_ok=True)
    try:
        import numpy as np
        import torch
        from sentence_transformers import SentenceTransformer
        import sentence_transformers
        import transformers

        report["versions"] = {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "sentence_transformers": sentence_transformers.__version__,
        }
        report["hardware"] = {
            "cuda": torch.cuda.is_available(),
            "gpu_count": torch.cuda.device_count(),
            "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "",
        }
        if not torch.cuda.is_available():
            raise RuntimeError("Kaggle GPU not attached; abort benchmark instead of reporting CPU numbers")

        record(report, "synthesize_zh_TW")
        start = time.monotonic()
        paths, durations = asyncio.run(create_synthetic_audio(scratch))
        report["audio_generation_seconds"] = round(time.monotonic() - start, 3)
        report["audio_seconds_total"] = round(sum(durations), 3)

        record(report, "load_embeddinggemma2")
        torch.cuda.reset_peak_memory_stats(0)
        loaded_at = time.monotonic()
        # T4 does not support bf16; model activations are incompatible with fp16.
        # Official Google docs recommend float32 when bf16 is unavailable.
        model = SentenceTransformer(
            "google/embeddinggemma-2",
            device="cuda",
            config_kwargs={"vision_config": None},
            model_kwargs={"torch_dtype": torch.float32},
        )
        model.eval()
        report["model_load_seconds"] = round(time.monotonic() - loaded_at, 3)
        report["model_dtype"] = str(model.dtype)
        report["embedding_dimensions"] = 768

        record(report, "embed_chinese_text")
        candidates = [t for t, _ in SAMPLE_PAIRS]
        paraphrases = [q for _, q in SAMPLE_PAIRS]
        started = time.monotonic()
        with torch.inference_mode():
            text_vecs = norm_matrix(model.encode(candidates, convert_to_numpy=True, show_progress_bar=False))
            query_vecs = norm_matrix(model.encode(paraphrases, convert_to_numpy=True, show_progress_bar=False))
        report["text_embedding_seconds"] = round(time.monotonic() - started, 3)

        record(report, "embed_chinese_audio")
        audio_vectors = []
        inference_times = []
        with torch.inference_mode():
            for index, path in enumerate(paths, 1):
                torch.cuda.synchronize()
                tick = time.monotonic()
                emb = model.encode({"audio": str(path)}, convert_to_numpy=True, show_progress_bar=False)
                torch.cuda.synchronize()
                elapsed = time.monotonic() - tick
                inference_times.append(elapsed)
                audio_vectors.append(norm_matrix(emb)[0])
                print(f"[EG2-INFERENCE] sample={index} elapsed={elapsed:.3f}s", flush=True)
        audio_vecs = norm_matrix(audio_vectors)
        if audio_vecs.shape != (len(paths), 768):
            raise RuntimeError(f"Unexpected embedding shape: {audio_vecs.shape}")

        report["audio_inference_total_seconds"] = round(sum(inference_times), 3)
        report["audio_realtime_factor"] = round(sum(durations) / sum(inference_times), 3)
        report["gpu_peak_allocated_gb"] = round(torch.cuda.max_memory_allocated(0) / 1024**3, 3)
        report["gpu_peak_reserved_gb"] = round(torch.cuda.max_memory_reserved(0) / 1024**3, 3)

        def rank_results(vecs, label):
            sim = audio_vecs @ vecs.T
            ranks = []
            top_results = []
            for i in range(len(paths)):
                ranked = np.argsort(-sim[i]).tolist()
                rank = ranked.index(i) + 1
                ranks.append(rank)
                top_results.append({
                    "sample_id": i + 1,
                    "correct_rank": rank,
                    "best_candidate_id": ranked[0] + 1,
                    "correct_similarity": round(float(sim[i, i]), 4),
                    "best_similarity": round(float(sim[i, ranked[0]]), 4),
                })
            return {
                "label": label,
                "top1": round(sum(r == 1 for r in ranks) / len(ranks), 4),
                "top3": round(sum(r <= 3 for r in ranks) / len(ranks), 4),
                "median_rank": float(np.median(ranks)),
                "examples": top_results,
            }

        record(report, "score_retrieval")
        report["retrieval_exact_synthetic"] = rank_results(text_vecs, "exact_spoken_text")
        report["retrieval_chinese_paraphrase"] = rank_results(query_vecs, "chinese_paraphrase")
        report["passed"] = True
        record(report, "complete")
        print("[EG2-RESULT]",json.dumps({
            "gpu": report["hardware"]["gpu_name"],
            "audio_seconds": report["audio_seconds_total"],
            "infer_seconds": report["audio_inference_total_seconds"],
            "realtime_factor": report["audio_realtime_factor"],
            "top1_exact": report["retrieval_exact_synthetic"]["top1"],
            "top1_paraphrase": report["retrieval_chinese_paraphrase"]["top1"],
            "gpu_peak_allocated_gb": report["gpu_peak_allocated_gb"],
        }, ensure_ascii=False), flush=True)
    except BaseException as exc:
        report["failure"] = {
            "type": type(exc).__name__,
            "message": str(exc).split("token=")[0][:400],
            "stage": report.get("stage"),
        }
        # Truncate traceback; do not print any secrets or full text/audio.
        print("[EG2-FAIL]", json.dumps(report["failure"], ensure_ascii=False), flush=True)
    finally:
        (output / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # Only the small report is published; synthetic audio is not uploaded.
        shutil.rmtree(scratch, ignore_errors=True)
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
