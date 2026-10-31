"""Regression tests for source provenance and CPU P259 translation safety."""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from source_duration import video_id,checked_duration,trusted_video_duration


class SourceDurationTests(unittest.TestCase):
    def test_youtube_id_requires_exact_supported_url(self):
        self.assertEqual(video_id("https://youtu.be/w7rzYft4MeE"),"w7rzYft4MeE")
        self.assertEqual(video_id("https://www.youtube.com/watch?v=w7rzYft4MeE"),
                         "w7rzYft4MeE")
        self.assertEqual(video_id("https://evil.com/watch?v=w7rzYft4MeE"),"")

    def test_legacy_chinese_metadata_validated_against_exact_id(self):
        payload={"id":"w7rzYft4MeE","duration":1854,
                 "source":{"id":"w7rzYft4MeE","duration":1854}}
        self.assertEqual(checked_duration(payload,"w7rzYft4MeE"),1854)
        self.assertIsNone(checked_duration(payload,"otherVideoX"))
        self.assertIsNone(checked_duration({"id":"w7rzYft4MeE",
                  "duration":float("nan")},"w7rzYft4MeE"))
        self.assertIsNone(checked_duration({"id":"w7rzYft4MeE",
                  "duration":0},"w7rzYft4MeE"))

    def test_legacy_file_recovered_without_network(self):
        with tempfile.TemporaryDirectory() as temp:
            def download(_drive,_file_id,path):
                Path(path).write_text(json.dumps({"id":"w7rzYft4MeE","duration":1872}))
            fake=types.ModuleType("google_io")
            fake.list_child_files=lambda _d,_f:[
                {"id":"source-legacy","name":"第259期_第4堂_來源資訊.json"}]
            fake.download_drive_file=download
            fake.find_file=lambda *_:None
            fake.upload_or_replace_file=lambda *a,**k:self.fail("no upload needed")
            with patch.dict(sys.modules,{"google_io":fake}):
                duration,basis=trusted_video_duration(None,"folder",temp,
                    "https://youtu.be/w7rzYft4MeE")
            self.assertEqual(duration,1872)
            self.assertEqual(basis,"legacy_source_info.duration")

    def test_conflicting_canonical_metadata_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            def download(_drive,_file_id,path):
                Path(path).write_text(json.dumps({"id":"anotherVideo","duration":2000}))
            fake=types.ModuleType("google_io")
            fake.list_child_files=lambda _d,_f:[{"id":"bad","name":"source_info.json"}]
            fake.download_drive_file=download
            fake.find_file=lambda *_:self.fail("should not call upload lookup")
            fake.upload_or_replace_file=lambda *a,**k:self.fail("no overwrite allowed")
            with patch.dict(sys.modules,{"google_io":fake}):
                result=trusted_video_duration(None,"folder",temp,
                    "https://youtu.be/w7rzYft4MeE")
            self.assertEqual(result,(None,"source_info_conflict"))

    def test_missing_metadata_only_promoted_after_verified_upload_readback(self):
        with tempfile.TemporaryDirectory() as temp:
            published={}
            def download(_drive,file_id,path):
                Path(path).write_bytes(published["body"])
            def upload(_drive,_folder,path,drive_name=None):
                self.assertEqual(drive_name,"source_info.json")
                published["body"]=Path(path).read_bytes()
            fake=types.ModuleType("google_io")
            fake.list_child_files=lambda _d,_f:[]
            fake.download_drive_file=download
            fake.find_file=lambda *_:(
                {"id":"verified","name":"source_info.json"} if published else None)
            fake.upload_or_replace_file=upload
            yt=types.ModuleType("yt_dlp")
            class YDL:
                def __init__(self,opts):self.opts=opts
                def __enter__(self):return self
                def __exit__(self,*a):return False
                def extract_info(self,url,download=False):
                    self_outer.assertFalse(download)
                    return {"id":"w7rzYft4MeE","duration":1888,
                            "title":"Source lesson"}
            self_outer=self
            yt.YoutubeDL=YDL
            with patch.dict(sys.modules,{"google_io":fake,"yt_dlp":yt}):
                value=trusted_video_duration(None,"folder",temp,
                    "https://youtu.be/w7rzYft4MeE")
            self.assertEqual(value,(1888,"youtube_verified_source_info.duration"))
            self.assertEqual(json.loads(published["body"])["id"],"w7rzYft4MeE")


if __name__ == "__main__":
    unittest.main()
