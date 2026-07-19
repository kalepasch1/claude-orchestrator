"""Tests for cross_portfolio_ab — cross-portfolio A/B test compounding."""
import os
import sys
import json
import unittest
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Stub db before importing the module
fake_db = MagicMock()
fake_db.select.return_value = []
fake_db.insert.return_value = [{"id": "exp-1"}]
with patch.dict(sys.modules, {"db": fake_db}):
    import cross_portfolio_ab


def _reset():
    """Reset module counters and db mock between tests."""
    for k in cross_portfolio_ab._counters:
        cross_portfolio_ab._counters[k] = 0
    fake_db.reset_mock()
    fake_db.select.return_value = []
    fake_db.insert.return_value = [{"id": "exp-1"}]


class TestFindWinningTactics(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_finds_winners_above_threshold(self):
        with patch.object(cross_portfolio_ab, "db") as mdb:
            mdb.select.return_value = [
                {"id": "t1", "app_id": "app-a", "tactic_name": "push_upsell",
                 "lift": 0.25, "confidence": 0.98, "status": "completed", "params": {"channel": "push"}},
                {"id": "t2", "app_id": "app-b", "tactic_name": "email_drip",
                 "lift": 0.05, "confidence": 0.99, "status": "completed", "params": {}},
                {"id": "t3", "app_id": "app-c", "tactic_name": "referral_bonus",
                 "lift": 0.15, "confidence": 0.80, "status": "completed", "params": {}},
            ]
            winners = cross_portfolio_ab.find_winning_tactics(min_lift=0.1, min_confidence=0.95)
            self.assertEqual(len(winners), 1)
            self.assertEqual(winners[0]["tactic_name"], "push_upsell")
            self.assertGreaterEqual(winners[0]["lift"], 0.1)
            self.assertGreaterEqual(winners[0]["confidence"], 0.95)

    def test_no_winners_returns_empty(self):
        with patch.object(cross_portfolio_ab, "db") as mdb:
            mdb.select.return_value = [
                {"id": "t1", "app_id": "app-a", "tactic_name": "weak",
                 "lift": 0.01, "confidence": 0.5, "status": "completed", "params": {}},
            ]
            winners = cross_portfolio_ab.find_winning_tactics()
            self.assertEqual(winners, [])


class TestPropagateTactic(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_propagates_to_target_apps(self):
        tactic = {"tactic_id": "t1", "app_id": "app-a", "tactic_name": "push_upsell",
                  "lift": 0.25, "confidence": 0.98, "params": {"channel": "push"}}
        with patch.object(cross_portfolio_ab, "db") as mdb:
            mdb.insert.return_value = [{"id": "exp-100"}]
            result = cross_portfolio_ab.propagate_tactic(tactic, ["app-b", "app-c"])
            self.assertEqual(len(result), 2)
            self.assertEqual(mdb.insert.call_count, 2)
            # Verify experiment shape
            first_call_args = mdb.insert.call_args_list[0]
            self.assertEqual(first_call_args[0][0], "ab_test_framework")
            inserted = first_call_args[0][1]
            self.assertEqual(inserted["app_id"], "app-b")
            self.assertEqual(inserted["origin"], "cross_portfolio_ab")
            self.assertEqual(inserted["status"], "pending")

    def test_skips_apps_already_running(self):
        """propagate_tactic itself doesn't filter; cross_pollinate does the filtering."""
        tactic = {"tactic_id": "t1", "app_id": "app-a", "tactic_name": "push_upsell",
                  "lift": 0.25, "confidence": 0.98, "params": {}}
        with patch.object(cross_portfolio_ab, "db") as mdb:
            mdb.insert.return_value = [{"id": "exp-200"}]
            result = cross_portfolio_ab.propagate_tactic(tactic, ["app-b"])
            self.assertEqual(len(result), 1)


class TestCrossPollinate(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_cross_pollinate_skips_already_running(self):
        """Apps already running the tactic are excluded."""
        with patch.object(cross_portfolio_ab, "db") as mdb:
            def side_effect(table, params=None):
                if table == "growth_distribution_run":
                    return [{"id": "t1", "app_id": "app-a", "tactic_name": "push_upsell",
                             "lift": 0.3, "confidence": 0.99, "status": "completed", "params": {}}]
                if table == "apps":
                    return [{"id": "app-a"}, {"id": "app-b"}, {"id": "app-c"}]
                if table == "ab_test_framework":
                    # app-b already has this tactic
                    return [{"app_id": "app-b"}]
                return []
            mdb.select.side_effect = side_effect
            mdb.insert.return_value = [{"id": "exp-300"}]
            result = cross_portfolio_ab.cross_pollinate()
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["winners"], 1)
            # Only app-c should get the experiment (app-a is source, app-b already running)
            self.assertEqual(result["propagated"], 1)
            self.assertEqual(mdb.insert.call_count, 1)
            inserted_app = mdb.insert.call_args[0][1]["app_id"]
            self.assertEqual(inserted_app, "app-c")

    def test_handles_no_winners_gracefully(self):
        with patch.object(cross_portfolio_ab, "db") as mdb:
            mdb.select.return_value = []
            result = cross_portfolio_ab.cross_pollinate()
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["winners"], 0)
            self.assertEqual(result["propagated"], 0)


class TestStats(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_stats_returns_dict(self):
        result = cross_portfolio_ab.stats()
        self.assertIsInstance(result, dict)
        self.assertIn("module", result)
        self.assertEqual(result["module"], "cross_portfolio_ab")
        self.assertIn("enabled", result)
        self.assertIn("winners_found", result)
        self.assertIn("experiments_created", result)
        self.assertIn("min_lift", result)
        self.assertIn("min_confidence", result)


class TestFeatureFlag(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_disabled_via_env_flag(self):
        original = cross_portfolio_ab.ENABLED
        try:
            cross_portfolio_ab.ENABLED = False
            self.assertEqual(cross_portfolio_ab.find_winning_tactics(), [])
            self.assertEqual(cross_portfolio_ab.propagate_tactic({}, ["app-x"]), [])
            result = cross_portfolio_ab.cross_pollinate()
            self.assertEqual(result["status"], "disabled")
        finally:
            cross_portfolio_ab.ENABLED = original


if __name__ == "__main__":
    unittest.main()
