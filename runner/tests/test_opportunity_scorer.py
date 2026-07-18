#!/usr/bin/env python3
"""Tests for opportunity_scorer module."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import opportunity_scorer as os_mod


class OpportunityScorerTest(unittest.TestCase):
    def test_score_proposal_returns_dict_with_required_keys(self):
        """score_proposal must return at least 'score' and 'reasoning'."""
        with patch.object(os_mod.db, "select", return_value=[]):
            result = os_mod.score_proposal(
                proposal_text="test",
                project_id="test-proj",
                surface_returns={},
            )
        for key in ["score", "reasoning", "components"]:
            self.assertIn(key, result)

    def test_zero_score_when_no_surface_returns(self):
        """When surface_returns is empty, components must be zero."""
        with patch.object(os_mod.db, "select", return_value=[]):
            result = os_mod.score_proposal(
                proposal_text="test",
                project_id="p",
                surface_returns={},
            )
        self.assertEqual(result["score"], 0.0)
        for comp in result["components"].values():
            self.assertEqual(comp, 0.0)

    def test_scales_with_past_return(self):
        """A proposal with a matching historical return should score > 0."""
        def fake_select(_table, _params=None):
            return [{"surface": "test", "roi": 500.0}]

        with patch.object(os_mod.db, "select", side_effect=fake_select):
            result = os_mod.score_proposal(
                proposal_text="test",
                project_id="p",
                surface_returns={"test": 100.0},
            )
        self.assertGreater(result["score"], 0.0)
        self.assertIn("test", result["components"])


class OpportunitySummaryTest(unittest.TestCase):
    def test_summary_contains_expected_counts(self):
        """summarize_opportunities returns counts for key pipelines."""
        fake_rows = [
            {"status": "queued"},
            {"status": "queued"},
            {"status": "approved"},
        ]
        with patch.object(os_mod.db, "select", return_value=fake_rows):
            summary = os_mod.summarize_opportunities(project_id="p")
        self.assertEqual(summary["queued"], 2)
        self.assertEqual(summary["approved"], 1)

    def test_empty_result_returns_empty_dict(self):
        """When no rows, return empty counts."""
        with patch.object(os_mod.db, "select", return_value=[]):
            summary = os_mod.summarize_opportunities(project_id="p")
        self.assertEqual(summary, {})


if __name__ == "__main__":
    unittest.main()
