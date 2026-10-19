"""Drive 502 resumable retry regressions without needing Google API credentials."""
import ast
import hashlib
import mimetypes
import ssl
from http.client import RemoteDisconnected
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]


def load_functions(path, names, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding="utf8"))
    selected = []
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names:
            selected.append(n)
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


class UploadError(Exception):
    def __init__(self, status):
        self.resp = types.SimpleNamespace(status=status)
        super().__init__(f"<HttpError {status}: Bad Gateway <!DOCTYPE html> untrusted upstream response")


class FakeReq:
    def __init__(self, outcome, calls):
        self.outcome, self.calls = outcome, calls

    def execute(self, num_retries=0):
        self.calls.append(num_retries)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class FakeFiles:
    def __init__(self, outcomes, metadata=None):
        self.outcomes=list(outcomes)
        self.create_calls = 0
        self.update_calls = 0
        self.get_calls = 0
        self.retries=[]
        self.metadata=metadata

    def create(self, **kwargs):
        self.create_calls+=1
        return FakeReq(self.outcomes.pop(0),self.retries)

    def update(self, **kwargs):
        self.update_calls+=1
        return FakeReq(self.outcomes.pop(0),self.retries)

    def get(self, **kwargs):
        self.get_calls+=1
        return FakeReq(self.metadata,self.retries)


class DriveRetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/"es.json"
        self.path.write_text('{"segments":[]}',encoding="utf8")
        self.exists=None
        self.lookup_calls=0
        self.waits=[]
        self.media_calls=[]
        def media(*args, **kwargs):
            self.media_calls.append((args,kwargs))
            return {"file":args[0]}
        def lookup(drive,parent,name):
            self.lookup_calls += 1
            if callable(self.exists):
                return self.exists(self.lookup_calls)
            return self.exists
        self.ns={
            "Path":Path,
            "ssl":ssl,
            "RemoteDisconnected":RemoteDisconnected,
            "hashlib":hashlib,
            "mimetypes":mimetypes,
            "time":types.SimpleNamespace(sleep=lambda seconds:self.waits.append(seconds)),
            "MediaFileUpload":media,
            "canonical_marker":lambda name:f"canonical:{name}",
            "find_file":lookup,
        }
        load_functions("translation-system/google_io.py",[
            "_upload_error_status","_transient_upload_error",
            "_uploaded_matches","upload_or_replace_file","update_cells"
        ],self.ns)
        self.ns["_RETRYABLE_UPLOAD_HTTP"]={408,409,429,500,502,503,504}

    def tearDown(self):
        self.tmp.cleanup()

    def upload(self, files):
        return self.ns["upload_or_replace_file"](
            types.SimpleNamespace(files=lambda:files),
            "parent-id", str(self.path),"es.json"
        )

    def test_502_retry_then_succeed_restarts_resumable(self):
        files=FakeFiles([UploadError(502),{"id":"new-file","name":"es.json"}])
        result=self.upload(files)
        self.assertEqual(result["id"],"new-file")
        self.assertEqual(files.create_calls,2)
        self.assertEqual(files.retries,[5,5])
        self.assertEqual(len(self.media_calls),2)
        self.assertEqual(self.waits,[2.0])

    def test_existing_file_retries_updates_not_duplicates(self):
        self.exists={"id":"existing"}
        files=FakeFiles([UploadError(503),{"id":"existing"}],metadata={"size":0})
        self.assertEqual(self.upload(files)["id"],"existing")
        self.assertEqual(files.create_calls,0)
        self.assertEqual(files.update_calls,2)

    def test_ambiguous_create_recovers_verified_bytes_no_duplicate(self):
        self.exists=lambda n: None if n==1 else {"id":"created"}
        data=self.path.read_bytes()
        metadata={"id":"created","size":len(data),
                  "md5Checksum":hashlib.md5(data).hexdigest()}
        files=FakeFiles([UploadError(502)],metadata=metadata)
        result=self.upload(files)
        self.assertEqual(result["id"],"created")
        self.assertEqual(files.create_calls,1)
        self.assertEqual(files.update_calls,0)
        self.assertEqual(files.get_calls,1)

    def test_400_does_not_retry(self):
        files=FakeFiles([UploadError(400)])
        with self.assertRaises(UploadError):
            self.upload(files)
        self.assertEqual(files.create_calls,1)
        self.assertEqual(self.waits,[])

    def test_repeated_502_raises_short_actionable_error(self):
        files=FakeFiles([UploadError(502)]*3)
        with self.assertRaisesRegex(RuntimeError,"after retries: HTTP 502") as ctx:
            self.upload(files)
        self.assertNotIn("<html",str(ctx.exception).lower())
        self.assertEqual(files.retries,[5,5,5])
        self.assertEqual(self.waits,[2.0,4.0])


    def test_ssl_eof_upload_retry_then_succeed(self):
        """A broken TLS connection is transient, not a corrupt MP3."""
        files=FakeFiles([ssl.SSLEOFError(8, "EOF occurred"), {"id":"uploaded"}])
        self.assertEqual(self.upload(files)["id"], "uploaded")
        self.assertEqual(files.create_calls, 2)
        self.assertEqual(self.waits, [2.0])

    def test_sheets_ssl_eof_retry_preserves_same_updates(self):
        outcomes=[ssl.SSLEOFError(8, "EOF occurred"), {"totalUpdatedCells":2}]
        calls=[]
        retries=[]
        class SheetValues:
            def batchUpdate(self, **kwargs):
                calls.append(kwargs)
                return FakeReq(outcomes.pop(0), retries)
        class Sheets:
            def spreadsheets(self):
                return self
            def values(self):
                return SheetValues()
        self.ns["update_cells"](Sheets(),"sheet-id", {"A1":"one","B2":"two"})
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[0],calls[1])
        self.assertEqual(retries,[5,5])
        self.assertEqual(self.waits,[2.0])

    def test_sheets_fatal_400_no_retry(self):
        outcomes=[UploadError(400)]
        count=[]
        class SheetValues:
            def batchUpdate(self, **kwargs):
                count.append(kwargs)
                return FakeReq(outcomes.pop(0),[])
        class Sheets:
            def spreadsheets(self):
                return self
            def values(self):
                return SheetValues()
        with self.assertRaises(UploadError):
            self.ns["update_cells"](Sheets(),"sheet-id",{"A1":"text"})
        self.assertEqual(len(count),1)
        self.assertEqual(self.waits,[])

    def test_sheets_repeated_ssl_eof_keeps_checkpoint_message_short(self):
        outcomes=[ssl.SSLEOFError(8, "EOF occurred") for _ in range(4)]
        count=[]
        class SheetValues:
            def batchUpdate(self, **kwargs):
                count.append(kwargs)
                return FakeReq(outcomes.pop(0), [])
        class Sheets:
            def spreadsheets(self):
                return self
            def values(self):
                return SheetValues()
        with self.assertRaisesRegex(RuntimeError,"checkpoint remains in Drive"):
            self.ns["update_cells"](Sheets(),"sheet-id",{"A1":"text"})
        self.assertEqual(len(count),4)
        self.assertEqual(self.waits,[2.0,4.0,8.0])

    def test_studio_status_does_not_contain_google_html(self):
        ns={}
        load_functions("translation-system/status_io.py",["readable_error"],ns)
        msg=ns["readable_error"](UploadError(502))
        self.assertIn("Google Drive",msg)
        self.assertNotIn("<!DOCTYPE",msg)
        self.assertNotIn("html",msg.lower())
        self.assertEqual(ns["readable_error"](message="Other ordinary error"),"Other ordinary error")


if __name__=="__main__":
    unittest.main()
