"""No-cloud contract tests for complete selected-language MP3 delivery."""
import ast
import hashlib
import tempfile
import pathlib
import subprocess
import types
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[2]
def read(path):return (ROOT/path).read_text(encoding="utf-8")
def isolated_functions(path,names,context):
    tree=ast.parse(read(path))
    funcs=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    assert {n.name for n in funcs}==set(names)
    exec(compile(ast.Module(body=funcs,type_ignores=[]),str(path),"exec"),context)
    return context

class DriveFiles:
    def __init__(self,names=()):
        self.names=set(names)
    def files(self):
        return self
    def get(self,fileId,fields=None,supportsAllDrives=True):
        self.fileid=fileId
        return self
    def execute(self):
        return {"id":self.fileid,"size":23422,
                "md5Checksum":getattr(self,"checksums",{}).get(self.fileid),
                "mimeType":
                "audio/x-wav" if self.fileid.endswith(".wav") else "audio/mpeg"}

class DeliveryVerification(unittest.TestCase):
    def setUp(self):
        self.files=DriveFiles(("km.mp3","km.wav"))
        self.manifest={
            "engine":"edge-natural-v2",
            "profile_revision":"2026-10-07-accent-tone-v2",
            "source_sha256":"approved-English-v1",
            "voice":"km-KH-PisethNeural",
            "rate":"-3%","pitch":"-1Hz",
            "assembly_policy":"continuous_total_duration",
            "duration_limit_seconds":1923,
            "status":"done"
        }
        self.ctx={
            "_load_tts_manifest":lambda *args:self.manifest,
            "find_file":lambda d,f,name: {"id":name} if name in d.names else None,
            "NATURAL_TTS_PROFILES":{"km":{"voice":"km-KH-PisethNeural",
                                       "rate":"-3%","pitch":"-1Hz"}},
            "NATURAL_TTS_PROFILE_REVISION":"2026-10-07-accent-tone-v2"
        }
        isolated_functions("translation-system/tts_runner.py",
            ("_verified_drive_audio","verify_uploaded_natural_output"),
            self.ctx)
    def status(self):
        return self.ctx["verify_uploaded_natural_output"](
            self.files,"audio","km","approved-English-v1",1923,"work")
    def test_complete_new_mp3_verified(self):
        self.assertEqual(self.status(),"done")
    def test_missing_mp3_blocks_completion(self):
        self.files.names.remove("km.mp3")
        self.assertEqual(self.status(),"missing")
    def test_old_english_final_blocks_completion(self):
        self.manifest["source_sha256"]="obsolete-English-v0"
        self.assertEqual(self.status(),"missing")
    def test_wrong_voice_and_duration_blocks_completion(self):
        self.manifest["voice"]="km-KH-SreymomNeural"
        self.assertEqual(self.status(),"missing")
        self.manifest["voice"]="km-KH-PisethNeural"
        self.manifest["duration_limit_seconds"]=1850
        self.assertEqual(self.status(),"missing")
    def test_overlong_natural_preview_stays_review(self):
        self.manifest["status"]="needs_review"
        self.files.names={"km.preview.mp3"}
        self.assertEqual(self.status(),"needs_review")
        self.files.names.clear()
        self.assertEqual(self.status(),"missing")

    def test_new_manifest_requires_exact_mp3_and_wav_md5(self):
        self.manifest["audio_receipts"]={
            "mp3":{"size":23422,"md5":"abc123"},
            "wav":{"size":23422,"md5":"wav456"}
        }
        self.files.checksums={"km.mp3":"abc123","km.wav":"wav456"}
        self.assertEqual(self.status(),"done")
        self.files.checksums["km.mp3"]="old-stale-mp3"
        self.assertEqual(self.status(),"missing")
        self.files.checksums["km.mp3"]="abc123"
        self.files.checksums["km.wav"]=None
        self.assertEqual(self.status(),"missing")
        self.files.checksums["km.wav"]="wav456"
        self.manifest["audio_receipts"]["mp3"]["size"]=23423
        self.assertEqual(self.status(),"missing")

    def test_preview_checksum_requires_actual_uploaded_bytes(self):
        self.manifest["status"]="needs_review"
        self.manifest["audio_receipts"]={"preview_mp3":{
            "size":23422,"md5":"expected-preview"
        }}
        self.files.names={"km.preview.mp3"}
        self.files.checksums={"km.preview.mp3":"expected-preview"}
        self.assertEqual(self.status(),"needs_review")
        self.files.checksums["km.preview.mp3"]="old-preview"
        self.assertEqual(self.status(),"missing")

    def test_manifest_uploaded_last_after_both_audio_formats(self):
        uploaded=[]
        ctx={
            "Path":pathlib.Path,
            "upload_or_replace_file":lambda d,f,path,name,display_name:
                uploaded.append(name),
            "formal_drive_name":lambda task,name:name,
        }
        isolated_functions("translation-system/tts_runner.py",
                           ("upload_natural_outputs",),ctx)
        paths={name:name+".file" for name in
               ("mp3","wav","preview_mp3","manifest","alignment_report")}
        result={**paths,"status":"done"}
        ctx["upload_natural_outputs"](None,"audio",result,{})
        self.assertEqual(uploaded,["mp3.file","wav.file",
                                   "alignment_report.file","manifest.file"])
        uploaded.clear()
        result["status"]="needs_review"
        ctx["upload_natural_outputs"](None,"audio",result,{})
        self.assertEqual(uploaded,["preview_mp3.file","alignment_report.file",
                                   "manifest.file"])

