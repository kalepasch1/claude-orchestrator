#!/usr/bin/env python3
"""Tests for portfolio_ab_analytics — mock A/B results in 3 apps, verify aggregation."""
import sys, os, unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MOCK_EXPERIMENTS = [
    {"id": "exp-1", "tactic": "model-routing", "project": "app-alpha", "status": "completed"},
    {"id": "exp-2", "tactic": "model-routing", "project": "app-beta", "status": "completed"},
    {"id": "exp-3", "tactic": "model-routing", "project": "app-gamma", "status": "active"},
]

MOCK_OUTCOMES = [
    # exp-1: control 60% success, variant 72% → lift 0.20
    *[{"experiment_id": "exp-1", "variant": "control", "success": i < 6} for i in range(10)],
    *[{"experiment_id": "exp-1", "variant": "candidate", "success": i < 9} for i in range(10)],
    # exp-2: control 50%, variant 65% → lift 0.30
    *[{"experiment_id": "exp-2", "variant": "control", "success": i < 5} for i in range(10)],
    *[{"experiment_id": "exp-2", "variant": "candidate", "success": i < 7} for i in range(10)],
    # exp-3: control 80%, variant 60% → negative lift
    *[{"experiment_id": "exp-3", "variant": "control", "success": i < 8} for i in range(10)],
    *[{"experiment_id": "exp-3", "variant": "candidate", "success": i < 6} for i in range(10)],
]


def _mock_select(table, params=None):
    if table == "experiments":
        return MOCK_EXPERIMENTS
    if table == "outcomes":
        return MOCK_OUTCOMES
    return []


class TestPortfolioAbAnalytics(unittest.TestCase):

    @patch("db.select", side_effect=_mock_select)
    def test_aggregation_groups_by_tactic(self, _):
        from portfolio_ab_analytics import aggregate_ab_results
        result = aggregate_ab_results()
        self.assertIn("model-routing", result)
        self.assertEqual(result["model-routing"]["app_count"], 3)

    @patch("db.select", side_effect=_mock_select)
    def test_per_app_lift_computed(self, _):
        from portfolio_ab_analytics import aggregate_ab_results
        result = aggregate_ab_results()
        apps = {e["app"]: e for e in result["model-routing"]["per_app"]}
        # app-alpha: 60%→90% = lift 0.5
        self.assertGreater(apps["app-alpha"]["lift"], 0)
        # app-gamma: 80%→60% = negative lift
        self.assertLess(apps["app-gamma"]["lift"], 0)

    @patch("db.select", side_effect=_mock_select)
    def test_portfolio_average_lift(self, _):
        from portfolio_ab_analytics import aggregate_ab_results
        result = aggregate_ab_results()
        avg = result["model-routing"]["portfolio_avg_lift"]
        # Average of positive and negative lifts across 3 apps
        self.assertIsInstance(avg, float)

    @patch("db.select", side_effect=_mock_select)
    def test_tactic_filter(self, _):
        from portfolio_ab_analytics import aggregate_ab_results
        result = aggregate_ab_results(tactic_filter="nonexistent")
        self.assertEqual(len(result), 0)

    @patch("db.select", side_effect=_mock_select)
    def test_p_values_present(self, _):
        from portfolio_ab_analytics import aggregate_ab_results
        result = aggregate_ab_results()
        for entry in result["model-routing"]["per_app"]:
            self.assertIn("p_value", entry)
            self.assertGreaterEqual(entry["p_value"], 0)
            self.assertLessEqual(entry["p_value"], 1)


if __name__ == "__main__":
    unittest.main()
