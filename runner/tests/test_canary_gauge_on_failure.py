#!/usr/bin/env python3
"""`canary_last_success` must read 0 on every failure path, not just on rollback.

The gauge's documented contract is that 0 means "not currently succeeding", and alerts
are written as `time() - canary_last_success > threshold`. `record_failure()` already
existed and the rollback verdict already called it — but two failure paths did not, and
on both of them the gauge kept the timestamp of the LAST SUCCESS, so the alert read green
while the canary was failing:

* VALIDATION FAILURE — `validate_canary` returning False means the marker did not survive
  the pipeline hop. It logged a warning and left the gauge alone.
* EXCEPTION — `evaluate()` returns a rollback verdict for failures it anticipates;
  anything it did not anticipate propagated straight out of `main()`, so the gauge was
  never touched at all while the canary was crashing.

Acceptance (from the task): trigger a validation failure and assert the gauge is 0.

Proof: python3 -m pytest runner/tests/test_canary_gauge_on_failure.py -q
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import canary  # noqa: E402


class _GaugeCase(unittest.TestCase):
    def setUp(self):
        canary.record_success(1_700_000_000.0)   # a known, non-zero "last success"
        self.assertEqual(canary.get_gauge("canary_last_success"), 1_700_000_000.0)

    def gauge(self):
        return canary.get_gauge("canary_last_success")


class TestValidationFailureZeroesTheGauge(_GaugeCase):
    def test_a_missing_marker_sets_the_gauge_to_zero(self):
        """The acceptance test named by the task."""
        self.assertFalse(canary.validate_canary("no marker in this response"))
        self.assertEqual(self.gauge(), 0)

    def test_a_non_string_input_sets_the_gauge_to_zero(self):
        self.assertFalse(canary.validate_canary(None))
        self.assertEqual(self.gauge(), 0)

    def test_an_empty_response_sets_the_gauge_to_zero(self):
        self.assertFalse(canary.validate_canary(""))
        self.assertEqual(self.gauge(), 0)

    def test_a_successful_validation_leaves_the_gauge_alone(self):
        self.assertTrue(canary.validate_canary("this response contains a canary token"))
        self.assertEqual(self.gauge(), 1_700_000_000.0)

    def test_a_substring_near_miss_is_still_a_failure(self):
        """Word-boundary matching is the unified semantics; "precanary" must not pass."""
        self.assertFalse(canary.validate_canary("precanaryX"))
        self.assertEqual(self.gauge(), 0)

    def test_the_pure_predicate_stays_pure(self):
        """canary_validation owns no gauge; only this module does."""
        import canary_validation
        canary_validation.validate_canary("nothing here")
        self.assertEqual(self.gauge(), 1_700_000_000.0)


class TestExceptionPathZeroesTheGauge(_GaugeCase):
    def test_a_raising_evaluate_zeroes_the_gauge(self):
        with patch.object(canary, "evaluate", side_effect=RuntimeError("boom")):
            code = canary.main(["http://metrics.invalid"])
        self.assertEqual(code, 1)
        self.assertEqual(self.gauge(), 0)

    def test_a_raising_evaluate_does_not_propagate(self):
        with patch.object(canary, "evaluate", side_effect=RuntimeError("boom")):
            canary.main([])  # must not raise

    def test_a_raising_evaluate_forces_a_rollback_verdict(self):
        with patch.object(canary, "evaluate", side_effect=RuntimeError("boom")):
            code = canary.main([])
        self.assertEqual(code, 1, "a crashed canary must not be treated as promotable")

    def test_a_rollback_verdict_still_zeroes_the_gauge(self):
        with patch.object(canary, "evaluate",
                          return_value={"verdict": "rollback", "reason": "error_rate"}):
            code = canary.main([])
        self.assertEqual(code, 1)
        self.assertEqual(self.gauge(), 0)

    def test_a_promote_verdict_stamps_a_fresh_success(self):
        with patch.object(canary, "evaluate",
                          return_value={"verdict": "promote", "reason": "ok"}):
            code = canary.main([])
        self.assertEqual(code, 0)
        self.assertGreater(self.gauge(), 1_700_000_000.0)


class TestHeartbeatReadsTheZero(_GaugeCase):
    def test_zero_means_never_currently_succeeding(self):
        canary.validate_canary("no marker")
        self.assertIsNone(canary.heartbeat_age(),
                          "0 must read as 'no current success', not as epoch 0")

    def test_a_zeroed_gauge_reports_the_heartbeat_expired(self):
        canary.validate_canary("no marker")
        self.assertTrue(canary.heartbeat_expired())

    def test_a_fresh_success_is_not_expired(self):
        canary.record_success()
        self.assertFalse(canary.heartbeat_expired())


class TestRenderedMetrics(_GaugeCase):
    def test_the_zero_is_visible_to_a_scraper(self):
        canary.validate_canary("no marker")
        body = canary.render_metrics()
        # render_metrics returns bytes (it is served straight down the wire).
        text = body.decode() if isinstance(body, bytes) else body
        self.assertIn("canary_last_success", text)
        self.assertIn("canary_last_success 0", text)


if __name__ == "__main__":
    unittest.main()
