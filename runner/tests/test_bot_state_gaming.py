#!/usr/bin/env python3
"""Tests for state_gaming_licensing bot — builds via bot_factory and asserts admission."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bots"))
from bots.state_gaming_licensing import SPEC
import bot_factory as bf

_EXPECTED = {item["issue"]["q"]: item["expected"] for item in SPEC.eval_set}

def _mock_invoker(persona, issue):
    q = issue.get("q", "")
    expected = _EXPECTED.get(q, "unknown")
    return {"stance": expected, "confidence": 0.85, "citations": ["mock-ref"]}

class TestStateGamingLicensingBot(unittest.TestCase):
    def test_spec_is_valid(self):
        bf._validate_spec(SPEC)
    def test_spec_role(self):
        self.assertEqual(SPEC.role, "discipline")
    def test_spec_target_app(self):
        self.assertEqual(SPEC.target_app, "apparently")
    def test_spec_has_enough_evals(self):
        self.assertGreaterEqual(len(SPEC.eval_set), 5)
    def test_admitted_with_correct_invoker(self):
        result = bf.build_bot(SPEC, _mock_invoker)
        self.assertEqual(result["admission"], "admitted")
        self.assertEqual(result["manifest"]["id"], "state-gaming-licensing-analyst")
        self.assertEqual(result["manifest"]["role"], "discipline")
    def test_manifest_has_corpus_filter(self):
        result = bf.build_bot(SPEC, _mock_invoker)
        cf = result["manifest"]["corpus_filter"]
        self.assertIn("NV-GCB", cf["source"])
        self.assertIn("statute", cf["doc_types"])

if __name__ == "__main__":
    unittest.main()
