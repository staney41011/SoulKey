"""CPU-only test suite for opt-in A+B multilingual narration fitting."""
import asyncio
import json
import math
import sys
import tempfile
import unittest
import wave
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from smart_tts_fit import (
    MAX_REWRITE_ROUNDS, _numbers, safe_candidate,
    semantic_pauses, prepare_smart_narration,
)
from natural_tts_planner import SpeechBlock
from natural_tts_assemble import assemble_preview, _wav_duration


def pcm(path, seconds, rate=8000):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(bytes(round(seconds*rate)*2))
    return path


def block(index, text, start=0, end=5):
    import hashlib
    return SpeechBlock(
        index=index, segment_ids=[index], source_start=start, source_end=end,
        text=text, text_sha256=hashlib.sha256(text.encode("utf8")).hexdigest(),
    )


class MockGemini:
    def __init__(self, approve=True):
        self.approve = approve
        self.calls = []
    def structured(self, prompt, schema, *, system_instruction="", thinking_level="low", model=None):
        payload=json.loads(prompt)
        is_audit="independent completeness auditor" in system_instruction
        self.calls.append("audit" if is_audit else "rewrite")
        if is_audit:
            return {"items":[{"index":x["index"],"approved":self.approve,
                               "reason":"no substantive omissions" if self.approve
                                        else "story causal link missing"}
                              for x in payload["items"]]}, None
        return {"items":[{
            "index":x["index"],
            "text":"A kind elder explains the teaching, recounts the same family "
                   "story, and reminds everyone to be compassionate.",
            "reason":"replaced verbose connective phrasing only",
        } for x in payload["items"]]}, None


class SmartFitTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)
        self.source_text=(
            "Our kind elder explains the teaching with several extended "
            "connective phrases while recounting the very same family story, "
            "and in closing reminds every participant to be compassionate "
            "in daily life, which is the point of the entire explanation."
        )
        self.blocks=[block(1,self.source_text,0,5),
                     block(2,self.source_text,5,10)]
        self.wavs=[pcm(self.path/f"original{i}.wav",4.4)
                   for i in (1,2)]
        self.results=[{"block_index":b.index,"text":b.text,
                       "text_sha256":b.text_sha256} for b in self.blocks]

    def tearDown(self):
        self.tmp.cleanup()

    def fake_renderer(self, new_sec=1.8):
        async def cb(*,lang,blocks,output_dir,checkpoint_store=None):
            return (
                [{"block_index":b.index,"text":b.text,
                  "text_sha256":b.text_sha256} for b in blocks],
                [pcm(output_dir/f"candidate-{b.index}.wav",new_sec)
                 for b in blocks]
            )
        return cb

    def run_fit(self, source=6, audit=True, new_sec=1.8, blocks=None, client=None):
        reviewer=client or MockGemini(approve=audit)
        outputs=prepare_smart_narration(
            language="en",blocks=blocks or self.blocks,
            block_results=self.results,
            wav_parts=self.wavs,
            source_duration=source,output_dir=self.path/"output",
            client_factory=lambda:reviewer,
            render_callback=self.fake_renderer(new_sec),
        )
        return outputs,reviewer

    def test_three_round_limit_and_natural_pauses(self):
        self.assertEqual(MAX_REWRITE_ROUNDS,3)
        self.assertEqual(semantic_pauses(self.blocks),[0.18])
        gap_blocks=[block(1,"A spoken sentence.",0,3),
                    block(2,"Second story",7,9),
                    block(3,"Buddhist teaching",9,11)]
        self.assertEqual(semantic_pauses(gap_blocks),[0.55,0.12])
        path=self.path/"list-pauses.wav"
        report=assemble_preview(self.wavs,path,pause_seconds=[0.35])
        self.assertAlmostEqual(report["duration"],9.15,places=2)
        with self.assertRaises(ValueError):
            assemble_preview(self.wavs,path,pause_seconds=[0.2,0.1])

    def test_no_minimum_duration_and_no_unnecessary_edits(self):
        out,client=self.run_fit(source=30)
        self.assertFalse(client.calls)
        self.assertEqual(out["report"]["modified_blocks"],0)
        self.assertTrue(out["report"]["within_source_limit_with_margin"])
        self.assertLess(out["preview"]["duration"],30)
        self.assertTrue(out["report"]["source_duration_seconds"]==30)
        self.assertEqual(out["report"]["semantic_pauses_seconds"],[0.18])
        self.assertEqual(out["blocks"][0].text,self.source_text)

    def test_approved_rewrite_shortens_audio_and_preserves_source(self):
        out,client=self.run_fit(source=6)
        self.assertEqual(client.calls,["rewrite","audit"])
        self.assertTrue(out["report"]["within_source_limit_with_margin"])
        self.assertEqual(out["report"]["modified_blocks"],2)
        self.assertLess(out["preview"]["duration"],6)
        self.assertTrue(out["report"]["passes"][0]["accepted"])
        self.assertEqual(self.blocks[0].text,self.source_text)
        self.assertAlmostEqual(_wav_duration(self.wavs[0]),4.4)
        self.assertEqual(out["blocks"][0].index,1)
        self.assertEqual(out["blocks"][0].segment_ids,[1])
        self.assertNotEqual(out["blocks"][0].text_sha256,self.blocks[0].text_sha256)
        script=json.loads(out["script_path"].read_text(encoding="utf-8"))
        self.assertTrue(script["source_translation_unchanged"])
        self.assertTrue(script["blocks"][0]["rewritten"])
        self.assertIn("anchors",out["report"])

    def test_auditor_rejection_preserves_original_and_prevents_release(self):
        out,client=self.run_fit(source=6,audit=False)
        self.assertEqual(client.calls,["rewrite","audit"])
        self.assertFalse(out["report"]["within_source_limit_with_margin"])
        self.assertEqual(out["report"]["modified_blocks"],0)
        self.assertEqual(out["blocks"],self.blocks)
        self.assertEqual(out["report"]["needs_review_reason"],
                         "independent_semantic_review_rejected_all")

    def test_no_gemini_key_keeps_review_only(self):
        def unavailable():
            raise RuntimeError("key unavailable")
        out=prepare_smart_narration(
            language="en",blocks=self.blocks,block_results=self.results,
            wav_parts=self.wavs,source_duration=6,
            output_dir=self.path/"output",
            client_factory=unavailable,
        )
        self.assertFalse(out["report"]["within_source_limit_with_margin"])
        self.assertEqual(out["report"]["modified_blocks"],0)
        self.assertEqual(out["report"]["needs_review_reason"],
                         "editor_unavailable:RuntimeError")

    def test_numeric_and_punctuation_guard(self):
        self.assertEqual(_numbers("年2026，１２５元；3.5倍"),["2026","125","3.5"])
        self.assertFalse(safe_candidate("He donated 125 dollars.","He donated 12 dollars.")[0])
        self.assertFalse(safe_candidate("The teaching is kind.","。")[0])
        self.assertFalse(safe_candidate("A short sentence.","A short sentence.")[0])
        self.assertTrue(safe_candidate(self.source_text,
                        "He explains the same family story and its lesson.")[0])

    def test_unproductive_audio_prevents_bogus_completion(self):
        out,client=self.run_fit(source=6,new_sec=5.0)
        self.assertFalse(out["report"]["within_source_limit_with_margin"])
        self.assertEqual(out["report"]["modified_blocks"],0)
        self.assertEqual(out["report"]["needs_review_reason"],
                         "revisions_did_not_reduce_audio")

if __name__=="__main__":
    unittest.main()
