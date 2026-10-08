"""Run Qwen JSON robustness tests without loading torch or the GPU model."""
import ast
import json
import re
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "polish.py"
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
needed = {"_extract_json_object", "_batch_corrections_or_preserve"}
functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in needed]
assert {node.name for node in functions} == needed
scope = {"json": json, "re": re}
exec(compile(ast.Module(body=functions, type_ignores=[]), str(SOURCE), "exec"), scope)


def execute(outputs, prepared):
    generated = iter(outputs)
    counts = []
    def fake_generate(_tokenizer, _model, _messages, max_new_tokens=2200):
        counts.append(max_new_tokens)
        return next(generated)
    scope["_generate_json"] = fake_generate
    parsed, preserved = scope["_batch_corrections_or_preserve"](
        None, None, [{"role": "user", "content": "polish"}], prepared,
    )
    return parsed, preserved, counts


class QwenJsonResilienceTests(unittest.TestCase):
    def test_retries_a_single_bad_chunk_before_accepting_corrected_text(self):
        parsed, preserved, counts = execute(
            ['{"segments":[{"id":0,"text":"bad"','{"segments":[{"id":0,"text":"修正文字"}]}'],
            [{"id": 0, "text": "原始逐字稿"}],
        )
        self.assertFalse(preserved)
        self.assertEqual(parsed["segments"][0]["text"], "修正文字")
        self.assertEqual(counts, [2200, 2600])

    def test_two_invalid_responses_preserve_every_source_segment_and_flag_it(self):
        batch = [{"id": 0, "text": "原來第一句"}, {"id": 1, "text": "原來第二句"}]
        parsed, preserved, counts = execute(
            ['{"segments":[{"id":0,"text":"oops"', '{"segments":{}'],
            batch,
        )
        self.assertTrue(preserved)
        self.assertEqual(len(parsed["segments"]), 2)
        self.assertEqual([x["text"] for x in parsed["segments"]], [x["text"] for x in batch])
        self.assertTrue(all(x["uncertain"] for x in parsed["segments"]))
        self.assertEqual(len(counts), 2)

    def test_partial_json_does_not_drop_a_segment(self):
        parsed, preserved, _ = execute(
            ['{"segments":[{"id":0,"text":"修正第一句"}]}'],
            [{"id": 0, "text": "第一句"}, {"id": 1, "text": "第二句"}],
        )
        self.assertFalse(preserved)
        self.assertEqual(len(parsed["segments"]), 2)
        self.assertEqual(parsed["segments"][1]["text"], "第二句")
        self.assertIn("人工核對", parsed["segments"][1]["uncertain"][0])

    def test_second_pass_preserves_current_text_if_reply_invalid(self):
        parsed, preserved, _ = execute(
            ["garbled", "not json"],
            [{"id": 2, "raw": "ASR原文", "current": "已校正版本"}],
        )
        self.assertTrue(preserved)
        self.assertEqual(parsed["segments"][0]["text"], "已校正版本")


if __name__ == "__main__":
    unittest.main()
