"""P259 Cloud Run delivery token never needs a stored Google refresh secret."""
import os
import sys
import pathlib
import json
import unittest
from unittest.mock import patch

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from google_io import CloudRunOIDCCredentials

class MockResponse:
    def __init__(self,payload):
        self.payload=payload
    def __enter__(self):
        return self
    def __exit__(self,*args):
        return False
    def read(self):
        return json.dumps(self.payload).encode("utf-8")

class Tests(unittest.TestCase):
    def test_short_lived_repo_bound_refresh_without_any_google_secrets(self):
        seen=[]
        def fake_urlopen(req,timeout):
            seen.append(req)
            if len(seen)==1:
                self.assertIn("audience=soulkey-bridge-translation-worker-v1",req.full_url)
                self.assertEqual(req.get_header("Authorization"),"Bearer github-actions-request")
                return MockResponse({"value":"short-lived-github-oidc"})
            self.assertEqual(req.full_url,"https://bridge.example.test")
            self.assertEqual(req.get_method(),"POST")
            self.assertIn(b"worker_drive_runtime",req.data)
            self.assertEqual(req.get_header("Authorization"),"Bearer short-lived-github-oidc")
            return MockResponse({"ok":True,"google_access_token":"temporary-google-token","expires_in":2700})
        with patch.dict(os.environ,{
            "ACTIONS_ID_TOKEN_REQUEST_URL":"https://github.example.test/oidc?x=1",
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN":"github-actions-request"
        },clear=True),patch("google_io.urllib.request.urlopen",side_effect=fake_urlopen):
            creds=CloudRunOIDCCredentials("https://bridge.example.test")
            creds.refresh(None)
            self.assertEqual(creds.token,"temporary-google-token")
            self.assertFalse(creds.expired)
            self.assertEqual(len(seen),2)

    def test_reject_insecure_bridge(self):
        with self.assertRaisesRegex(RuntimeError,"HTTPS"):
            CloudRunOIDCCredentials("http://invalid.test")

    def test_missing_oidc_fails_without_google_secret_fallback(self):
        with patch.dict(os.environ,{},clear=True):
            c=CloudRunOIDCCredentials("https://bridge.example.test")
            with self.assertRaisesRegex(RuntimeError,"GitHub Actions OIDC"):
                c.refresh(None)

    def test_missing_drive_permission_refuses_token(self):
        replies=iter([{"value":"id"},{"ok":False,
                              "error":"p259_drive_editor_permission_missing"}])
        def fake_urlopen(req,timeout):
            return MockResponse(next(replies))
        with patch.dict(os.environ,{
            "ACTIONS_ID_TOKEN_REQUEST_URL":"https://github.example.test/oidc",
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN":"auth"
        },clear=True),patch("google_io.urllib.request.urlopen",side_effect=fake_urlopen):
            c=CloudRunOIDCCredentials("https://bridge.example.test")
            with self.assertRaisesRegex(RuntimeError,"permission"):
                c.refresh(None)
            self.assertFalse(c.token)

if __name__=="__main__":
    unittest.main(verbosity=2)
