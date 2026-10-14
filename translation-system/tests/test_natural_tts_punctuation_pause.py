"""A punctuation-only translation segment must never fail an entire lesson."""
import asyncio
import hashlib
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from natural_tts_planner import SpeechBlock
from natural_tts_edge import synthesize_block, _ffprobe_duration

class TestPunctuationOnlyTts(unittest.TestCase):
    def test_period_from_p257_l01_three_languages(self):
        for code,block_id,voice in (
            ("id",6,"id-ID-ArdiNeural"),
            ("ta",7,"ta-IN-ValluvarNeural"),
            ("lo",7,"lo-LA-ChanthavongNeural"),
        ):
            with self.subTest(language=code), tempfile.TemporaryDirectory() as temp:
                text="."
                b=SpeechBlock(index=block_id,segment_ids=[26],
                    source_start=115.88,source_end=128.46,text=text,
                    text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest())
                output=Path(temp)/"0006.part.mp3"
                bounds=Path(temp)/"0006.boundaries.jsonl"
                result=asyncio.run(synthesize_block(
                    b,voice=voice,rate="-3%",pitch="-1Hz",
                    output_mp3=output,boundary_path=bounds
                ))
                self.assertEqual(result["audio_kind"],"punctuation_pause")
                self.assertEqual(result["attempt"],0)
                self.assertEqual(result["segment_ids"],[26])
                self.assertEqual(result["text_sha256"],b.text_sha256)
                self.assertTrue(output.is_file())
                self.assertGreater(output.stat().st_size,100)
                self.assertTrue(bounds.is_file())
                self.assertEqual(bounds.read_text(encoding="utf-8"),"")
                self.assertGreater(_ffprobe_duration(output),0.15)
                self.assertLess(_ffprobe_duration(output),0.35)
    def test_all_nonspoken_punctuation(self):
        with tempfile.TemporaryDirectory() as d:
            b=SpeechBlock(index=3,segment_ids=[5],source_start=0,source_end=1,
                text="？！",text_sha256=hashlib.sha256("？！".encode()).hexdigest())
            value=asyncio.run(synthesize_block(
                b,voice="zh-CN-YunxiNeural",rate="+0%",pitch="+0Hz",
                output_mp3=Path(d)/"a.mp3",boundary_path=Path(d)/"b.jsonl"
            ))
            self.assertEqual(value["audio_kind"],"punctuation_pause")

if __name__=="__main__":
    unittest.main()
