"""Regression: long-running CPU translations must not reuse expired GitHub OIDC."""
import importlib.util
import io
import json
import pathlib
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

MODULE=pathlib.Path(__file__).resolve().parents[1]/"translation_worker.py"
spec=importlib.util.spec_from_file_location("soulkey_translation_worker",MODULE)
worker=importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class FakeResponse:
    def __enter__(self):
        return self
    def __exit__(self,*_):
        pass
    def read(self):
        return b'{"ok":true}'


class FreshIdentityTests(unittest.TestCase):
    def test_new_token_per_request_even_with_stale_initial_token(self):
        authorizations=[]
        def urlopen(req,timeout):
            authorizations.append(req.get_header("Authorization"))
            return FakeResponse()
        with patch.object(worker,"github_oidc",side_effect=["new-jwt-1","new-jwt-2"]),\
             patch.object(worker.urllib.request,"urlopen",side_effect=urlopen):
            self.assertTrue(worker.bridge_request("expired","worker_job_part",{"job_id":"one"})["ok"])
            self.assertTrue(worker.bridge_request("expired","worker_job_report",{"job_id":"one"})["ok"])
        self.assertEqual(authorizations,["Bearer new-jwt-1","Bearer new-jwt-2"])

    def test_retry_401_with_another_fresh_jwt(self):
        authorizations=[]
        def urlopen(req,timeout):
            authorizations.append(req.get_header("Authorization"))
            if len(authorizations)==1:
                raise HTTPError(worker.BASE,401,"Expired",{},io.BytesIO(b""))
            return FakeResponse()
        with patch.object(worker,"github_oidc",side_effect=["new-jwt-1","new-jwt-2"]),\
             patch.object(worker.urllib.request,"urlopen",side_effect=urlopen):
            self.assertTrue(worker.bridge_request("expired","worker_job_part",{"job_id":"one"})["ok"])
        self.assertEqual(authorizations,["Bearer new-jwt-1","Bearer new-jwt-2"])

    def test_non_authorization_error_does_not_retry(self):
        with patch.object(worker,"github_oidc",return_value="fresh"),\
             patch.object(worker.urllib.request,"urlopen",side_effect=HTTPError(worker.BASE,409,"Conflict",{},None)) as fetch:
            with self.assertRaises(HTTPError):
                worker.bridge_request("expired","worker_job_part",{"job_id":"one"})
        self.assertEqual(fetch.call_count,1)


if __name__=="__main__":
    unittest.main()