class WorkerCompletion(unittest.TestCase):
    def setUp(self):
        self.attempts=[]
        self.sleeps=[]
        self.exit_codes=[]
        def run(cmd):
            self.attempts.append(list(cmd))
            if self.exit_codes:
                code=self.exit_codes.pop(0)
                if code:raise subprocess.CalledProcessError(code,cmd)
        self.ctx={
            "run":run,"subprocess":subprocess,
            "time":types.SimpleNamespace(sleep=lambda n:self.sleeps.append(n))
        }
        isolated_functions("translation-system/web_job_worker.py",
            ("run_verified_tts_job",),self.ctx)
    def invoke(self):
        return self.ctx["run_verified_tts_job"](
            ["python","tts_runner.py","--langs","en,th,es,id,vi,hi,ta,ja,ko,km",
             "--strict-delivery"],retry_waits=(0,0))
    def test_all_ten_success(self):
        self.assertEqual(self.invoke(),"done")
        self.assertEqual(len(self.attempts),1)
    def test_missing_audio_retries_and_succeeds(self):
        self.exit_codes=[2,2,0]
        self.assertEqual(self.invoke(),"done")
        self.assertEqual(len(self.attempts),3)
    def test_persistent_missing_audio_is_never_reported_done(self):
        self.exit_codes=[2,2,2]
        with self.assertRaisesRegex(RuntimeError,"still missing"):
            self.invoke()
        self.assertEqual(len(self.attempts),3)
    def test_preview_only_stays_needs_review_no_wasted_retry(self):
        self.exit_codes=[3]
        self.assertEqual(self.invoke(),"needs_review")
        self.assertEqual(len(self.attempts),1)
    def test_non_delivery_exception_is_retried(self):
        self.exit_codes=[1,0]
        self.assertEqual(self.invoke(),"done")
        self.assertEqual(len(self.attempts),2)

    def test_drive_token_refreshed_on_every_attempt(self):
        self.exit_codes=[2,0]
        calls=[]
        status=self.ctx["run_verified_tts_job"](
            ["python","tts_runner.py","--strict-delivery"],
            retry_waits=(0,),refresh_credentials=lambda:calls.append("fresh"))
        self.assertEqual(status,"done")
        self.assertEqual(calls,["fresh","fresh"])

    def test_translation_uses_checkpoint_retries(self):
        isolated_functions("translation-system/web_job_worker.py",
            ("run_checkpointed_multi",),self.ctx)
        self.exit_codes=[1,0]
        self.ctx["run_checkpointed_multi"](["python","multi.py"],
                                          retry_waits=(0,))
        self.assertEqual(len(self.attempts),2)

class WiringContracts(unittest.TestCase):
    def test_final_and_tts_are_strict_and_report_actual_status(self):
        worker=read("translation-system/web_job_worker.py")
        runner=read("translation-system/tts_runner.py")
        self.assertIn('elif args.stage == "finish":',worker)
        self.assertIn('audio_result=run_verified_tts_job([',worker)
        self.assertIn('"--strict-delivery",',worker)
        self.assertIn('if cmd and args.stage=="tts":',worker)
        self.assertIn('"needs_review" if audio_result=="needs_review" else "done"',worker)
        self.assertIn('if args.strict_delivery and strict_missing:',runner)
        self.assertIn('if args.strict_delivery and strict_review:',runner)
        self.assertIn('delivered=verify_uploaded_natural_output(',runner)
        self.assertIn('delivered=verify_uploaded_natural_output(',runner)
        self.assertIn('result["status"] == "needs_review"',runner)
        self.assertIn('upload_natural_outputs(',runner)
        self.assertIn('delivered=verify_uploaded_natural_output(',runner)
        self.assertNotIn('smart_fit_review.mp3',runner)
        self.assertIn('strict_missing.extend(',runner)
        self.assertIn('audio_receipts',runner)
        self.assertIn('md5Checksum',runner)
        self.assertIn('voice_access_denials >= 2',runner)
        edge=read('translation-system/natural_tts_edge.py')
        self.assertIn('Microsoft Edge TTS WebSocket HTTP 403',edge)

if __name__=="__main__":
    unittest.main()
