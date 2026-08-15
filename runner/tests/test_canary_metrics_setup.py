#!/usr/bin/env python3
"""The metrics endpoint must actually be started, and only when asked for.

`start_metrics_server()` was implemented, idempotent, fail-soft and covered by 12 tests
in test_canary_metrics_server.py — and called from nowhere. The gauge was updated on
every run and no scraper could read it, because nothing ever bound the port. These tests
pin the wiring itself, which is the part that was missing.

The default must stay OFF: this CLI runs in CI and in the deploy window, where a stray
listener or a port collision with a parallel canary would be a brand-new failure mode for
a tool whose whole purpose is not to be one.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import canary


class TestMetricsServerIsWiredIntoMain(unittest.TestCase):
    def setUp(self):
        # evaluate() would otherwise attempt a real HTTP fetch.
        self._eval = patch.object(canary, "evaluate",
                                  return_value={"verdict": "promote", "reason": "ok"})
        self._eval.start()
        self.addCleanup(self._eval.stop)
        self._print = patch("builtins.print")
        self._print.start()
        self.addCleanup(self._print.stop)

    def test_enabled_starts_the_server(self):
        with patch.object(canary, "start_metrics_server") as start, \
             patch.dict(os.environ, {"CANARY_METRICS_ENABLED": "true"}):
            canary.main([])
        start.assert_called_once()

    def test_disabled_by_default(self):
        with patch.object(canary, "start_metrics_server") as start:
            env = dict(os.environ)
            env.pop("CANARY_METRICS_ENABLED", None)
            with patch.dict(os.environ, env, clear=True):
                canary.main([])
        start.assert_not_called()

    def test_explicit_false_does_not_start(self):
        with patch.object(canary, "start_metrics_server") as start, \
             patch.dict(os.environ, {"CANARY_METRICS_ENABLED": "false"}):
            canary.main([])
        start.assert_not_called()

    def test_flag_parsing_is_forgiving_of_case_and_whitespace(self):
        for value in ("TRUE", " true ", "True"):
            with self.subTest(value=value):
                with patch.object(canary, "start_metrics_server") as start, \
                     patch.dict(os.environ, {"CANARY_METRICS_ENABLED": value}):
                    canary.main([])
                start.assert_called_once()

    def test_a_non_boolean_value_does_not_enable(self):
        # Fail toward the safe default rather than guessing what "yes" meant.
        for value in ("1", "yes", "on", ""):
            with self.subTest(value=value):
                with patch.object(canary, "start_metrics_server") as start, \
                     patch.dict(os.environ, {"CANARY_METRICS_ENABLED": value}):
                    canary.main([])
                start.assert_not_called()

    def test_started_before_evaluate_so_a_slow_run_is_scrapeable(self):
        order = []
        with patch.object(canary, "start_metrics_server",
                          side_effect=lambda: order.append("start")), \
             patch.object(canary, "evaluate",
                          side_effect=lambda *_a, **_k: order.append("evaluate") or
                          {"verdict": "promote", "reason": "ok"}), \
             patch.dict(os.environ, {"CANARY_METRICS_ENABLED": "true"}):
            canary.main([])
        self.assertEqual(order, ["start", "evaluate"])

    def test_a_failed_bind_does_not_break_the_verdict(self):
        # start_metrics_server returns None on a taken port; the canary's exit code is
        # the contract every deploy gate reads and it must not depend on the endpoint.
        with patch.object(canary, "start_metrics_server", return_value=None), \
             patch.dict(os.environ, {"CANARY_METRICS_ENABLED": "true"}):
            self.assertEqual(canary.main([]), 0)

    def test_verdict_exit_codes_are_unchanged_when_enabled(self):
        with patch.object(canary, "start_metrics_server"), \
             patch.object(canary, "evaluate",
                          return_value={"verdict": "rollback", "reason": "bad"}), \
             patch.dict(os.environ, {"CANARY_METRICS_ENABLED": "true"}):
            self.assertEqual(canary.main([]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
