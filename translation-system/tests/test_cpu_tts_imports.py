"""Prevent Edge CPU jobs accidentally importing heavy MMS/torch dependencies."""
import ast
import builtins
import importlib
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

SYSTEM = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SYSTEM))
from tts_fingerprint import segments_fingerprint


class EdgeCPUImports(unittest.TestCase):
    def test_exact_legacy_fingerprint_compatibility(self):
        source = (SYSTEM / "tts_engine.py").read_text(encoding="utf-8")
        module = ast.parse(source)
        old_fn = next(
            node for node in module.body
            if isinstance(node, ast.FunctionDef) and node.name == "segments_fingerprint"
        )
        isolated = ast.Module(body=[old_fn], type_ignores=[])
        values = {"json": json}
        import hashlib
        values["hashlib"] = hashlib
        exec(compile(isolated, "old_fingerprint", "exec"), values)
        old = values["segments_fingerprint"]
        examples = [
            [],
            [{"id": 1, "start": 0, "end": 2, "text": "The value is 2.5."}],
            [{"id": 1, "start": "0", "end": 3.02, "text": "願意開啟心靈的鎖匙"}],
            [{"text": ""}, {"text": " learning ", "start": 1.5}],
            [{"id": 7, "start": 0, "end": 3, "text": "ภาษาไทย"}],
        ]
        for segments in examples:
            with self.subTest(segments=segments):
                self.assertEqual(old(segments), segments_fingerprint(segments))

    def test_edge_runner_never_loads_gpu_only_dependencies(self):
        blocked = {"numpy", "scipy", "torch", "transformers"}
        original = builtins.__import__
        def only_light(name, *args, **kwargs):
            if name.split(".")[0] in blocked:
                raise ModuleNotFoundError(
                    f"GPU-only package {name} must not be imported by CPU Edge runner"
                )
            return original(name, *args, **kwargs)
        with mock.patch("builtins.__import__", side_effect=only_light):
            sys.modules.pop("tts_runner", None)
            runner = importlib.import_module("tts_runner")
            self.assertIs(runner.segments_fingerprint, segments_fingerprint)
        self.assertNotIn("tts_engine", runner.__dict__)


if __name__ == "__main__":
    from unittest import mock
    unittest.main()
