import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import portfolio_autopilot


#: growth_apps as it REALLY is: keyed on `app` (text), labelled by `display_name`.
#: There is no `id` and no `name` column. These tests previously built {"id","name"} rows
#: against a MagicMock that accepts any column, so they stayed green for months while the
#: nightly job died with KeyError: 'id' on its very first row. Asserting the real schema is
#: the only version of this file that can detect that.
def _make_app(app="testapp", display_name="Testapp", enabled=True):
    return {"app": app, "display_name": display_name, "enabled": enabled}


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
        # Real signature: cold_start_app(p_app text, p_n integer, p_mode text).
        # The old assertions demanded p_app_id/p_count, which cannot bind.
        rpc_calls = [c for c in self.db.rpc.call_args_list if c[0][0] == "cold_start_app"]
        self.assertEqual(len(rpc_calls), 1)
        self.assertEqual(rpc_calls[0][0][1]["p_app"], "testapp")
        self.assertEqual(rpc_calls[0][0][1]["p_n"], 3)
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

        # Real signature: auto_tune_distribution(p_cac_ceiling numeric). p_ceiling never bound.
        tune_calls = [c for c in self.db.rpc.call_args_list if c[0][0] == "auto_tune_distribution"]
        self.assertEqual(len(tune_calls), 1)
        self.assertEqual(tune_calls[0][0][1]["p_cac_ceiling"], 30.0)

    # --- zero signups flagging ---

    def test_flags_apps_with_zero_signups(self):
        """A real 0 signups against real recorded human effort must escalate.

        Rewritten: the old version passed NO runs at all and demanded severity=high, which
        conflated "no data" with "zero signups". Since every app had no measurable runs,
        every app was permanently high-severity and the flag carried no information.
        Signups live in growth_distribution_metric and human effort in
        growth_distribution_play.human_minutes — neither is a column on the run table.
        """
        app = _make_app()

        def select_side(table, params=None):
            if table == "growth_apps":
                return [app]
            if table == "growth_distribution_run":
                return [{"id": "run-1", "play_id": "play-1"}]
            if table == "growth_distribution_play":
                return [{"human_minutes": 90}]          # real effort was spent
            if table == "growth_distribution_metric":
                return [{"signups": 0}]                 # and it produced nothing
            if table == "growth_settings":
                return [{"value": "50"}]
            return []
        self.db.select.side_effect = select_side
        self.db.rpc.return_value = "ok"

        portfolio_autopilot.run()

        insert_calls = [c for c in self.db.insert.call_args_list
                        if c[0][0] == "growth_intake_suggestion"]
        self.assertTrue(len(insert_calls) >= 1)
        row = insert_calls[0][0][1]
        self.assertEqual(row["severity"], "high")
        self.assertIn("0 signups", row["detail"])
        # growth_intake_suggestion is keyed on `app`; app_id/app_name do not exist there.
        self.assertEqual(row["app"], "testapp")
        self.assertNotIn("app_id", row)

    def test_no_runs_is_unknown_not_a_zero_signup_alarm(self):
        """The companion case the old test was accidentally asserting."""
        app = _make_app()

        def select_side(table, params=None):
            if table == "growth_apps":
                return [app]
            if table == "growth_settings":
                return [{"value": "50"}]
            return []
        self.db.select.side_effect = select_side
        self.db.rpc.return_value = "ok"

        portfolio_autopilot.run()

        row = [c for c in self.db.insert.call_args_list
               if c[0][0] == "growth_intake_suggestion"][0][0][1]
        self.assertEqual(row["severity"], "low")
        self.assertIn("unknown", row["detail"])

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
        # zero_run_apps is a human-facing list, so it carries display_name ("Testapp"),
        # not the `app` key. Previously it emitted app["name"], a column that never existed.
        self.assertIn("Testapp", s["zero_run_apps"])
        self.assertEqual(s["cac_ceiling"], "42")

    def test_disabled_via_env(self):
        portfolio_autopilot.ENABLED = False
        result = portfolio_autopilot.run()
        self.assertEqual(result, {"skipped": True})

        s = portfolio_autopilot.stats()
        self.assertFalse(s["enabled"])


if __name__ == "__main__":
    unittest.main()
