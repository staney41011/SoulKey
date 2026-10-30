#!/usr/bin/env python3
"""Offline regression tests for conservative P259 Gemma4 QA recovery."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

source_path=Path(__file__).resolve().with_name("p259_gemma4_kaggle.py")
spec=importlib.util.spec_from_file_location("p259_engine",source_path)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
SRC=[{"id":58,"text":"We should remember the kindness of others."}]
TARGET=[{"id":58,"text":"他人の親切を忘れてはいけません。"}]

class FakeGemma:
    def __init__(self,verdict):
        self.verdict=verdict
        self.requests=[]
    def json(self,prompt,limit=0):
        self.requests.append(prompt)
        if "independent final translation reviewer" in prompt:
            return {"verdict":self.verdict,"evidence":"compared whole meaning"}
        return {"segments":TARGET}

class Tests(unittest.TestCase):
    def test_no_failures_need_no_adjudication(self):
        g=FakeGemma("accurate")
        with patch.object(m,"qa",return_value={}):
            rows,batches,repairs=m.repair(g,"ja",SRC,TARGET)
        self.assertEqual(rows,TARGET)
        self.assertEqual(batches,1)
        self.assertEqual(repairs,0)
        self.assertEqual(g.requests,[])

    def test_semantic_false_positive_requires_independent_check(self):
        g=FakeGemma("accurate")
        with patch.object(m,"qa",return_value={58:["possible omitted context"]}),patch.object(m,"local_issues",return_value=[]):
            rows,batches,repairs=m.repair(g,"ja",SRC,TARGET)
        self.assertEqual(rows,TARGET)
        self.assertEqual(batches,6)
        self.assertEqual(repairs,4)
        self.assertEqual(sum("independent final translation reviewer" in x for x in g.requests),1)

    def test_deterministic_failure_cannot_be_overridden(self):
        g=FakeGemma("accurate")
        with patch.object(m,"qa",return_value={58:["missing number"]}),patch.object(m,"local_issues",return_value=["numbers_mismatch"]):
            with self.assertRaisesRegex(ValueError,"gemma4_unresolved_qa_ja_58"):
                m.repair(g,"ja",SRC,TARGET)
        self.assertFalse(any("independent final translation reviewer" in x for x in g.requests))

    def test_uncertain_review_never_passes(self):
        g=FakeGemma("uncertain")
        with patch.object(m,"qa",return_value={58:["possible omission"]}),patch.object(m,"local_issues",return_value=[]):
            with self.assertRaisesRegex(ValueError,"gemma4_unresolved_qa_ja_58"):
                m.repair(g,"ja",SRC,TARGET)

    def test_material_issue_never_passes(self):
        g=FakeGemma("material_issue")
        with patch.object(m,"qa",return_value={58:["incorrect negation"]}),patch.object(m,"local_issues",return_value=[]):
            with self.assertRaisesRegex(ValueError,"gemma4_unresolved_qa_ja_58"):
                m.repair(g,"ja",SRC,TARGET)

    def test_semantic_pass_cache_rechecks_changed_translation_only(self):
        class Reviewer:
            def __init__(self):
                self.requests=[]
            def json(self,prompt,limit=0):
                self.requests.append(prompt)
                return {"failures":[]}
        source=[
            {"id":58,"text":"Please protect the precious teachings."},
            {"id":59,"text":"And care for your neighbors."},
        ]
        initial=[
            {"id":58,"text":"大切な教えを守ってください。"},
            {"id":59,"text":"隣人を大切にしましょう。"},
        ]
        changed=[
            initial[0],
            {"id":59,"text":"近所の人々を思いやりましょう。"},
        ]
        g=Reviewer()
        cache=set()
        with patch.object(m,"local_issues",return_value=[]):
            self.assertEqual(m.qa(g,"ja",source,initial,cache),{})
            self.assertEqual(len(g.requests),1)
            self.assertEqual(m.qa(g,"ja",source,initial,cache),{})
            self.assertEqual(len(g.requests),1)
            self.assertEqual(m.qa(g,"ja",source,changed,cache),{})
        self.assertEqual(len(g.requests),2)
        self.assertIn('"id": 59',g.requests[-1])
        self.assertNotIn('"id": 58',g.requests[-1])

    def test_cached_semantic_pass_cannot_bypass_hard_number_check(self):
        g=FakeGemma("accurate")
        source=[{"id":58,"text":"There are 25 people."}]
        translations=[{"id":58,"text":"25人がいます。"}]
        cache={(58,"25人がいます。")}
        with patch.object(m,"local_issues",return_value=["missing_number:25"]):
            self.assertEqual(m.qa(g,"ja",source,translations,cache),
                             {58:["missing_number:25"]})
        self.assertEqual(g.requests,[])

    def test_neutral_numbers_and_punctuation_do_not_deadlock_qa(self):
        # Numeric-only subtitle fragments are correct even when unchanged.
        for segment in ["2026", "7.", "...", "1,200"]:
            with self.subTest(segment=segment):
                self.assertNotIn("empty_or_english_copy",
                                 m.local_issues(segment,segment,"pt"))

    def test_real_english_sentence_cannot_be_reused_as_translation(self):
        for language in ["pt","it","ja"]:
            with self.subTest(language=language):
                self.assertIn("empty_or_english_copy",
                              m.local_issues("We should be kind.","We should be kind.",language))

    def test_blank_target_still_fails(self):
        self.assertIn("empty_or_english_copy",m.local_issues("2026","","pt"))

if __name__=="__main__":unittest.main(verbosity=2)
