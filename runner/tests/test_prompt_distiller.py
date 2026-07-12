#!/usr/bin/env python3
"""Tests for runner/prompt_distiller.py"""
import sys, os, unittest
from unittest.mock import patch
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import prompt_distiller

class TestEstimateTokens(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(prompt_distiller._estimate_tokens("abcd"), 1)
        self.assertEqual(prompt_distiller._estimate_tokens("abcdefgh"), 2)
    def test_empty(self):
        self.assertEqual(prompt_distiller._estimate_tokens(""), 0)
        self.assertEqual(prompt_distiller._estimate_tokens(None), 0)

class TestStripDirectives(unittest.TestCase):
    def test_preflight(self):
        r = prompt_distiller._strip_directives("Do thing.\nPREFLIGHT DIRECTIVE blah\nMore.")
        self.assertNotIn("PREFLIGHT DIRECTIVE", r)
        self.assertIn("Do thing", r)
    def test_agentic(self):
        self.assertNotIn("AGENTIC-REPAIR", prompt_distiller._strip_directives("Fix.\nAGENTIC-REPAIR ctx"))
    def test_clean(self):
        self.assertEqual(prompt_distiller._strip_directives("normal"), "normal")

class TestExtractConventions(unittest.TestCase):
    def test_finds_recurring(self):
        line = "DO: always commit tests before merging code changes"
        prompts = [line, line, line]
        r = prompt_distiller.extract_conventions(prompts)
        self.assertTrue(any("always commit tests" in c for c in r))
    def test_skips_rare(self):
        prompts = ["DO: unique thing only once here."]
        self.assertEqual(prompt_distiller.extract_conventions(prompts), [])

class TestDistillPrompt(unittest.TestCase):
    def test_removes_directives(self):
        p = "Fix bug.\nPREFLIGHT DIRECTIVE no diff\nAGENTIC-REPAIR context\nDone."
        r = prompt_distiller.distill_prompt(p)
        self.assertNotIn("PREFLIGHT", r)
        self.assertNotIn("AGENTIC-REPAIR", r)
        self.assertIn("Fix bug", r)
    def test_deduplicates_lines(self):
        p = "Line A\nLine B\nLine A\nLine C"
        r = prompt_distiller.distill_prompt(p)
        self.assertEqual(r.count("Line A"), 1)
    def test_collapses_blanks(self):
        p = "A\n\n\n\n\nB"
        r = prompt_distiller.distill_prompt(p)
        self.assertNotIn("\n\n\n", r)

class TestMeasureSavings(unittest.TestCase):
    def test_savings(self):
        r = prompt_distiller.measure_savings("a" * 400, "a" * 200)
        self.assertEqual(r["original_tokens"], 100)
        self.assertEqual(r["distilled_tokens"], 50)
        self.assertEqual(r["tokens_saved"], 50)
        self.assertEqual(r["savings_pct"], 50.0)
    def test_empty(self):
        r = prompt_distiller.measure_savings("", "")
        self.assertEqual(r["savings_pct"], 0.0)

class TestSweep(unittest.TestCase):
    @patch("prompt_distiller.db")
    def test_returns_report(self, mock_db):
        mock_db.select.return_value = [
            {"id":"1","slug":"s1","prompt":"DO: always test. " * 20,"note":"ok"},
            {"id":"2","slug":"s2","prompt":"DO: always test. " * 20,"note":"ok"},
        ]
        r = prompt_distiller.sweep("p")
        self.assertEqual(r["tasks_analysed"], 2)
        self.assertIn("total_potential_savings", r)
    @patch("prompt_distiller.db")
    def test_handles_error(self, mock_db):
        mock_db.select.side_effect = Exception("net")
        r = prompt_distiller.sweep("p")
        self.assertEqual(r["tasks_analysed"], 0)

class TestRecordSavings(unittest.TestCase):
    @patch("prompt_distiller.db")
    def test_upserts(self, mock_db):
        prompt_distiller.record_savings("p", {"tokens_saved": 50})
        mock_db.upsert.assert_called_once()
    @patch("prompt_distiller.db")
    def test_swallows_error(self, mock_db):
        mock_db.upsert.side_effect = Exception("net")
        prompt_distiller.record_savings("p", {})  # should not raise

if __name__ == "__main__":
    unittest.main()
