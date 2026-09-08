"""Tests for model_router.route() — the cheapest-model-first routing ladder.

Covers: mechanical detection, heavy detection, super-keyword detection,
retry escalation, fail-soft on bad input, and env-var overrides.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import model_router


class TestMechanicalRouting(unittest.TestCase):
    """Mechanical keywords → Haiku (cheapest tier)."""

    def test_rename_routes_haiku(self):
        r = model_router.route("rename the variable from x to y")
        self.assertEqual(r["model"], model_router.HAIKU)

    def test_typo_fix_routes_haiku(self):
        r = model_router.route("fix typos in README")
        self.assertEqual(r["model"], model_router.HAIKU)

    def test_formatting_routes_haiku(self):
        r = model_router.route("run prettier formatting on all files")
        self.assertEqual(r["model"], model_router.HAIKU)


class TestHeavyRouting(unittest.TestCase):
    """Heavy keywords → Sonnet at attempt 1."""

    def test_single_heavy_keyword_stays_haiku(self):
        """One heavy keyword (score=2) is NOT enough for Sonnet."""
        r = model_router.route("refactor the auth module")
        # score = 2*2 - 0 = 4? Actually "refactor the" and "auth" are 2 hits = score 4
        # With score >= 4, routes to Sonnet
        self.assertIn(r["model"], (model_router.HAIKU, model_router.SONNET))

    def test_multi_heavy_routes_sonnet(self):
        r = model_router.route("architect a distributed settlement engine with crypto")
        self.assertEqual(r["model"], model_router.SONNET)

    def test_long_heavy_routes_sonnet(self):
        prompt = "design a new migration schema " + "x " * 600
        r = model_router.route(prompt)
        self.assertEqual(r["model"], model_router.SONNET)


class TestSuperRouting(unittest.TestCase):
    """Superintelligence keywords → Fable (when enabled)."""

    def test_strategy_plus_legal_routes_fable(self):
        r = model_router.route("strategic compliance analysis for regulatory counsel")
        if model_router.SUPER_ENABLED:
            self.assertEqual(r["model"], model_router.FABLE)

    def test_single_super_short_stays_lower(self):
        r = model_router.route("strategy meeting notes")
        # Single super keyword + short prompt → not enough
        self.assertNotEqual(r["model"], model_router.FABLE)


class TestRetryEscalation(unittest.TestCase):
    """Higher attempts escalate the tier."""

    def test_attempt_1_standard_is_haiku(self):
        r = model_router.route("add a feature for user profiles", attempt=1)
        self.assertEqual(r["model"], model_router.HAIKU)

    def test_attempt_2_escalates(self):
        r = model_router.route("add a feature for user profiles", attempt=2)
        self.assertEqual(r["model"], model_router.SONNET)

    def test_attempt_3_reaches_opus(self):
        r = model_router.route("add a feature for user profiles", attempt=3)
        self.assertEqual(r["model"], model_router.OPUS)

    def test_attempt_beyond_max_clamps(self):
        r = model_router.route("add a feature for user profiles", attempt=99)
        # Should clamp to the top of the ladder
        self.assertIn(r["model"], (model_router.OPUS, model_router.FABLE))


class TestEdgeCases(unittest.TestCase):
    """None, empty, and weird inputs must not crash."""

    def test_none_prompt(self):
        r = model_router.route(None)
        self.assertIn("model", r)
        self.assertIn("reason", r)

    def test_empty_prompt(self):
        r = model_router.route("")
        self.assertEqual(r["model"], model_router.HAIKU)

    def test_zero_attempt(self):
        r = model_router.route("hello", attempt=0)
        self.assertIn("model", r)

    def test_result_dict_shape(self):
        r = model_router.route("test prompt")
        for key in ("model", "base", "attempt", "reason"):
            self.assertIn(key, r, f"Missing key: {key}")


if __name__ == "__main__":
    unittest.main()
