"""Verify cookies are decoded only on the ephemeral GitHub CC worker."""
import base64
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

FILE=Path(__file__).resolve().parents[1]/"youtube_cc_worker.py"
spec=importlib.util.spec_from_file_location("soulkey_cc_cookie_test",FILE)
worker=importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)

SAMPLE="# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\ttest_session\tFAKE_VALUE_DO_NOT_USE\n"

class CookieTest(unittest.TestCase):
    def test_valid_base64_private_ephemeral_file(self):
        encoded=base64.b64encode(SAMPLE.encode()).decode()
        with tempfile.TemporaryDirectory() as tmp:
            path=worker.temporary_cookiefile(encoded,tmp)
            self.assertTrue(Path(path).is_file())
            self.assertEqual(Path(path).stat().st_mode&0o777,0o600)
            self.assertEqual(Path(path).read_text(),SAMPLE)
        self.assertFalse(Path(path).exists())

    def test_raw_netscape_cookie_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(Path(worker.temporary_cookiefile(SAMPLE,tmp)).exists())

    def test_reject_invalid_and_unrelated_cookie(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError,"invalid base64"):
                worker.temporary_cookiefile("not-cookie-and-not-base64",tmp)
            wrong=base64.b64encode(b"# Netscape HTTP Cookie File\n.other.com\tTRUE\t/\tTRUE\t0\ttest\tno\n").decode()
            with self.assertRaisesRegex(RuntimeError,"no recognizable YouTube"):
                worker.temporary_cookiefile(wrong,tmp)
            self.assertFalse((Path(tmp)/"youtube_cookies.txt").exists())

    def test_empty_key_does_not_write_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(worker.temporary_cookiefile("",tmp))
            self.assertFalse((Path(tmp)/"youtube_cookies.txt").exists())

if __name__=="__main__":
    unittest.main()
