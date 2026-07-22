import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import portfolio_autopilot


def _make_app(app_id="app-1", name="testapp", enabled=True):
    return {"id": app_id, "name": name, "enabled": enabled}


class TestPortfolioAutopilot(unittest.TestCase):

    def setUp(self):
        self.db = MagicMock()
        self._patch = patch.object(portfolio_autopilot, "db", self.db)
        self._patch.start()
        os.environ["ORCH_PORTFOLIO_AUTOPILOT_ENABLED"] = "true"
        portfolio_autopilot.ENABLED = True

    def tearDown(self):
        self._patch.stop()
        os.environ.pop("ORCH_PORTFOLIO_AUTOPILOT_ENABLED", None)

    # --- Cold-start ---

    def test_cold_starts_app_with_no_active_runs(self):
        app = _make_app()
        # select growth_apps -> one app; select growth_distribution_run -> empty (0 active)
        self.db.select.side_effect = [
            [app],          # _enabled_apps
            [],             # _active_run_count -> 0
            [],             # _signups_per_human_hour
        ]
        self.db.rpc.return_value = "ok"

        # growth_settings select for ceiling
        def select_side(table, params=None):
            if table == "growth_apps":
                return [app]
            if table == "growth_distribution_run":
                return []
            if table == "growth_settings":
                return [{"value": "25"}]
            return []
        self.db.select.side_effect = select_side

        result = portfolio_autopilot.run()

        # cold_start_app should have been called
        rpc_calls = [c for c in self.db.rpc.call_args_list if c[0][0] == "cold_start_app"]
        self.assertEqual(len(rpc_calls), 1)
        self.assertEqual(rpc_calls[0][0][1]["p_app_id"], "app-1")
        self.assertEqual(rpc_calls[0][0][1]["p_count"], 3)
        self.assertEqual(rpc_calls[0][0][1]["p_mode"], "approval")
        self.assertEqual(result["cold_started"], 1)

    def test_skips_cold_start_when_active_runs_exist(self):
        app = _make_app()

        def select_side(table, params=None):
            if table == "growth_apps":
                return [app]
            if table == "growth_distribution_run":
                if params and params.get("status") == "eq.active" and "id" in params.get("select", ""):
                    return [{"id": "run-1"}]  # 1 active run
                return [{"signups": 5, "human_hours": 1}]
            if table == "growth_settings":
                return [{"value": "50"}]
            return []
        self.db.select.side_effect = select_side
        self.db.rpc.return_value = "ok"

        result = portfolio_autopilot.run()
        self.assertEqual(result["cold_started"], 0)

    # --- auto_tune ---

    def test_calls_auto_tune_distribution(self):
        app = _make_app()

        def select_side(table, params=None):
            if table == "growth_apps":
                return [app]
            if table == "growth_distribution_run":
                if params and "id" in params.get("select", ""):
                    return [{"id": "run-1"}]
                return [{"signups": 10, "human_hours": 2}]
            if table == "growth_settings":
                return [{"value": "30"}]
            return []
        self.db.select.side_effect = select_side
        self.db.rpc.return_value = "tuned"

        result = portfolio_autopilot.run()

        tune_calls = [c for c in self.db.rpc.call_args_list if c[0][0] == "auto_tune_distribution"]
        self.assertEqual(len(tune_calls), 1)
        self.assertEqual(tune_calls[0][0][1]["p_ceiling"], 30.0)

    # --- zero signups flagging ---

    def test_flags_apps_with_zero_signups(self):
        app = _make_app()

        def select_side(table, params=None):
            if table == "growth_apps":
                return [app]
            if table == "growth_distribution_run":
                return []  # no runs -> 0 signups
            if table == "growth_settings":
                return [{"value": "50"}]
            return []
        self.db.select.side_effect = select_side
        self.db.rpc.return_value = "ok"

        portfolio_autopilot.run()

        # Check that the digest insert has severity=high
        insert_calls = [c for c in self.db.insert.call_args_list
                        if c[0][0] == "growth_intake_suggestion"]
        self.assertTrue(len(insert_calls) >= 1)
        row = insert_calls[0][0][1]
        self.assertEqual(row["severity"], "high")
        self.assertIn("0 signups", row["detail"])

    # --- stats ---

    def test_stats_output(self):
        app = _make_app()

        def select_side(table, params=None):
            if table == "growth_apps":
                return [app]
            if table == "growth_distribution_run":
                return []
            if table == "growth_settings":
                return [{"value": "42"}]
            return []
        self.db.select.side_effect = select_side

        s = portfolio_autopilot.stats()
        self.assertTrue(s["enabled"])
        self.assertEqual(s["total_apps"], 1)
        self.assertIn("testapp", s["zero_run_apps"])
        self.assertEqual(s["cac_ceiling"], "42")

    def test_disabled_via_env(self):
        portfolio_autopilot.ENABLED = False
        result = portfolio_autopilot.run()
        self.assertEqual(result, {"skipped": True})

        s = portfolio_autopilot.stats()
        self.assertFalse(s["enabled"])


if __name__ == "__main__":
    unittest.main()
