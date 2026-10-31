"""Safely lengthen short complete TTS narrations without fake ending silence."""
from __future__ import annotations
import math
import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
from natural_tts_assemble import assemble_continuous_with_limit

def make_wav(path,seconds,sample_rate=8000):
    frames=round(seconds*sample_rate)
    with wave.open(str(path),"wb") as fp:
        fp.setnchannels(1)
        fp.setsampwidth(2)
        fp.setframerate(sample_rate)
        samples=bytearray()
        # low amplitude tone so ffmpeg atempo receives real signal.
        for n in range(frames):
            sample=int(1200*math.sin(2*math.pi*220*n/sample_rate))
            samples.extend(sample.to_bytes(2,"little",signed=True))
        fp.writeframes(samples)

class DurationFit(unittest.TestCase):
    def test_27min_equivalent_moves_close_to_video(self):
        # Scaled test: 2.7 sec models 27 min against a 3.049 min source.
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/"natural.wav";out=Path(d)/"output.wav"
            make_wav(source,2.7)
            report=assemble_continuous_with_limit(source,out,source_duration=3.049)
            self.assertFalse(report["needs_review"])
            self.assertTrue(2.90<=report["final_duration"]<=3.05,report)
            self.assertTrue(1.0<report["applied_slowdown"]<=1.18)
    def test_23min_equivalent_slowdown_is_capped(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/"natural.wav";out=Path(d)/"output.wav"
            make_wav(source,2.3)
            report=assemble_continuous_with_limit(source,out,source_duration=3.049)
            self.assertTrue(report["needs_review"])
            self.assertTrue(report["under_source_minimum"])
            self.assertTrue(2.6<=report["final_duration"]<=2.75,report)
            self.assertLessEqual(report["applied_slowdown"],1.180001)
            self.assertGreater(report["duration_gap_seconds"],.25)
    def test_short_l04_english_must_not_pass_false_done(self):
        # Real 2026-10-31 L04 English report: 1468.9 s / 1829.0 s.
        # Scaled durations keep the regression fast without mocking FFmpeg.
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/"natural.wav";out=Path(d)/"output.wav"
            make_wav(source,1.244856)
            report=assemble_continuous_with_limit(
                source,out,source_duration=1.829
            )
            self.assertTrue(report["needs_review"],report)
            self.assertTrue(report["under_source_minimum"],report)
            self.assertLess(report["final_duration"],1.829*0.96)
    def test_near_full_source_is_not_slowed(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/"natural.wav";out=Path(d)/"output.wav"
            make_wav(source,3.01)
            report=assemble_continuous_with_limit(source,out,source_duration=3.049)
            self.assertEqual(report["applied_slowdown"],1)
            self.assertAlmostEqual(report["final_duration"],3.01,delta=.02)
    def test_overlong_still_needs_review(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/"natural.wav";out=Path(d)/"output.wav"
            make_wav(source,3.6)
            report=assemble_continuous_with_limit(source,out,source_duration=3.049)
            self.assertTrue(report["needs_review"])
            self.assertAlmostEqual(report["final_duration"],3.6,delta=.02)

if __name__=="__main__":
    unittest.main()
