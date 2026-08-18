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


if __name__ == "__main__":
    unittest.main()
