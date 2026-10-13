"""Drive-backed, bounded Edge TTS block cache (not a formal deliverable).

Each archive covers at most eight source-verified MP3 blocks. WAV is rebuilt
locally, so the Drive checkpoint uses bandwidth proportional to new work.
Never imports or overwrites the officially delivered lesson MP3/WAV.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import zipfile

from google_io import download_drive_file, find_file, upload_or_replace_file
from natural_tts_config import NATURAL_TTS_PROFILES, NATURAL_TTS_PROFILE_REVISION

GROUP_SIZE = 8
MAX_BLOCK_BYTES = 12 * 1024 * 1024


class DriveTTSBlockCache:
    def __init__(self, drive, audio_folder, lang, source_sha256, blocks, scratch):
        self.drive = drive
        self.folder = audio_folder
        self.lang = lang
        self.source = str(source_sha256 or "")
        self.by_index = {int(b.index): b for b in blocks}
        self.scratch = Path(scratch)
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.profile = NATURAL_TTS_PROFILES[lang]
        self.context = {
            "lang": lang,
            "source_sha256": self.source,
            "profile_revision": NATURAL_TTS_PROFILE_REVISION,
            "voice": self.profile["voice"],
            "rate": self.profile["rate"],
            "pitch": self.profile["pitch"],
        }

    def group_members(self, group):
        return sorted(i for i in self.by_index if (i - 1) // GROUP_SIZE == group)

    def group_name(self, group):
        return f"_soulkey_tts_cache_{self.lang}_{group:04d}.zip"

    def restore(self, output_dir):
        """Restore only verified archives matching the exact Final & voice."""
        output_dir = Path(output_dir)
        recovered = {}
        for group in sorted({(i - 1) // GROUP_SIZE for i in self.by_index}):
            item = find_file(self.drive, self.folder, self.group_name(group))
            if not item:
                continue
            local = self.scratch / self.group_name(group)
            try:
                download_drive_file(self.drive, item["id"], local)
                with zipfile.ZipFile(local) as archive:
                    manifest = json.loads(archive.read("manifest.json"))
                    if any(manifest.get(k) != v for k, v in self.context.items()):
                        continue
                    if int(manifest.get("group", -1)) != group:
                        continue
                    entries = list(manifest.get("blocks") or [])
                    expected = self.group_members(group)
                    if sorted(int(x["block_index"]) for x in entries) != expected:
                        continue
                    blobs = {}
                    for row in entries:
                        index = int(row["block_index"])
                        block = self.by_index[index]
                        if row.get("text_sha256") != block.text_sha256:
                            raise ValueError("Final text revision does not match")
                        name = f"blocks/{index:04d}.mp3"
                        if int(row.get("size") or 0) > MAX_BLOCK_BYTES:
                            raise ValueError("oversized checkpoint block")
                        info = archive.getinfo(name)
                        if info.file_size != int(row.get("size") or 0):
                            raise ValueError("checkpoint size mismatch")
                        if not (1024 < info.file_size <= MAX_BLOCK_BYTES):
                            raise ValueError("invalid checkpoint size")
                        blob = archive.read(name)
                        if hashlib.sha256(blob).hexdigest() != row.get("sha256"):
                            raise ValueError("checkpoint hash mismatch")
                        blobs[index] = blob
                    # Only write after verifying the entire batch.
                    output_block_dir = output_dir / "blocks"
                    output_block_dir.mkdir(parents=True, exist_ok=True)
                    for index, blob in blobs.items():
                        dest = output_block_dir / f"{index:04d}.mp3"
                        tmp = dest.with_suffix(".restore.tmp")
                        tmp.write_bytes(blob)
                        os.replace(tmp, dest)
                    recovered.update({
                        int(row["block_index"]): {
                            "block_index": int(row["block_index"]),
                            "text_sha256": row["text_sha256"],
                            "duration": float(row["duration"]),
                        } for row in entries
                    })
            except (OSError, ValueError, KeyError, TypeError, RuntimeError,
                    zipfile.BadZipFile) as exc:
                print(f"[TTS-CACHE] Ignore invalid {self.lang} group {group}: {type(exc).__name__}", flush=True)
            finally:
                local.unlink(missing_ok=True)

        if recovered:
            payload = {
                "language": self.lang,
                "profile_revision": NATURAL_TTS_PROFILE_REVISION,
                "voice": self.profile["voice"],
                "rate": self.profile["rate"],
                "pitch": self.profile["pitch"],
                "blocks": [recovered[k] for k in sorted(recovered)],
            }
            checkpoint = output_dir / f"{self.lang}.tts_checkpoint.json"
            tmp = checkpoint.with_suffix(".restore.json")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, checkpoint)
        print(f"[TTS-CACHE] {self.lang} restored {len(recovered)} matching blocks", flush=True)
        return len(recovered)

    def save_group(self, group, metadata, output_dir):
        """Upload complete eight-block groups; no official audio is touched."""
        members = self.group_members(group)
        if not members or any(i not in metadata for i in members):
            raise ValueError("cannot store incomplete cache group")
        output_dir = Path(output_dir)
        archive_path = self.scratch / self.group_name(group)
        entries = []
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as bundle:
            for index in members:
                block = self.by_index[index]
                info = metadata[index]
                if info.get("text_sha256") != block.text_sha256:
                    raise ValueError("checkpoint text revision changed")
                path = output_dir / "blocks" / f"{index:04d}.mp3"
                size = path.stat().st_size
                if not (1024 < size <= MAX_BLOCK_BYTES):
                    raise ValueError("bad checkpoint audio size")
                blob = path.read_bytes()
                entries.append({
                    "block_index": index,
                    "text_sha256": block.text_sha256,
                    "duration": float(info["duration"]),
                    "size": len(blob),
                    "sha256": hashlib.sha256(blob).hexdigest(),
                })
                bundle.writestr(f"blocks/{index:04d}.mp3", blob)
            bundle.writestr("manifest.json", json.dumps({
                **self.context, "group": group, "blocks": entries
            }, ensure_ascii=False))
        try:
            upload_or_replace_file(
                self.drive, self.folder, archive_path,
                drive_name=self.group_name(group),
            )
            print(f"[TTS-CACHE] Saved {self.lang} group {group} ({len(entries)} blocks)", flush=True)
        finally:
            archive_path.unlink(missing_ok=True)
