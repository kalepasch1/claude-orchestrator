#!/usr/bin/env python3
"""Tests for health.py — portfolio health score and unified action inbox."""
import sys, os, types, unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Stub db before importing health
db_mod = types.ModuleType("db")
db_mod.select = MagicMock(return_value=[])
sys.modules.setdefault("db", db_mod)

import health


class TestScores(unittest.TestCase):
    @patch.object(db_mod, "select", return_value=[
        {"project": "alpha", "health_score": 85, "blocked": 0, "open_approvals": 1},
        {"project": "beta", "health_score": 92, "blocked": 1, "open_approvals": 0},
    ])
    def test_scores_returns_rows(self, mock_sel):
        result = health.scores()
        self.assertEqual(len(result), 2)
        mock_sel.assert_called_once_with("v_project_health", {"select": "*", "order": "health_score.asc"})

    @patch.object(db_mod, "select", return_value=[])
    def test_scores_empty(self, _):
        self.assertEqual(health.scores(), [])

    @patch.object(db_mod, "select", return_value=None)
    def test_scores_none_returns_empty(self, _):
        self.assertEqual(health.scores(), [])


class TestInbox(unittest.TestCase):
    @patch.object(db_mod, "select", return_value=[{"id": 1, "action": "approve"}])
    def test_inbox_returns_items(self, mock_sel):
        result = health.inbox()
        self.assertEqual(len(result), 1)
        mock_sel.assert_called_once_with("v_action_inbox", {"select": "*"})


class TestSummary(unittest.TestCase):
    @patch.object(db_mod, "select")
    def test_summary_with_projects(self, mock_sel):
        mock_sel.side_effect = [
            # scores() call
            [
                {"project": "a", "health_score": 80, "blocked": 2, "open_approvals": 3},
                {"project": "b", "health_score": 90, "blocked": 0, "open_approvals": 1},
                {"project": "c", "health_score": 100, "blocked": 0, "open_approvals": 0},
            ],
            # inbox() call
            [{"id": 1}, {"id": 2}],
        ]
        s = health.summary()
        self.assertEqual(s["projects"], 3)
        self.assertAlmostEqual(s["avg_health"], 90.0)
        self.assertEqual(len(s["needs_attention"]), 3)
        self.assertEqual(s["inbox_count"], 2)
        self.assertEqual(s["needs_attention"][0]["project"], "a")

    @patch.object(db_mod, "select")
    def test_summary_empty(self, mock_sel):
        mock_sel.return_value = []
        s = health.summary()
        self.assertEqual(s["projects"], 0)
        self.assertEqual(s["avg_health"], 100)
        self.assertEqual(s["needs_attention"], [])

    @patch.object(db_mod, "select")
    def test_summary_single_project(self, mock_sel):
        mock_sel.side_effect = [
            [{"project": "solo", "health_score": 55, "blocked": 1, "open_approvals": 5}],
            [],  # empty inbox
        ]
        s = health.summary()
        self.assertEqual(s["projects"], 1)
        self.assertAlmostEqual(s["avg_health"], 55.0)
        self.assertEqual(s["inbox_count"], 0)


if __name__ == "__main__":
    unittest.main()
