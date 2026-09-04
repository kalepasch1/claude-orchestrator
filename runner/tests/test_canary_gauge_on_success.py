#!/usr/bin/env python3
"""A successful validation must mark the canary as currently succeeding.

Only the `promote` verdict in `main()` ever stamped `canary_last_success`. So
`validate_canary` returning True — the marker demonstrably survived the pipeline hop —
left the gauge reading whatever it read before, and a live success was invisible to the
heartbeat.

ONE DELIBERATE DEVIATION FROM THE LITERAL REQUEST. The task asked for
`canary_last_success.set(1)`. This gauge holds a UNIX TIMESTAMP: `record_success` stamps
`time.time()`, `heartbeat_age` computes `now - last`, and 0 is the documented "not
currently succeeding" sentinel. A literal 1 would make `heartbeat_age` report roughly 56
years of staleness and `heartbeat_expired` return True forever — a successful validation
would read as a dead canary, the exact inversion of what was asked for. The tests below
pin the intent (non-zero, fresh, heartbeat healthy) rather than the literal value.

Proof: python3 -m pytest runner/tests/test_canary_gauge_on_success.py -q
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import canary  # noqa: E402

MARKER_TEXT = "this response contains a canary token"


class _GaugeCase(unittest.TestCase):
    def setUp(self):
        canary.set_gauge("canary_last_success", 0)   # start from "not succeeding"

    def gauge(self):
        return canary.get_gauge("canary_last_success")


class TestValidationSuccessMarksSuccess(_GaugeCase):
    def test_a_successful_validation_sets_the_gauge(self):
        """The acceptance test named by the task, pinned to intent not to a literal."""
        self.assertTrue(canary.validate_canary(MARKER_TEXT))
        self.assertNotEqual(self.gauge(), 0)

    def test_the_gauge_is_a_fresh_timestamp(self):
        before = time.time()
        canary.validate_canary(MARKER_TEXT)
        self.assertGreaterEqual(self.gauge(), before)
        self.assertLessEqual(self.gauge(), time.time())

    def test_it_is_not_the_literal_one(self):
        """A literal 1 would make the heartbeat permanently expired."""
        canary.validate_canary(MARKER_TEXT)
        self.assertGreater(self.gauge(), 1)

    def test_the_heartbeat_reads_healthy_after_a_success(self):
        canary.validate_canary(MARKER_TEXT)
        self.assertFalse(canary.heartbeat_expired())

    def test_the_heartbeat_age_is_near_zero_after_a_success(self):
        canary.validate_canary(MARKER_TEXT)
        age = canary.heartbeat_age()
        self.assertIsNotNone(age)
        self.assertLess(age, 5)

    def test_a_literal_one_would_have_expired_the_heartbeat(self):
        """Documents WHY the literal value was not used, so the deviation is auditable."""
        canary.set_gauge("canary_last_success", 1)
        self.assertTrue(canary.heartbeat_expired())
        self.assertGreater(canary.heartbeat_age(), 10 ** 9)

    def test_repeated_successes_move_the_gauge_forward(self):
        canary.validate_canary(MARKER_TEXT)
        first = self.gauge()
        time.sleep(0.01)
        canary.validate_canary(MARKER_TEXT)
        self.assertGreaterEqual(self.gauge(), first)


class TestFailurePathsAreUnaffected(_GaugeCase):
    def test_a_failed_validation_does_not_mark_success(self):
        canary.set_gauge("canary_last_success", 0)
        self.assertFalse(canary.validate_canary("no marker here"))
        self.assertEqual(self.gauge(), 0)

    def test_a_non_string_input_does_not_mark_success(self):
        canary.set_gauge("canary_last_success", 0)
        self.assertFalse(canary.validate_canary(None))
        self.assertEqual(self.gauge(), 0)

    def test_a_substring_near_miss_does_not_mark_success(self):
        """Word-boundary semantics: "precanaryX" is not a surviving marker."""
        canary.set_gauge("canary_last_success", 0)
        self.assertFalse(canary.validate_canary("precanaryX"))
        self.assertEqual(self.gauge(), 0)

    def test_the_pure_predicate_stays_pure(self):
        """canary_validation owns no gauge; only this module does."""
        import canary_validation
        canary.set_gauge("canary_last_success", 0)
        self.assertTrue(canary_validation.validate_canary(MARKER_TEXT))
        self.assertEqual(self.gauge(), 0)


class TestScraperSeesIt(_GaugeCase):
    def test_the_success_is_visible_in_rendered_metrics(self):
        canary.validate_canary(MARKER_TEXT)
        body = canary.render_metrics()
        text = body.decode() if isinstance(body, bytes) else body
        self.assertIn("canary_last_success", text)
        self.assertNotIn("canary_last_success 0", text)


if __name__ == "__main__":
    unittest.main()
