"""Guard against false "done" status on legacy under-length MP3 manifests.

The function is extracted with AST to keep this check independent from live
Google Drive, Edge TTS, or Kaggle credentials.
"""
import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TREE = ast.parse((ROOT / "tts_runner.py").read_text(encoding="utf-8"))
FN = next(x for x in TREE.body if isinstance(x, ast.FunctionDef)
          and x.name == "verify_uploaded_natural_output")

def verify_with_timeline(timeline):
    profile={"voice":"en-US-AndrewMultilingualNeural","rate":"-4%","pitch":"-2Hz"}
    manifest={
        "engine":"edge-natural-v2",
        "profile_revision":"test-v2",
        "source_sha256":"source-sha",
        **profile,
        "assembly_policy":"continuous_total_duration",
        "duration_limit_seconds":1829.0,
        "status":"done",
        "timeline":timeline,
    }
    scope={
        "_load_tts_manifest": lambda *args: manifest,
        "_verified_drive_audio": lambda *args: True,
        "NATURAL_TTS_PROFILES":{"en":profile},
        "NATURAL_TTS_PROFILE_REVISION":"test-v2",
        "MIN_NARRATION_TO_SOURCE_RATIO":0.96,
    }
    exec(compile(ast.Module(body=[FN],type_ignores=[]),"<tts_verify>", "exec"),scope)
    return scope["verify_uploaded_natural_output"](
        None,"test-audio","en","source-sha",1829.0,None
    )

class LegacyShortManifestTests(unittest.TestCase):
    def test_real_p259_l04_english_24m_vs_30m_is_not_done(self):
        self.assertEqual(verify_with_timeline({"final_duration":1468.901}),"needs_review")

    def test_below_96_percent_is_not_done(self):
        self.assertEqual(verify_with_timeline({"final_duration":1755.0}),"needs_review")

    def test_96_percent_with_margin_can_be_done(self):
        self.assertEqual(verify_with_timeline({"final_duration":1755.90}),"done")

    def test_invalid_duration_is_not_done(self):
        self.assertEqual(verify_with_timeline({"final_duration":"nan-data"}),"needs_review")

if __name__=="__main__":
    unittest.main()
