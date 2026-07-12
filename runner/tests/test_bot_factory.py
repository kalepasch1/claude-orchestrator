#!/usr/bin/env python3
"""Tests for bot_factory.py — BotSpec validation, eval, and admission."""
import os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import bot_factory as bf


def _make_spec(**overrides):
    base = {
        "id": "test-bot-1",
        "role": "authority",
        "target_app": "apparently",
        "corpus_filter": {"source": ["CFTC"], "doc_types": ["order"]},
        "priors_tag": "test_priors",
        "competence": {"regulatory": 0.9},
        "authority": 0.8,
        "reliability": 0.85,
        "eval_set": [
            {"issue": {"q": f"question-{i}"}, "expected": "approve"}
            for i in range(5)
        ],
    }
    base.update(overrides)
    return bf.BotSpec(**base)

def _passing_invoker(persona, issue):
    return {"stance": "approve", "confidence": 0.9, "citations": ["ref-1"]}

def _failing_invoker(persona, issue):
    return {"stance": "deny", "confidence": 0.95, "citations": []}

def _low_calibration_invoker(persona, issue):
    if issue.get("q", "").endswith(("0", "1")):
        return {"stance": "approve", "confidence": 0.9, "citations": []}
    return {"stance": "deny", "confidence": 0.9, "citations": []}

class TestBotSpecValidation(unittest.TestCase):
    def test_valid_spec_accepted(self):
        spec = _make_spec()
        self.assertEqual(spec.role, "authority")
    def test_invalid_role_raises(self):
        with self.assertRaises(ValueError):
            spec = _make_spec(role="invalid_role")
            bf._validate_spec(spec)
    def test_bad_role_validate(self):
        spec = _make_spec()
        spec.role = "invalid_role"
        with self.assertRaises(ValueError):
            bf._validate_spec(spec)
    def test_empty_corpus_filter_raises(self):
        spec = _make_spec(corpus_filter={})
        with self.assertRaises(ValueError):
            bf._validate_spec(spec)
    def test_too_few_eval_raises(self):
        spec = _make_spec(eval_set=[{"issue": {"q": "x"}, "expected": "y"}])
        with self.assertRaises(ValueError):
            bf._validate_spec(spec)

class TestRunEval(unittest.TestCase):
    def test_passing_eval(self):
        spec = _make_spec()
        result = bf.run_eval(spec, _passing_invoker)
        self.assertEqual(result["passed"], 5)
        self.assertEqual(result["total"], 5)
        self.assertGreater(result["calibration"], 0.0)
    def test_failing_eval(self):
        spec = _make_spec()
        result = bf.run_eval(spec, _failing_invoker)
        self.assertEqual(result["passed"], 0)
        self.assertEqual(result["total"], 5)

class TestBuildBot(unittest.TestCase):
    def test_admitted_with_passing_invoker(self):
        spec = _make_spec()
        result = bf.build_bot(spec, _passing_invoker)
        self.assertEqual(result["admission"], "admitted")
        self.assertIn("manifest", result)
        m = result["manifest"]
        self.assertEqual(m["id"], "test-bot-1")
        self.assertEqual(m["role"], "authority")
        self.assertEqual(m["priors_tag"], "test_priors")
        self.assertEqual(m["corpus_filter"], {"source": ["CFTC"], "doc_types": ["order"]})
    def test_gated_with_failing_invoker(self):
        spec = _make_spec()
        result = bf.build_bot(spec, _failing_invoker)
        self.assertEqual(result["admission"], "gated")
    def test_gated_with_low_calibration(self):
        spec = _make_spec()
        result = bf.build_bot(spec, _low_calibration_invoker)
        self.assertEqual(result["admission"], "gated")
    def test_invalid_spec_raises(self):
        spec = _make_spec(corpus_filter={})
        with self.assertRaises(ValueError):
            bf.build_bot(spec, _passing_invoker)
    def test_manifest_shape(self):
        spec = _make_spec()
        result = bf.build_bot(spec, _passing_invoker)
        m = result["manifest"]
        for key in ("id", "role", "competence", "authority", "reliability", "priors_tag", "corpus_filter"):
            self.assertIn(key, m)

if __name__ == "__main__":
    unittest.main()
