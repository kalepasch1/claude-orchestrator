"""A failing canary must clear canary_last_success, not leave the old timestamp.

Only the promote path wrote the gauge. After a rollback it still held the
timestamp of the *previous* success, so an alert phrased as
`time() - canary_last_success > threshold` read as healthy while the canary was
actively rolling back. These tests pin the zeroing contract and the main() wiring.
"""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
)

import canary  # noqa: E402


class CanaryFailureGaugeTest(unittest.TestCase):
    def setUp(self):
        canary.set_gauge("canary_last_success", 0)

    def tearDown(self):
        canary.set_gauge("canary_last_success", 0)

    # --- record_failure ---------------------------------------------------

    def test_record_failure_zeroes_a_previous_success(self):
        canary.record_success(1754450000.0)
        self.assertEqual(canary.get_gauge("canary_last_success"), 1754450000.0)

        canary.record_failure()

        self.assertEqual(canary.get_gauge("canary_last_success"), 0.0)

    def test_record_failure_is_idempotent(self):
        canary.record_failure()
        canary.record_failure()
        self.assertEqual(canary.get_gauge("canary_last_success"), 0.0)

    def test_zeroed_gauge_is_rendered_on_metrics(self):
        canary.record_success(1754450000.0)
        canary.record_failure()
        body = canary.render_metrics().decode()
        self.assertIn("# TYPE canary_last_success gauge", body)
        self.assertIn("canary_last_success 0.0", body)
        self.assertNotIn("1754450000.0", body)

    def test_a_later_success_still_moves_the_gauge_forward(self):
        canary.record_failure()
        canary.record_success(1754460000.0)
        self.assertEqual(canary.get_gauge("canary_last_success"), 1754460000.0)

    # --- main() wiring ----------------------------------------------------

    def _main(self, verdict, reason="test"):
        original = canary.evaluate
        canary.evaluate = lambda *a, **k: {"verdict": verdict, "reason": reason}
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = canary.main([])
            return rc, json.loads(buf.getvalue())
        finally:
            canary.evaluate = original

    def test_main_zeroes_the_gauge_on_rollback(self):
        canary.record_success(1754450000.0)

        rc, result = self._main("rollback", "error_rate=0.4 breaches max 0.1")

        self.assertEqual(rc, 1)
        self.assertEqual(result["verdict"], "rollback")
        self.assertEqual(canary.get_gauge("canary_last_success"), 0.0)

    def test_main_sets_the_gauge_on_promote(self):
        rc, result = self._main("promote", "all metrics within thresholds")

        self.assertEqual(rc, 0)
        self.assertGreater(canary.get_gauge("canary_last_success"), 0.0)

    def test_main_zeroes_the_gauge_for_an_unknown_verdict(self):
        """Anything that is not an explicit promote is a failure."""
        canary.record_success(1754450000.0)
        self._main("unreachable")
        self.assertEqual(canary.get_gauge("canary_last_success"), 0.0)


if __name__ == "__main__":
    unittest.main()
