import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def isolated_function(path, name, globals_dict):
    parsed = ast.parse(path.read_text(encoding="utf-8"))
    func = next(n for n in parsed.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    script = compile(ast.Module(body=[func], type_ignores=[]), str(path), "exec")
    exec(script, globals_dict)
    return globals_dict[name]


class EnglishCcFetchTests(unittest.TestCase):
    def test_transcript_fast_path_short_circuits_expensive_pot_loop(self):
        fake_path = Path("/tmp/correct-youtube-en.json")
        called = []
        env = {
            "_video_id_from_url": lambda url: "4l1T2MlQYUI",
            "_download_english_cc_via_transcript_api": lambda video_id, wd: (
                called.append(("transcript", video_id)) or fake_path
            ),
            "_download_english_cc_bgutil_retry": lambda *a, **k: (
                called.append(("bgutil", None)) or None
            ),
            "Path": Path,
        }
        run = isolated_function(
            ROOT / "translation-system/youtube_io.py", "download_english_cc", env
        )
        self.assertEqual(run("https://youtu.be/4l1T2MlQYUI", Path("/tmp")), fake_path)
        self.assertEqual(called, [("transcript", "4l1T2MlQYUI")])

    def test_caption_recovery_is_restricted_to_current_lesson(self):
        cc = (ROOT / "translation-system/cc_runner.py").read_text(encoding="utf-8")
        self.assertIn('if args.refresh_english_review:', cc)
        self.assertIn('refreshed = download_english_cc(task["youtube_url"], workdir)', cc)
        self.assertIn('str(existing.get("video_id") or "") == match.group(1)', cc)
        self.assertIn('english_cc = cc_paths.get("en") or stored_english_path', cc)
        self.assertIn("無法依此判定影片沒有 CC", cc)

    def test_chinese_final_is_alignment_source_when_github_cache_missing(self):
        import json
        import tempfile
        from unittest.mock import Mock
        source = {
            "segments": [
                {"id": 0, "start": 0, "end": 20, "text": "????????"},
                {"id": 1, "start": 20, "end": 40, "text": "?????"},
            ]
        }
        with tempfile.TemporaryDirectory() as folder:
            workdir = Path(folder)
            env = {
                "Path": Path,
                "json": json,
                "find_file": lambda *args: {"id": "approved_zh_file"},
                "download_drive_file": lambda drive, id, target: (
                    target.write_text(json.dumps(source, ensure_ascii=False), encoding="utf8")
                ),
                "download_review_cache": Mock(side_effect=AssertionError("should not request missing github cache")),
                "print": lambda *args, **kwargs: None,
            }
            load = isolated_function(
                ROOT / "translation-system/cc_runner.py",
                "load_review_base_from_final_or_cache", env
            )
            result = load(
                "P261-L01", {"transcript": "folder"}, None, workdir
            )
            self.assertEqual(result["source"], "zh-TW.final.json")
            self.assertEqual(len(result["segments"]), 2)
            self.assertTrue(all(x["confirmed"] for x in result["segments"]))
            self.assertTrue((workdir / "zh-TW.review-cache.json").exists())

    def test_english_pipeline_does_not_retranslate_when_cc_is_present(self):
        code = (ROOT / "bridge/apps-script/Code.gs").read_text(encoding="utf-8")
        self.assertIn('readJsonFile_(folders.source, "youtube.en.json")', code)
        self.assertIn('alignEnglishCcToReviewItems_', code)


if __name__ == "__main__":
    unittest.main()
