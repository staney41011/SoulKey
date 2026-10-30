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

if __name__=="__main__":unittest.main(verbosity=2)
