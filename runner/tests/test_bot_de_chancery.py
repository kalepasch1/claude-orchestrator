#!/usr/bin/env python3
"""Tests for de_chancery bot — builds via bot_factory and asserts admission."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bots"))
from bots.de_chancery import SPEC
import bot_factory as bf

_EXPECTED = {item["issue"]["q"]: item["expected"] for item in SPEC.eval_set}

def _mock_invoker(persona, issue):
    q = issue.get("q", "")
    expected = _EXPECTED.get(q, "unknown")
    return {"stance": expected, "confidence": 0.88, "citations": ["mock-ref"]}

class TestDeChanceryBot(unittest.TestCase):
    def test_spec_is_valid(self):
        bf._validate_spec(SPEC)
    def test_spec_role(self):
        self.assertEqual(SPEC.role, "reviewer")
    def test_spec_target_app(self):
        self.assertEqual(SPEC.target_app, "apparently")
    def test_spec_priors_tag(self):
        self.assertEqual(SPEC.priors_tag, "de_chancery")
    def test_spec_has_enough_evals(self):
        self.assertGreaterEqual(len(SPEC.eval_set), 5)
    def test_admitted_with_correct_invoker(self):
        result = bf.build_bot(SPEC, _mock_invoker)
        self.assertEqual(result["admission"], "admitted")
        self.assertEqual(result["manifest"]["id"], "de-chancery-recipient")
        self.assertEqual(result["manifest"]["role"], "reviewer")
    def test_manifest_has_corpus_filter(self):
        result = bf.build_bot(SPEC, _mock_invoker)
        cf = result["manifest"]["corpus_filter"]
        self.assertIn("DE_Chancery", cf["source"])
        self.assertIn("opinion", cf["doc_types"])
    def test_manifest_has_competence(self):
        result = bf.build_bot(SPEC, _mock_invoker)
        comp = result["manifest"]["competence"]
        self.assertIn("fiduciary_duty_analysis", comp)
        self.assertIn("rfi_anticipation", comp)
    def test_eval_pass_rate(self):
        result = bf.run_eval(SPEC, _mock_invoker)
        self.assertEqual(result["passed"], result["total"])
    def test_gated_with_bad_invoker(self):
        def bad_invoker(persona, issue):
            return {"stance": "wrong_answer", "confidence": 0.5, "citations": []}
        result = bf.build_bot(SPEC, bad_invoker)
        self.assertEqual(result["admission"], "gated")

if __name__ == "__main__":
    unittest.main()
