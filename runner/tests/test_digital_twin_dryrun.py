#!/usr/bin/env python3
"""Tests for digital_twin_dryrun.py — shadow env + synthetic traffic for high-risk changes."""
import os, sys, types, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Stub db before importing the module under test
_fake_db = types.ModuleType("db")
_fake_db.select = lambda *a, **k: []
_fake_db.insert = lambda *a, **k: None
_fake_db.update = lambda *a, **k: None
sys.modules["db"] = _fake_db

import digital_twin_dryrun as dtd


def _spec(**kw):
    base = {"id": "test-change-1", "app": "demo", "error_prob": 0.0}
    base.update(kw)
    return base


class TestCreateShadowEnv(unittest.TestCase):
    def test_creates_active_shadow(self):
        env = dtd.create_shadow_env(_spec())
        self.assertTrue(env["shadow_active"])
        self.assertIn("env_id", env)
        self.assertTrue(env["env_id"].startswith("shadow-"))

    def test_degraded_when_disabled(self):
        old = dtd.ENABLED
        try:
            dtd.ENABLED = False
            env = dtd.create_shadow_env(_spec())
            self.assertFalse(env["shadow_active"])
            self.assertIn("reason", env)
        finally:
            dtd.ENABLED = old

    def test_contains_change_spec(self):
        spec = _spec(id="abc")
        env = dtd.create_shadow_env(spec)
        self.assertEqual(env["change_spec"]["id"], "abc")


class TestGenerateSyntheticTraffic(unittest.TestCase):
    def test_correct_count(self):
        env = dtd.create_shadow_env(_spec())
        traffic = dtd.generate_synthetic_traffic(env, num_requests=42)
        self.assertEqual(len(traffic), 42)

    def test_returns_empty_when_inactive(self):
        env = {"shadow_active": False}
        traffic = dtd.generate_synthetic_traffic(env, num_requests=10)
        self.assertEqual(traffic, [])

    def test_request_ids_unique(self):
        env = dtd.create_shadow_env(_spec())
        traffic = dtd.generate_synthetic_traffic(env, num_requests=50)
        ids = [r["request_id"] for r in traffic]
        self.assertEqual(len(ids), len(set(ids)))


class TestRunTwinHarness(unittest.TestCase):
    def test_collects_metrics(self):
        env = dtd.create_shadow_env(_spec())
        traffic = dtd.generate_synthetic_traffic(env, num_requests=20)
        result = dtd.run_twin_harness(env, traffic)
        self.assertTrue(result["ran"])
        self.assertEqual(result["total"], 20)
        self.assertIn("latency_mean_ms", result)
        self.assertIn("latency_p99_ms", result)
        self.assertIn("error_rate", result)
        self.assertEqual(result["successes"] + result["errors"], 20)

    def test_inactive_shadow_returns_not_ran(self):
        result = dtd.run_twin_harness({"shadow_active": False}, [])
        self.assertFalse(result["ran"])


class TestCheckPromotionSafety(unittest.TestCase):
    def test_safe_when_metrics_good(self):
        harness = {
            "ran": True, "error_rate": 0.01, "latency_p99_ms": 500,
        }
        safety = dtd.check_promotion_safety(harness)
        self.assertTrue(safety["safe"])
        self.assertEqual(safety["reasons"], [])

    def test_unsafe_when_error_rate_high(self):
        harness = {
            "ran": True, "error_rate": 0.15, "latency_p99_ms": 500,
        }
        safety = dtd.check_promotion_safety(harness, max_error_rate=0.05)
        self.assertFalse(safety["safe"])
        self.assertTrue(any("error_rate" in r for r in safety["reasons"]))

    def test_unsafe_when_latency_high(self):
        harness = {
            "ran": True, "error_rate": 0.01, "latency_p99_ms": 5000,
        }
        safety = dtd.check_promotion_safety(harness, max_latency_p99_ms=2000)
        self.assertFalse(safety["safe"])
        self.assertTrue(any("latency_p99" in r for r in safety["reasons"]))

    def test_unsafe_when_not_ran(self):
        harness = {"ran": False, "reason": "no shadow"}
        safety = dtd.check_promotion_safety(harness)
        self.assertFalse(safety["safe"])


class TestDryrunChange(unittest.TestCase):
    def test_full_orchestration(self):
        spec = _spec(error_prob=0.0)
        report = dtd.dryrun_change(spec, num_requests=30,
                                   max_error_rate=0.5, max_latency_p99_ms=99999)
        self.assertEqual(report["stage"], "complete")
        self.assertTrue(report["safe"])
        self.assertIn("harness", report)
        self.assertIn("safety", report)
        self.assertEqual(report["harness"]["total"], 30)

    def test_dryrun_blocks_on_high_errors(self):
        spec = _spec(error_prob=0.99)
        report = dtd.dryrun_change(spec, num_requests=50,
                                   max_error_rate=0.05, max_latency_p99_ms=99999)
        self.assertEqual(report["stage"], "complete")
        self.assertFalse(report["safe"])


class TestStats(unittest.TestCase):
    def test_stats_returns_dict(self):
        s = dtd.stats()
        self.assertIsInstance(s, dict)
        self.assertIn("dryruns_total", s)
        self.assertIn("shadow_envs_created", s)
        self.assertIn("harness_runs", s)


class TestDisabledViaEnvFlag(unittest.TestCase):
    def test_disabled_returns_not_active(self):
        old = dtd.ENABLED
        try:
            dtd.ENABLED = False
            report = dtd.dryrun_change(_spec())
            self.assertFalse(report.get("safe", True))
            self.assertIn("reason", report)
        finally:
            dtd.ENABLED = old


if __name__ == "__main__":
    unittest.main()
