#!/usr/bin/env python3
"""canary heartbeat expiry detection.

`canary_last_success` was write-only: record_success() stamped it, record_failure() zeroed
it, and nothing ever read it back. A canary that stopped evaluating altogether — crashed
thread, wedged deploy window, sleeping host — therefore kept serving whatever timestamp it
last wrote, and looked identical on /metrics to one that was healthy. Staleness was left to
an external alert nobody had written.

These tests pin the read side: a stale heartbeat, and a heartbeat that never started, are
both detected, and the verdict reaches both /metrics and the CLI.
"""
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import canary  # noqa: E402


class HeartbeatExpiryTest(unittest.TestCase):
    def setUp(self):
        canary.set_gauge("canary_last_success", 0)
        self.addCleanup(canary.set_gauge, "canary_last_success", 0)

    def test_a_heartbeat_that_never_beat_is_expired(self):
        # The case nobody notices: a canary that dies before its first success.
        self.assertIsNone(canary.heartbeat_age())
        self.assertTrue(canary.heartbeat_expired())

    def test_a_fresh_heartbeat_is_not_expired(self):
        canary.record_success()
        self.assertFalse(canary.heartbeat_expired())
        self.assertLess(canary.heartbeat_age(), 5)

    def test_a_stale_heartbeat_is_expired(self):
        canary.record_success(ts=1000.0)
        self.assertTrue(canary.heartbeat_expired(now=1000.0 + 301))

    def test_the_boundary_is_exclusive(self):
        canary.record_success(ts=1000.0)
        self.assertFalse(canary.heartbeat_expired(now=1000.0 + 300),
                         "exactly at the limit is still alive")
        self.assertTrue(canary.heartbeat_expired(now=1000.0 + 300.001))

    def test_a_recorded_failure_reads_as_expired(self):
        # record_failure() zeroes the gauge, and 0 means "not currently succeeding".
        canary.record_success()
        canary.record_failure()
        self.assertTrue(canary.heartbeat_expired())

    def test_a_clock_that_went_backwards_is_not_a_negative_age(self):
        canary.record_success(ts=2000.0)
        self.assertEqual(canary.heartbeat_age(now=1000.0), 0.0)
        self.assertFalse(canary.heartbeat_expired(now=1000.0))

    def test_the_max_age_is_configurable(self):
        canary.record_success(ts=1000.0)
        with patch.dict(os.environ, {"CANARY_HEARTBEAT_MAX_AGE_S": "10"}):
            self.assertTrue(canary.heartbeat_expired(now=1011.0))
        with patch.dict(os.environ, {"CANARY_HEARTBEAT_MAX_AGE_S": "3600"}):
            self.assertFalse(canary.heartbeat_expired(now=1011.0))

    def test_a_junk_or_zero_max_age_falls_back_to_the_default(self):
        canary.record_success(ts=1000.0)
        for bad in ("not-a-number", "0", "-5", ""):
            with self.subTest(value=bad), patch.dict(os.environ,
                                                     {"CANARY_HEARTBEAT_MAX_AGE_S": bad}):
                self.assertFalse(canary.heartbeat_expired(now=1100.0))
                self.assertTrue(canary.heartbeat_expired(now=1400.0))

    def test_an_explicit_max_age_argument_wins_over_the_env(self):
        canary.record_success(ts=1000.0)
        with patch.dict(os.environ, {"CANARY_HEARTBEAT_MAX_AGE_S": "3600"}):
            self.assertTrue(canary.heartbeat_expired(now=1050.0, max_age=10))


class HeartbeatStatusTest(unittest.TestCase):
    def setUp(self):
        canary.set_gauge("canary_last_success", 0)
        self.addCleanup(canary.set_gauge, "canary_last_success", 0)

    def test_status_distinguishes_never_beat_from_stale(self):
        never = canary.heartbeat_status()
        self.assertTrue(never["expired"])
        self.assertIsNone(never["age_s"], "never-beat must not report an age of 0")
        self.assertIn("no successful canary evaluation", never["reason"])

        canary.record_success(ts=1000.0)
        stale = canary.heartbeat_status(now=1000.0 + 400)
        self.assertTrue(stale["expired"])
        self.assertEqual(stale["age_s"], 400.0)

    def test_status_is_json_serialisable(self):
        canary.record_success()
        json.dumps(canary.heartbeat_status())  # must not raise


class HeartbeatMetricsTest(unittest.TestCase):
    def setUp(self):
        canary.set_gauge("canary_last_success", 0)
        self.addCleanup(canary.set_gauge, "canary_last_success", 0)

    def test_metrics_expose_the_expiry_verdict(self):
        body = canary.render_metrics().decode()
        self.assertIn("canary_heartbeat_expired 1", body)

        canary.record_success()
        self.assertIn("canary_heartbeat_expired 0", canary.render_metrics().decode())

    def test_the_verdict_is_recomputed_at_scrape_time(self):
        # A gauge only written on state change would report 0 forever for exactly the
        # failure this exists to catch: a canary that has stopped writing anything at all.
        canary.record_success(ts=1000.0)
        with patch.object(canary.time, "time", return_value=1000.0 + 10):
            self.assertIn("canary_heartbeat_expired 0", canary.render_metrics().decode())
        # Nothing has been written since — only the clock moved.
        with patch.object(canary.time, "time", return_value=1000.0 + 9999):
            self.assertIn("canary_heartbeat_expired 1", canary.render_metrics().decode())

    def test_metrics_still_render_the_existing_gauges(self):
        body = canary.render_metrics().decode()
        self.assertIn("canary_up 1", body)
        self.assertIn("canary_last_success", body)


class HeartbeatCliTest(unittest.TestCase):
    def setUp(self):
        canary.set_gauge("canary_last_success", 0)
        self.addCleanup(canary.set_gauge, "canary_last_success", 0)

    def test_heartbeat_flag_exits_nonzero_when_expired(self):
        self.assertEqual(canary.main(["--heartbeat"]), 1)

    def test_heartbeat_flag_exits_zero_when_current(self):
        canary.record_success()
        self.assertEqual(canary.main(["--heartbeat"]), 0)

    def test_heartbeat_flag_does_not_run_an_evaluation(self):
        # Checking whether the canary is alive must not require the canary to work.
        canary.record_success()
        with patch.object(canary, "evaluate",
                          side_effect=AssertionError("evaluate must not be called")):
            self.assertEqual(canary.main(["--heartbeat"]), 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
