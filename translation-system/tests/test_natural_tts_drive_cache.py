"""Offline, synthetic Google Drive checkpoint tests: never access Drive."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from natural_tts_drive_cache import DriveTTSBlockCache
from natural_tts_planner import SpeechBlock
import natural_tts_drive_cache as cache_module


def blocks(n=8):
    return [
        SpeechBlock(index=i, segment_ids=[i], source_start=i * 2.0,
                    source_end=i * 2.0 + 1, text=f"Synthetic {i}",
                    text_sha256=hashlib.sha256(f"Synthetic {i}".encode()).hexdigest())
        for i in range(1, n + 1)
    ]


class DriveCacheTests(unittest.TestCase):
    def test_restore_exact_revision_and_voice_only(self):
        disk = {}
        def upload(drive, folder, path, drive_name=None):
            disk[drive_name] = Path(path).read_bytes()
            return {"id": drive_name}
        def find(drive, folder, name):
            return {"id": name} if name in disk else None
        def download(drive, identifier, path):
            Path(path).write_bytes(disk[identifier])

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "original"
            parts = source / "blocks"
            parts.mkdir(parents=True)
            selected = blocks()
            metadata = {}
            for block in selected:
                (parts / f"{block.index:04d}.mp3").write_bytes(
                    b"x" * (2048 + block.index))
                metadata[block.index] = {
                    "block_index": block.index,
                    "text_sha256": block.text_sha256,
                    "duration": 1.3,
                }
            with patch.object(cache_module,"upload_or_replace_file",side_effect=upload), \
                 patch.object(cache_module,"find_file",side_effect=find), \
                 patch.object(cache_module,"download_drive_file",side_effect=download):
                cache = DriveTTSBlockCache(
                    object(), "audio-folder", "en", "source-revision-1",
                    selected, root / "scratch",
                )
                cache.save_group(0, metadata, source)
                self.assertEqual(len(disk), 1)
                restored = root / "restored"
                self.assertEqual(cache.restore(restored), 8)
                self.assertEqual(cache.restored_groups, {0})
                for block in selected:
                    self.assertEqual(
                        (restored / "blocks" / f"{block.index:04d}.mp3").read_bytes(),
                        b"x" * (2048 + block.index),
                    )
                changed = DriveTTSBlockCache(
                    object(), "audio-folder", "en", "source-revision-2",
                    selected, root / "scratch_changed",
                )
                self.assertEqual(changed.restore(root / "changed"), 0)
                self.assertFalse((root / "changed" / "en.tts_checkpoint.json").exists())
                # A broken archive never passes SHA verification.
                name = cache.group_name(0)
                disk[name] = disk[name][:45]
                corrupted = DriveTTSBlockCache(
                    object(), "audio-folder", "en", "source-revision-1",
                    selected, root / "scratch_corrupted",
                )
                self.assertEqual(corrupted.restore(root / "corrupted"), 0)

    def test_incomplete_batch_is_not_uploaded(self):
        with tempfile.TemporaryDirectory() as temp:
            c = DriveTTSBlockCache(
                object(), "unused", "en", "source-1", blocks(),
                Path(temp)/"scratch",
            )
            with self.assertRaises(ValueError):
                c.save_group(0, {}, Path(temp))


if __name__ == "__main__":
    unittest.main()
