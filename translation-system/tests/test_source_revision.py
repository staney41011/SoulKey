"""Regression tests: a replaced YouTube link must not reuse stale ASR."""
import importlib
import json
import sys
import tempfile
import types
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
DEPS = PROJECT / ".test-deps"
if DEPS.exists():
    sys.path.insert(0, str(DEPS))
sys.path.insert(0, str(ROOT))

# No Google authentication is required for unit tests.
fake_google = types.ModuleType("google_io")
fake_google.download_drive_file = lambda *a, **k: None
fake_google.find_file = lambda *a, **k: None
fake_google.upload_or_replace_file = lambda *a, **k: None
sys.modules.setdefault("google_io", fake_google)
source_revision = importlib.import_module("source_revision")
import numpy as np


def write_wav(path, seconds=70, change=False, gain=1.0):
    rate = 16000
    time = np.arange(seconds * rate, dtype=np.float32) / rate
    envelope = (0.1 + 0.55 * np.abs(np.sin(time * 1.139))) * (
        0.65 + 0.35 * np.sin(time * 0.173)**2
    )
    pcm = envelope * np.sin(2 * np.pi * (190 + 12 * np.sin(time * .037)) * time)
    if change:
        pcm[rate*18:rate*31] = np.sin(
            2 * np.pi * 430 * time[rate*18:rate*31]
        ) * envelope[rate*18:rate*31]
    data = (pcm * gain * 18000).clip(-32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as dst:
        dst.setnchannels(1)
        dst.setsampwidth(2)
        dst.setframerate(rate)
        dst.writeframes(data.tobytes())


class SourceRevisionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name)
        self.original = path / "old.wav"
        self.duplicate = path / "new.wav"
        self.different = path / "different.wav"
        write_wav(self.original)
        write_wav(self.duplicate, gain=.98)
        write_wav(self.different, change=True)
        self.sig_original = source_revision.audio_signature(self.original)

    def verify(self, prior, new_path, fail_old=False):
        downloaded = []
        uploads = []
        def get_audio(url, dest):
            downloaded.append(url)
            if fail_old and "old123" in url:
                raise RuntimeError("old video deleted")
            return (self.original if "old123" in url else new_path), {
                "webpage_url": "https://youtu.be/new456",
            }

        with (patch.object(source_revision, "_read_json", return_value=prior),
              patch.object(source_revision, "upload_or_replace_file",
                           side_effect=lambda *a, **k: uploads.append((a,k)))):
            result = source_revision.verify_existing_asr(
                drive=None,
                folders={"source": "folder"},
                current_url="https://youtu.be/new456",
                workdir=Path(self.tmp.name) / "workdir",
                download_audio_fn=get_audio,
            )
        return result, downloaded, uploads

    def test_same_id_different_url_styles_never_downloads(self):
        prior = {"youtube_url": "https://youtube.com/watch?v=new456&feature=share"}
        result, fetched, saved = self.verify(prior, self.different)
        self.assertEqual(result, (True, "same_youtube_video_id"))
        self.assertEqual(fetched, [])
        self.assertEqual(saved, [])

    def test_reuploaded_same_audio_skips_asr(self):
        result, fetched, saved = self.verify(
            {"youtube_url": "https://youtu.be/old123"},
            self.duplicate,
        )
        self.assertEqual(result, (True, "audio_and_timeline_match"))
        self.assertEqual(len(fetched), 2)
        self.assertEqual(len(saved), 1)

    def test_prior_signature_supports_deleted_old_video(self):
        result, fetched, saved = self.verify(
            {"youtube_url": "https://youtu.be/old123",
             "audio_signature": self.sig_original},
            self.duplicate, fail_old=True,
        )
        self.assertEqual(result, (True, "audio_and_timeline_match"))
        self.assertEqual(len(fetched), 1)
        self.assertEqual(len(saved), 1)

    def test_different_audio_cannot_reuse_asr(self):
        result, fetched, saved = self.verify(
            {"youtube_url": "https://youtu.be/old123"},
            self.different,
        )
        self.assertEqual(result, (False, "audio_or_timeline_changed"))
        self.assertEqual(saved, [])

    def test_unavailable_old_video_fails_closed(self):
        result, fetched, saved = self.verify(
            {"youtube_url": "https://youtu.be/old123"},
            self.duplicate, fail_old=True,
        )
        self.assertEqual(result, (False, "original_audio_unavailable"))
        self.assertEqual(saved, [])

    def test_signature_time_shift_rejected(self):
        with tempfile.TemporaryDirectory() as other:
            target = Path(other) / "shifted.wav"
            with wave.open(str(self.original), "rb") as src:
                signal = np.frombuffer(src.readframes(src.getnframes()), dtype="<i2")
            samples = np.concatenate([np.zeros(3200, dtype="<i2"), signal[:-3200]])
            with wave.open(str(target), "wb") as dst:
                dst.setnchannels(1)
                dst.setsampwidth(2)
                dst.setframerate(16000)
                dst.writeframes(samples.tobytes())
            self.assertFalse(source_revision.equivalent_audio(
                self.sig_original, source_revision.audio_signature(target)
            ))


if __name__ == "__main__":
    unittest.main()
