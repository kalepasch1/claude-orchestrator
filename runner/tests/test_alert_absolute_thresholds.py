#!/usr/bin/env python3
"""Integration-throughput alerting must be ABSOLUTE, not a derivative.

The 2026-08-08 outage, measured: merges per day were 234 (Aug 5), 246 (Aug 6),
45 (Aug 7), 4 (Aug 8). A 60x collapse; the fleet shipped essentially nothing for ~36h
and nothing responded automatically. Two independent causes:

  * the repair loop fires a playbook only when a KPI is >2x worse than the PREVIOUS
    run — a derivative test. Its own stored baseline moved merged_24h 15 -> 9, a ratio
    of 1.667, safely under the 2x bar, while the real LEVEL was in free fall;
  * the one absolute rule, `low_merge_rate`, fired at `< 5` with severity "info". Aug 7
    tripped nothing; Aug 8 produced an "info".

These tests replay that exact series. The headline case is
`test_gradual_collapse_never_trips_a_2x_derivative_test`, which demonstrates the blind
spot arithmetically and then shows the level rules catching the same series.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import alert_rules_engine as engine

# The measured series, in order.
OUTAGE_SERIES = [234, 246, 45, 4]


def fire(metrics):
    """Evaluate with clean state; return {rule_id: severity} for newly-firing alerts."""
    engine._STATE["firing"] = {}
    events = engine.evaluate(rules=engine.DEFAULT_RULES, metrics=metrics)
    return {e["rule_id"]: e.get("severity") for e in events if e["event"] == "firing"}


class TestDerivativeTestIsBlind(unittest.TestCase):
    def test_gradual_collapse_never_trips_a_2x_derivative_test(self):
        """Why a level test is required at all.

        Not one step-over-step ratio in a 234 -> 4 collapse reaches 2x if the decline is
        even slightly smoothed — and the loop compared against its own 2-hourly stored
        baseline, which is smoother still. A test that only sees the slope cannot see a
        cliff you walk down.
        """
        smooth = [234, 200, 150, 110, 80, 60, 45, 30, 20, 12, 7, 4]
        worst_ratio = max(smooth[i] / smooth[i + 1] for i in range(len(smooth) - 1))
        self.assertLess(worst_ratio, 2.0,
                        "series was chosen to stay under a 2x derivative bar")
        # Same series, absolute rules: the collapse is caught.
        self.assertIn("merge_throughput_degraded", fire({"merge_rate_24h": smooth[6]}))
        self.assertIn("merge_throughput_collapsed", fire({"merge_rate_24h": smooth[-1]}))


class TestOutageSeriesNowAlerts(unittest.TestCase):
    def test_healthy_days_are_quiet(self):
        for merges in (234, 246):
            with self.subTest(merges=merges):
                fired = fire({"merge_rate_24h": merges, "merge_rate_1h": 8})
                self.assertNotIn("merge_throughput_degraded", fired)
                self.assertNotIn("merge_throughput_collapsed", fired)

    def test_aug_7_now_fires_a_day_before_zero(self):
        # 45 merges. Previously silent — this is the whole point: warn while there is
        # still a day left to act.
        self.assertIn("merge_throughput_degraded", fire({"merge_rate_24h": 45}))

    def test_aug_8_is_critical_not_info(self):
        fired = fire({"merge_rate_24h": 4})
        self.assertEqual(fired.get("merge_throughput_collapsed"), "critical")

    def test_hourly_stall_is_caught_without_waiting_for_the_24h_window(self):
        # The outage ran 7.5h at zero while merge_rate_24h still read healthy.
        fired = fire({"merge_rate_24h": 120, "merge_rate_1h": 0})
        self.assertEqual(fired.get("merge_stall_1h"), "critical")

    def test_the_ladder_escalates_rather_than_replacing(self):
        # A total collapse must trip BOTH levels, so severity routing sees the worst one.
        fired = fire({"merge_rate_24h": 0, "merge_rate_1h": 0})
        self.assertIn("merge_throughput_degraded", fired)
        self.assertIn("merge_throughput_collapsed", fired)
        self.assertIn("merge_stall_1h", fired)

    def test_severity_matches_the_stakes(self):
        severities = {r["id"]: r["severity"] for r in engine.DEFAULT_RULES}
        self.assertEqual(severities["merge_throughput_collapsed"], "critical")
        self.assertEqual(severities["merge_stall_1h"], "critical")
        # "the fleet ships nothing" must not rank below queue depth.
        self.assertNotEqual(severities["merge_throughput_collapsed"], "info")


class TestRuleSetIntegrity(unittest.TestCase):
    def test_thresholds_form_a_ladder(self):
        by_id = {r["id"]: r for r in engine.DEFAULT_RULES}
        self.assertLess(by_id["merge_throughput_collapsed"]["threshold"],
                        by_id["merge_throughput_degraded"]["threshold"])

    def test_rule_ids_are_unique(self):
        ids = [r["id"] for r in engine.DEFAULT_RULES]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_rule_metric_is_actually_collected(self):
        # A rule on a metric nobody produces is silently skipped by evaluate(): the
        # `value is None -> continue` branch. It looks configured and never fires.
        import inspect
        source = inspect.getsource(engine._collect_metrics)
        for rule in engine.DEFAULT_RULES:
            with self.subTest(rule=rule["id"]):
                self.assertIn(f'metrics["{rule["metric"]}"]', source,
                              f'{rule["id"]} watches an uncollected metric')


class TestCollectionFailureIsLoud(unittest.TestCase):
    def test_a_broken_control_plane_does_not_read_as_health(self):
        """A quiet board must never be the same signal as a healthy board.

        With metrics empty, every `lt` rule evaluates None, `_compare` returns False,
        and nothing fires — a perfectly calm dashboard at the exact moment the control
        plane is unreachable. The collector must record that it failed.
        """
        import io
        import contextlib

        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) \
            else __builtins__.__import__

        def boom(name, *args, **kwargs):
            if name == "db":
                raise RuntimeError("control plane unreachable")
            return real_import(name, *args, **kwargs)

        stderr = io.StringIO()
        if isinstance(__builtins__, dict):
            __builtins__["__import__"] = boom
        else:
            __builtins__.__import__ = boom
        try:
            with contextlib.redirect_stderr(stderr):
                metrics = engine._collect_metrics()
        finally:
            if isinstance(__builtins__, dict):
                __builtins__["__import__"] = real_import
            else:
                __builtins__.__import__ = real_import

        self.assertIn("_collection_error", metrics)
        self.assertIn("FAILED", stderr.getvalue())

    def test_partial_metrics_still_evaluate_the_rules_that_have_data(self):
        # Fail-soft: a missing metric must not suppress the ones that were collected.
        fired = fire({"merge_rate_24h": 4})
        self.assertIn("merge_throughput_collapsed", fired)


if __name__ == "__main__":
    unittest.main(verbosity=2)
