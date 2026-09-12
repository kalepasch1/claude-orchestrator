#!/usr/bin/env python3
"""Tests for health.py — portfolio health score and unified action inbox."""
import sys, os, unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# REWRITTEN (module preamble). This file used to build a throwaway ModuleType("db"), register it
# with sys.modules.setdefault("db", db_mod) and then @patch.object(db_mod, "select", ...).
# setdefault is a no-op whenever anything has already imported the real db — which the repo-root
# and runner/tests conftests both do — so the stub was never wired to anything. health.py kept
# its reference to the REAL db module, every test drove live PostgREST, and all seven blew up
# with RuntimeError("set SUPABASE_URL and SUPABASE_SERVICE_KEY"). Patching db.select on the real
# module object is what actually intercepts health.py's calls, so that is what we do now.
import db
import health
import pipeline_metrics


class TestScores(unittest.TestCase):
    @patch.object(db, "select", return_value=[
        {"project": "alpha", "health_score": 85, "blocked": 0, "open_approvals": 1},
        {"project": "beta", "health_score": 92, "blocked": 1, "open_approvals": 0},
    ])
    def test_scores_returns_rows(self, mock_sel):
        result = health.scores()
        self.assertEqual([r["project"] for r in result], ["alpha", "beta"])
        # scores() promises "worst first", which it delegates to the view's ordering.
        mock_sel.assert_called_once_with("v_project_health", {"select": "*", "order": "health_score.asc"})

    @patch.object(db, "select", return_value=[])
    def test_scores_empty(self, _):
        self.assertEqual(health.scores(), [])

    @patch.object(db, "select", return_value=None)
    def test_scores_none_returns_empty(self, _):
        # db.select returns None on a soft failure; scores() must coerce that to [] so callers
        # (digest.py, the dashboard) never iterate None.
        self.assertEqual(health.scores(), [])


class TestInbox(unittest.TestCase):
    @patch.object(db, "select", return_value=[{"id": 1, "action": "approve"}])
    def test_inbox_returns_items(self, mock_sel):
        result = health.inbox()
        self.assertEqual(result, [{"id": 1, "action": "approve"}])
        mock_sel.assert_called_once_with("v_action_inbox", {"select": "*"})


class TestSummary(unittest.TestCase):
    """summary() fans out to scores() + inbox() + test_pipeline().

    pipeline_metrics.get_health is stubbed rather than left to consume the db.select side_effect
    queue: summary() calls it third, so a bare side_effect list of two would feed it whichever
    rows happened to be left (or a StopIteration it silently swallows), making the assertions
    below depend on an unrelated module's query count.
    """

    def setUp(self):
        patcher = patch.object(pipeline_metrics, "get_health",
                               return_value={"lookback_minutes": 60, "by_task_type": {}})
        self.mock_pipeline = patcher.start()
        self.addCleanup(patcher.stop)

    @patch.object(db, "select")
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
        self.assertEqual(s["inbox_count"], 2)
        # needs_attention is the worst THREE rows, projected onto a fixed shape.
        self.assertEqual(s["needs_attention"], [
            {"project": "a", "score": 80, "blocked": 2, "approvals": 3},
            {"project": "b", "score": 90, "blocked": 0, "approvals": 1},
            {"project": "c", "score": 100, "blocked": 0, "approvals": 0},
        ])
        self.assertEqual(s["test_pipeline"], {"lookback_minutes": 60, "by_task_type": {}})
        self.mock_pipeline.assert_called_once_with(lookback_minutes=60, task_type=None)

    @patch.object(db, "select")
    def test_summary_truncates_needs_attention_to_worst_three(self, mock_sel):
        # ADDED: the previous file never exercised the rows[:3] slice with more than three rows,
        # so an off-by-one there would have gone unnoticed while every assertion stayed green.
        rows = [{"project": p, "health_score": sc, "blocked": 0, "open_approvals": 0}
                for p, sc in (("a", 10), ("b", 20), ("c", 30), ("d", 40), ("e", 50))]
        mock_sel.side_effect = [rows, []]
        s = health.summary()
        self.assertEqual(s["projects"], 5)
        self.assertEqual([r["project"] for r in s["needs_attention"]], ["a", "b", "c"])
        self.assertAlmostEqual(s["avg_health"], 30.0)

    @patch.object(db, "select")
    def test_summary_empty(self, mock_sel):
        mock_sel.return_value = []
        s = health.summary()
        self.assertEqual(s["projects"], 0)
        # No projects means nothing is unhealthy — the neutral score, not a divide-by-zero.
        self.assertEqual(s["avg_health"], 100)
        self.assertEqual(s["needs_attention"], [])
        self.assertEqual(s["inbox_count"], 0)

    @patch.object(db, "select")
    def test_summary_single_project(self, mock_sel):
        mock_sel.side_effect = [
            [{"project": "solo", "health_score": 55, "blocked": 1, "open_approvals": 5}],
            [],  # empty inbox
        ]
        s = health.summary()
        self.assertEqual(s["projects"], 1)
        self.assertAlmostEqual(s["avg_health"], 55.0)
        self.assertEqual(s["inbox_count"], 0)
        self.assertEqual(s["needs_attention"],
                         [{"project": "solo", "score": 55, "blocked": 1, "approvals": 5}])


class TestPipelineFailSoft(unittest.TestCase):
    def test_test_pipeline_is_fail_soft(self):
        # ADDED: health.test_pipeline() swallows any pipeline_metrics failure and returns a
        # shaped default. Nothing covered that contract, and summary() depends on it to keep
        # returning a dict when the metrics table is missing.
        with patch.object(pipeline_metrics, "get_health", side_effect=RuntimeError("no table")):
            self.assertEqual(health.test_pipeline(lookback_minutes=15),
                             {"lookback_minutes": 15, "by_task_type": {}})


if __name__ == "__main__":
    unittest.main()
