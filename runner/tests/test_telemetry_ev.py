"""
test_telemetry_ev.py - telemetry_ingest + ev_scheduler app_signals integration.

Tests:
  - score shifts with synthetic signals (error spike boosts fix tasks, usage boosts features)
  - neutrality on absence (missing signals don't change score)
  - collect() returns proper shape
  - fail-soft on db errors
"""
import os, sys, json, unittest
from unittest.mock import patch, MagicMock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ev_scheduler
import telemetry_ingest


def _ctx(**over):
    ctx = {"revenue_by_project": {"payapp": 900.0},
           "surface_returns": {},
           "outcome_stats": {"payapp": {"success_rate": 0.8, "avg_usd": 0.5}},
           "approved_slugs": set(),
           "app_signals": {}}
    ctx.update(over)
    return ctx


def _task(**over):
    t = {"id": "t1", "project": "payapp", "kind": "bugfix", "prompt": "fix crash",
         "slug": "fix-crash", "transient_retries": 0, "attempt": 0}
    t.update(over)
    return t


class TestScoreWithSignals(unittest.TestCase):

    def test_neutral_on_absence(self):
        """Missing app_signals should not change score vs empty signals."""
        no_signals = ev_scheduler.score(_task(), _ctx())
        empty_signals = ev_scheduler.score(_task(), _ctx(app_signals={}))
        self.assertEqual(no_signals, empty_signals)

    def test_neutral_on_zero_signals(self):
        """Zero-valued signals should not change score."""
        base = ev_scheduler.score(_task(), _ctx())
        zero = ev_scheduler.score(_task(), _ctx(app_signals={
            "payapp": {"usage_trend": 0.0, "error_rate": 0.0, "cost_burn": 0.0}
        }))
        self.assertEqual(base, zero)

    def test_error_spike_boosts_fix(self):
        """High error_rate should boost bugfix tasks."""
        base = ev_scheduler.score(_task(kind="bugfix"), _ctx())
        boosted = ev_scheduler.score(_task(kind="bugfix"), _ctx(app_signals={
            "payapp": {"error_rate": 0.8, "usage_trend": 0.0, "cost_burn": 0.0}
        }))
        self.assertGreater(boosted, base)

    def test_usage_boosts_feature(self):
        """Rising usage should boost build/feature tasks."""
        base = ev_scheduler.score(_task(kind="build"), _ctx())
        boosted = ev_scheduler.score(_task(kind="build"), _ctx(app_signals={
            "payapp": {"error_rate": 0.0, "usage_trend": 0.8, "cost_burn": 0.0}
        }))
        self.assertGreater(boosted, base)

    def test_dead_app_sinks(self):
        """Declining usage with no errors should deprioritize."""
        base = ev_scheduler.score(_task(kind="build"), _ctx())
        sunk = ev_scheduler.score(_task(kind="build"), _ctx(app_signals={
            "payapp": {"error_rate": 0.0, "usage_trend": -0.8, "cost_burn": 0.0}
        }))
        self.assertLess(sunk, base)

    def test_error_does_not_boost_docs(self):
        """Error spikes should not boost non-fix task kinds."""
        base = ev_scheduler.score(_task(kind="docs"), _ctx())
        same = ev_scheduler.score(_task(kind="docs"), _ctx(app_signals={
            "payapp": {"error_rate": 0.9, "usage_trend": 0.0, "cost_burn": 0.0}
        }))
        self.assertEqual(base, same)


class TestCollect(unittest.TestCase):

    @patch("telemetry_ingest.db")
    @patch("telemetry_ingest.subprocess")
    def test_collect_shape(self, mock_sub, mock_db):
        """collect() returns dict of {project: {usage_trend, error_rate, cost_burn}}."""
        mock_db.select.return_value = [
            {"project": "app1", "metric": "active_users", "value": 200}
        ]
        mock_sub.run.return_value = MagicMock(returncode=1, stdout="")
        # First call = deploy health (empty), second = app_metrics, third = ai_call_costs
        mock_db.select.side_effect = [
            [],  # deploy health
            [{"project": "app1", "metric": "active_users", "value": 200}],
            [{"project": "app1", "cost_usd": 1.5}],
        ]
        result = telemetry_ingest.collect()
        self.assertIn("app1", result)
        self.assertIn("usage_trend", result["app1"])
        self.assertIn("error_rate", result["app1"])
        self.assertIn("cost_burn", result["app1"])

    @patch("telemetry_ingest.db")
    @patch("telemetry_ingest.subprocess")
    def test_collect_failsoft(self, mock_sub, mock_db):
        """collect() returns {} when all sources fail."""
        mock_db.select.side_effect = Exception("db down")
        mock_sub.run.side_effect = Exception("no vercel")
        result = telemetry_ingest.collect()
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
