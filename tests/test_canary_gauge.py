"""canary_last_success gauge: initialized to 0, settable, rendered on /metrics."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))

import canary  # noqa: E402


class CanaryGaugeTest(unittest.TestCase):
    def setUp(self):
        canary.set_gauge("canary_last_success", 0)

    def test_gauge_initialized_to_zero(self):
        self.assertEqual(canary.get_gauge("canary_last_success"), 0.0)

    def test_metrics_endpoint_renders_gauge_in_prometheus_format(self):
        body = canary.render_metrics().decode()
        self.assertIn("canary_up 1", body)
        self.assertIn("# TYPE canary_last_success gauge", body)
        self.assertIn("canary_last_success 0.0", body)

    def test_record_success_moves_the_gauge(self):
        canary.record_success(1754450000.0)
        self.assertEqual(canary.get_gauge("canary_last_success"), 1754450000.0)
        self.assertIn("canary_last_success 1754450000.0", canary.render_metrics().decode())

    def test_bad_values_fail_soft(self):
        canary.set_gauge("canary_last_success", "not-a-number")
        self.assertEqual(canary.get_gauge("canary_last_success"), 0.0)

    def test_gauge_object_is_module_level(self):
        """`canary.canary_last_success` is a Gauge object on the module surface."""
        gauge = canary.canary_last_success
        self.assertIsInstance(gauge, canary.Gauge)
        self.assertEqual(gauge.name, "canary_last_success")
        self.assertEqual(
            gauge.documentation,
            "Indicator of the last validation result (1 for success, 0 for failure)",
        )

    def test_gauge_object_and_helpers_share_state(self):
        canary.canary_last_success.set(42)
        self.assertEqual(canary.get_gauge("canary_last_success"), 42.0)
        canary.set_gauge("canary_last_success", 7)
        self.assertEqual(canary.canary_last_success.get(), 7.0)

    def test_gauge_object_inc_dec_and_fail_soft(self):
        canary.canary_last_success.inc(2.5)
        self.assertEqual(canary.canary_last_success.get(), 2.5)
        canary.canary_last_success.dec(0.5)
        self.assertEqual(canary.canary_last_success.get(), 2.0)
        canary.canary_last_success.inc("nope")
        self.assertEqual(canary.canary_last_success.get(), 2.0)

    def test_help_line_rendered(self):
        body = canary.render_metrics().decode()
        self.assertIn("# HELP canary_last_success Indicator of the last validation", body)

    def test_validate_canary_logs_without_nameerror(self):
        """Regression: `_log` was referenced but never bound (NameError on call)."""
        self.assertTrue(canary.validate_canary("contains a CANARY marker"))
        self.assertFalse(canary.validate_canary("nothing here"))
        self.assertFalse(canary.validate_canary(None))


if __name__ == "__main__":
    unittest.main()
