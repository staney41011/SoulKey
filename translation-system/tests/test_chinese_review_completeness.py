"""Regression gates for partial Chinese Final repair and full review loading."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ChineseReviewCompletenessTests(unittest.TestCase):
    def test_p260_l02_recovery_preserves_every_segment_and_human_edits(self):
        path = ROOT / "studio-review-cache" / "P260-L02" / "zh.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data["segments"]
        self.assertEqual(data["total_segments"], 312)
        self.assertEqual(len(items), 312)
        self.assertEqual([x["id"] for x in items], list(range(312)))
        self.assertLess(items[0]["start"], 5)
        self.assertGreater(items[-1]["end"], 1420)
        self.assertEqual(sum(x.get("confirmed") is True for x in items), 50)
        self.assertTrue(all(items[i]["confirmed"] for i in range(150, 200)))
        self.assertTrue(data["review_required"])

    def test_frontend_renders_merged_chunks_and_blocks_incomplete_final(self):
        script = (ROOT / "studio" / "app-20260923-48.js").read_text(encoding="utf-8")
        self.assertIn("renderSegments(zhFreshSegments)", script)
        self.assertIn("renderSegments(merged);", script)
        self.assertIn("zhReviewHasCompleteCoverage()", script)
        self.assertIn("setZhFinalizeEnabled(complete)", script)
        self.assertIn("if(!zhReviewHasCompleteCoverage())", script)

    def test_bridge_never_approves_a_partial_batch(self):
        bridge = (ROOT / "bridge" / "apps-script" / "Code.gs").read_text(encoding="utf-8")
        self.assertIn('error:"incomplete_zh_final"', bridge)
        self.assertIn("expected_segments:expected", bridge)
        self.assertIn("partialChineseFinal", bridge)
        self.assertIn("If a historical finalize stored only one batch", bridge)


if __name__ == "__main__":
    unittest.main()
