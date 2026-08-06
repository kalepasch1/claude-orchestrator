#!/usr/bin/env python3
"""Acceptance for the canary_last_success gauge.

The stated acceptance is `canary.canary_last_success` exists at module level and
behaves as a Prometheus Gauge. The constraint the first attempt at this tripped on:
prometheus_client is not installed here and the repo ships no dependency manifest,
while canary.py is imported by the scheduler — so a hard import would trade a
missing metric for an unimportable module. These tests therefore pin the contract
that actually matters (the gauge exists, tracks verdicts, and is exposed on
/metrics) under BOTH environments, rather than pinning the import itself.
"""
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import canary  # noqa: E402


class TestGaugeExists(unittest.TestCase):
    def test_gauge_is_module_level(self):
        self.assertTrue(hasattr(canary, "canary_last_success"))

    def test_gauge_has_documented_description(self):
        self.assertEqual(
            canary._GAUGE_DOC,
            "Indicator of the last validation result (1 for success, 0 for failure)")

    def test_gauge_name(self):
        self.assertEqual(canary._GAUGE_NAME, "canary_last_success")

    def test_gauge_exposes_the_prometheus_surface(self):
        g = canary.canary_last_success
        for method in ("set", "inc", "dec"):
            self.assertTrue(callable(getattr(g, method, None)), f"missing {method}()")

    def test_real_gauge_used_when_client_available(self):
        if not canary.PROMETHEUS_AVAILABLE:
            self.skipTest("prometheus_client not installed in this environment")
        from prometheus_client import Gauge
        self.assertIsInstance(canary.canary_last_success, Gauge)

    def test_import_survives_without_prometheus_client(self):
        # The whole point: absence of the optional dep must not break the module.
        self.assertIsNotNone(canary.canary_last_success)
        self.assertIn(canary.PROMETHEUS_AVAILABLE, (True, False))


def _gauge_value():
    g = canary.canary_last_success
    if hasattr(g, "get"):
        return g.get()
    return g._value.get()  # prometheus_client Gauge internal


class TestVerdictRecording(unittest.TestCase):
    def test_promote_sets_one(self):
        canary._record_verdict("rollback")
        with patch.dict(os.environ, {}, clear=True):
            r = canary.evaluate(None)
        self.assertEqual(r["verdict"], "promote")
        self.assertEqual(_gauge_value(), 1)

    def test_rollback_sets_zero(self):
        canary._record_verdict("promote")
        with patch.dict(os.environ, {"CANARY_FETCH_RETRIES": "0"}, clear=True):
            r = canary.evaluate("http://127.0.0.1:9/never")
        self.assertEqual(r["verdict"], "rollback")
        self.assertEqual(_gauge_value(), 0)

    def test_threshold_breach_sets_zero(self):
        payload = json.dumps({"error_rate": 9.9, "p95_ms": 10, "conversion": 5}).encode()

        class _Resp:
            def read(self):
                return payload
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        canary._record_verdict("promote")
        with patch.dict(os.environ, {"CANARY_MAX_ERROR_RATE": "1.0"}, clear=True):
            with patch.object(canary.urllib.request, "urlopen", return_value=_Resp()):
                r = canary.evaluate("http://example/metrics")
        self.assertEqual(r["verdict"], "rollback")
        self.assertEqual(_gauge_value(), 0)

    def test_record_verdict_never_raises(self):
        with patch.object(canary, "canary_last_success", object()):
            canary._record_verdict("promote")  # must swallow AttributeError


class TestMetricsRendering(unittest.TestCase):
    def test_render_includes_the_gauge_name(self):
        canary._record_verdict("promote")
        self.assertIn("canary_last_success", canary._render_metrics())

    def test_render_never_raises(self):
        with patch.object(canary, "canary_last_success", object()):
            with patch.object(canary, "PROMETHEUS_AVAILABLE", False):
                self.assertIsInstance(canary._render_metrics(), str)

    def test_render_reflects_current_value(self):
        canary._record_verdict("promote")
        self.assertIn("canary_last_success 1", canary._render_metrics())
        canary._record_verdict("rollback")
        self.assertIn("canary_last_success 0", canary._render_metrics())


class TestFallbackGauge(unittest.TestCase):
    def test_set_get_roundtrip(self):
        g = canary._FallbackGauge("g", "d")
        g.set(1)
        self.assertEqual(g.get(), 1.0)

    def test_inc_dec(self):
        g = canary._FallbackGauge("g", "d")
        g.inc()
        g.inc(2)
        g.dec()
        self.assertEqual(g.get(), 2.0)

    def test_render_is_valid_exposition_format(self):
        g = canary._FallbackGauge("my_metric", "my help")
        out = g.render()
        self.assertIn("# HELP my_metric my help", out)
        self.assertIn("# TYPE my_metric gauge", out)
        self.assertIn("my_metric 0.0", out)


if __name__ == "__main__":
    unittest.main()
