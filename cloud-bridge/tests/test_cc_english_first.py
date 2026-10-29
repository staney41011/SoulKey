"""Offline tests: English caption first, source match, and no 429 retry storms."""
import importlib.util
import io
import pathlib
import sys
import types
import unittest
from unittest.mock import patch

ROOT=pathlib.Path(__file__).resolve().parents[1]
VIDEO="w7rzYft4MeE"

def read_module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/(name+".py"))
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class FakeDownloader:
    requests=[]
    def __init__(self,opts):self.opts=opts
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def extract_info(self,url,download=False):
        assert url.endswith(VIDEO)
        tracks={l:[{"url":"https://example.test/"+l,"ext":"vtt"}]
            for l in ("en","es","vi")}
        return {"id":VIDEO,"automatic_captions":tracks}
    def urlopen(self,url):
        self.requests.append(url)
        if url.endswith("/es"):
            raise RuntimeError("HTTP Error 429 Too Many Requests")
        if url.endswith("/vi"):
            raise AssertionError("Must not request later languages after HTTP 429")
        return io.BytesIO(b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello world.\n")

class FirstLanguageTest(unittest.TestCase):
    def test_checkpoint_before_subsequent_rate_limit(self):
        for name in ("youtube_cc_worker","youtube_cc_kaggle"):
            with self.subTest(name=name):
                mod=read_module(name)
                FakeDownloader.requests=[]
                events=[]
                with patch.dict(sys.modules,{"yt_dlp":types.SimpleNamespace(YoutubeDL=FakeDownloader)}):
                    data,missing=mod.fetch_youtube(VIDEO,["vi","es","en"],
                        on_caption=lambda lang,text,source:events.append((lang,text,source)))
                self.assertEqual([e[0] for e in events],["en"])
                self.assertEqual(list(data),["en"])
                self.assertIn("Hello world.",data["en"][0])
                self.assertIn("es",missing)
                self.assertIn("vi",missing)
                self.assertEqual(FakeDownloader.requests,[
                    "https://example.test/en","https://example.test/es"])

    def test_source_identity_guard(self):
        mod=read_module("youtube_cc_worker")
        class Wrong(FakeDownloader):
            def extract_info(self,url,download=False):
                return {"id":"Different11","automatic_captions":{}}
        with patch.dict(sys.modules,{"yt_dlp":types.SimpleNamespace(YoutubeDL=Wrong)}):
            with self.assertRaisesRegex(RuntimeError,"different video"):
                mod.fetch_youtube(VIDEO,["en"])
if __name__=="__main__":unittest.main()
