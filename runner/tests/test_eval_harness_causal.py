#!/usr/bin/env python3
"""Tests for causal attribution integration in eval_harness.py.

20+ tests: attribution correctly isolates a routing-change-caused delta from a
concurrent-unrelated-event delta in synthetic data, fail-soft when causal_attribution
errors (falls back to raw before/after, doesn't block eval_harness entirely).
"""
import sys, os, types, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Stub db and causal_attribution for isolated testing
_fake_experiments = []

_db_mod = types.ModuleType("db")
def _fake_select(table, params=None):
    if table == "committee_experiments":
        return list(_fake_experiments)
    return []
_db_mod.select = _fake_select
_db_mod.insert = lambda *a, **k: None
_db_mod.update = lambda *a, **k: None
sys.modules["db"] = _db_mod

_ca_mod = types.ModuleType("causal_attribution")
sys.modules["causal_attribution"] = _ca_mod

# Stub claude_cli
_cli_mod = types.ModuleType("claude_cli")
_cli_mod.run = lambda *a, **k: {"returncode": 0, "text": "ok"}
sys.modules["claude_cli"] = _cli_mod

import eval_harness


class TestCausalAttribution(unittest.TestCase):
    def setUp(self):
        global _fake_experiments
        _fake_experiments = []

    # --- Basic attribution tests ---
    def test_raw_delta_no_experiments(self):
        """No experiments -> falls back to raw delta."""
        r = eval_harness._try_causal_attribution(0.5, 0.8)
        self.assertAlmostEqual(r["raw_delta"], 0.3)
        self.assertAlmostEqual(r["causal_delta"], 0.3)
        self.assertFalse(r["attributed"])

    def test_raw_delta_negative(self):
        """Candidate worse than current -> negative delta."""
        r = eval_harness._try_causal_attribution(0.8, 0.5)
        self.assertAlmostEqual(r["raw_delta"], -0.3)
        self.assertAlmostEqual(r["causal_delta"], -0.3)

    def test_raw_delta_zero(self):
        """Equal rates -> zero delta."""
        r = eval_harness._try_causal_attribution(0.5, 0.5)
        self.assertAlmostEqual(r["raw_delta"], 0.0)

    # --- Concurrent event isolation ---
    def test_positive_concurrent_event_inflated_delta(self):
        """A concurrent positive event inflates raw delta; causal delta strips it."""
        global _fake_experiments
        _fake_experiments = [{"slug": "unrelated-exp", "lift": 10.0, "status": "concluded"}]
        r = eval_harness._try_causal_attribution(0.5, 0.7)
        self.assertAlmostEqual(r["raw_delta"], 0.2)
        self.assertAlmostEqual(r["noise_delta"], 0.1)  # 10% lift
        self.assertAlmostEqual(r["causal_delta"], 0.1)  # 0.2 - 0.1
        self.assertTrue(r["attributed"])

    def test_negative_concurrent_event_masked_improvement(self):
        """A concurrent negative event masks a real improvement."""
        global _fake_experiments
        _fake_experiments = [{"slug": "bad-event", "lift": -20.0, "status": "concluded"}]
        r = eval_harness._try_causal_attribution(0.5, 0.4)
        # Raw says -0.1 (looks like regression), but concurrent event was -0.2
        self.assertAlmostEqual(r["raw_delta"], -0.1)
        self.assertAlmostEqual(r["noise_delta"], -0.2)
        self.assertAlmostEqual(r["causal_delta"], 0.1)  # actually improved!
        self.assertTrue(r["attributed"])

    def test_multiple_concurrent_events(self):
        """Multiple concurrent events sum up."""
        global _fake_experiments
        _fake_experiments = [
            {"slug": "exp-a", "lift": 5.0, "status": "concluded"},
            {"slug": "exp-b", "lift": -3.0, "status": "concluded"},
        ]
        r = eval_harness._try_causal_attribution(0.5, 0.6)
        self.assertAlmostEqual(r["noise_delta"], 0.02)  # (5-3)/100
        self.assertAlmostEqual(r["causal_delta"], 0.08)

    def test_own_change_excluded_from_noise(self):
        """The change being evaluated is excluded from noise calculation."""
        global _fake_experiments
        _fake_experiments = [
            {"slug": "my-routing-change", "lift": 15.0, "status": "concluded"},
            {"slug": "unrelated", "lift": 5.0, "status": "concluded"},
        ]
        r = eval_harness._try_causal_attribution(0.5, 0.7, context={"change_id": "my-routing-change"})
        self.assertAlmostEqual(r["noise_delta"], 0.05)  # only unrelated counted
        self.assertTrue(r["attributed"])

    def test_no_change_id_counts_all(self):
        """Without change_id, all concurrent experiments count as noise."""
        global _fake_experiments
        _fake_experiments = [
            {"slug": "exp-a", "lift": 10.0, "status": "concluded"},
        ]
        r = eval_harness._try_causal_attribution(0.5, 0.7, context=None)
        self.assertAlmostEqual(r["noise_delta"], 0.1)

    def test_experiment_with_none_lift_skipped(self):
        """Experiments without a lift value are skipped."""
        global _fake_experiments
        _fake_experiments = [
            {"slug": "no-lift", "lift": None, "status": "concluded"},
            {"slug": "has-lift", "lift": 5.0, "status": "concluded"},
        ]
        r = eval_harness._try_causal_attribution(0.5, 0.6)
        self.assertAlmostEqual(r["noise_delta"], 0.05)

    # --- Fail-soft tests ---
    def test_failsoft_db_import_error(self):
        """If db module is broken, falls back to raw delta."""
        old = sys.modules.get("db")
        sys.modules["db"] = None  # will cause import to fail in some paths
        # Force a fresh call that won't use cached module
        r = eval_harness._try_causal_attribution(0.5, 0.8)
        # Should not raise, should return raw delta
        self.assertAlmostEqual(r["raw_delta"], 0.3)
        sys.modules["db"] = old

    def test_failsoft_returns_raw_on_exception(self):
        """Any exception in attribution returns raw delta, not error."""
        old_select = _db_mod.select
        _db_mod.select = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down"))
        r = eval_harness._try_causal_attribution(0.5, 0.8)
        self.assertAlmostEqual(r["raw_delta"], 0.3)
        self.assertFalse(r["attributed"])
        _db_mod.select = old_select

    def test_failsoft_does_not_block_eval(self):
        """Even with broken attribution, evaluate_with_attribution still works."""
        old_select = _db_mod.select
        _db_mod.select = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down"))
        result = eval_harness.evaluate_with_attribution(0.8, 0.5)
        self.assertTrue(result["adopt"])  # candidate > current
        _db_mod.select = old_select

    # --- evaluate_with_attribution tests ---
    def test_adopt_when_causal_positive(self):
        """Adopt when causal delta is positive."""
        result = eval_harness.evaluate_with_attribution(0.8, 0.5)
        self.assertTrue(result["adopt"])
        self.assertAlmostEqual(result["candidate_rate"], 0.8)
        self.assertAlmostEqual(result["current_rate"], 0.5)

    def test_reject_when_causal_negative(self):
        """Reject when causal delta is negative."""
        result = eval_harness.evaluate_with_attribution(0.3, 0.5)
        self.assertFalse(result["adopt"])

    def test_adopt_when_equal(self):
        """Adopt when causal delta is zero (>= threshold)."""
        result = eval_harness.evaluate_with_attribution(0.5, 0.5)
        self.assertTrue(result["adopt"])

    def test_adopt_despite_raw_regression_with_concurrent_noise(self):
        """Key test: raw delta says regression, but concurrent negative event
        caused it — causal delta shows actual improvement, so adopt."""
        global _fake_experiments
        _fake_experiments = [{"slug": "infra-outage", "lift": -30.0, "status": "concluded"}]
        result = eval_harness.evaluate_with_attribution(0.4, 0.5)
        # Raw: 0.4 - 0.5 = -0.1 (looks bad)
        # Noise: -0.3 (concurrent bad event)
        # Causal: -0.1 - (-0.3) = 0.2 (actually good!)
        self.assertTrue(result["adopt"])
        self.assertTrue(result["attribution"]["attributed"])

    def test_reject_despite_raw_improvement_with_concurrent_boost(self):
        """Raw delta says improvement, but a concurrent positive event caused it —
        causal delta shows the change itself was harmful, so reject."""
        global _fake_experiments
        _fake_experiments = [{"slug": "lucky-boost", "lift": 50.0, "status": "concluded"}]
        result = eval_harness.evaluate_with_attribution(0.7, 0.5)
        # Raw: 0.7 - 0.5 = 0.2 (looks good)
        # Noise: 0.5 (concurrent good event)
        # Causal: 0.2 - 0.5 = -0.3 (actually bad!)
        self.assertFalse(result["adopt"])

    def test_attribution_result_structure(self):
        """Result dict has expected keys."""
        result = eval_harness.evaluate_with_attribution(0.6, 0.5)
        self.assertIn("adopt", result)
        self.assertIn("candidate_rate", result)
        self.assertIn("current_rate", result)
        self.assertIn("attribution", result)
        attr = result["attribution"]
        self.assertIn("raw_delta", attr)
        self.assertIn("causal_delta", attr)
        self.assertIn("attributed", attr)
        self.assertIn("noise_delta", attr)

    def test_zero_lift_experiment_no_effect(self):
        """Experiment with zero lift contributes no noise."""
        global _fake_experiments
        _fake_experiments = [{"slug": "zero", "lift": 0.0, "status": "concluded"}]
        r = eval_harness._try_causal_attribution(0.5, 0.7)
        self.assertAlmostEqual(r["noise_delta"], 0.0)
        self.assertAlmostEqual(r["causal_delta"], 0.2)

    def test_large_concurrent_noise(self):
        """Large concurrent noise correctly adjusts delta."""
        global _fake_experiments
        _fake_experiments = [{"slug": "massive", "lift": 100.0, "status": "concluded"}]
        r = eval_harness._try_causal_attribution(0.5, 0.7)
        self.assertAlmostEqual(r["noise_delta"], 1.0)
        self.assertAlmostEqual(r["causal_delta"], -0.8)

    def test_context_none_safe(self):
        """context=None doesn't crash."""
        r = eval_harness._try_causal_attribution(0.5, 0.7, context=None)
        self.assertIsInstance(r, dict)

    def test_context_empty_change_id(self):
        """Empty change_id doesn't filter any experiments."""
        global _fake_experiments
        _fake_experiments = [{"slug": "x", "lift": 10.0, "status": "concluded"}]
        r = eval_harness._try_causal_attribution(0.5, 0.7, context={"change_id": ""})
        self.assertAlmostEqual(r["noise_delta"], 0.1)


if __name__ == "__main__":
    unittest.main()
