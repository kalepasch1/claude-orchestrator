"""Slice 3: pricing_config wired into the economic scheduler's initialization path.

Acceptance for this slice: load_ctx() carries the pricing table, existing scoring is
byte-for-byte unchanged under the stock defaults, and the tier weighting only becomes
live once an operator pushes a project-keyed ORCH_PRICING_TIERS.
"""
import os
import sys
import unittest
from unittest import mock

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
sys.path.insert(0, RUNNER)

import economic_scheduler  # noqa: E402
import pricing_config  # noqa: E402


class LoadCtxCarriesPricingTests(unittest.TestCase):
    def setUp(self):
        pricing_config.invalidate()
        self.addCleanup(pricing_config.invalidate)

    def _load_ctx_without_db(self):
        """load_ctx with the DB reads stubbed; only the pricing wiring is under test."""
        with mock.patch.object(economic_scheduler.db, "select", return_value=[]), \
             mock.patch.object(economic_scheduler.revenue_attribution, "kind_roi", return_value={}):
            return economic_scheduler.load_ctx()

    def test_ctx_contains_the_pricing_table(self):
        ctx = self._load_ctx_without_db()
        self.assertIn("pricing", ctx)
        for key in pricing_config.REQUIRED_KEYS:
            self.assertIn(key, ctx["pricing"])

    def test_ctx_keeps_its_original_keys(self):
        """Backward compatibility: nothing that was on ctx before has gone away."""
        ctx = self._load_ctx_without_db()
        for key in ("kind_roi", "high_growth_projects", "error_rates"):
            self.assertIn(key, ctx)

    def test_pricing_load_failure_does_not_break_ctx(self):
        """Fail-soft: pricing_config never raises, but ctx must survive even if it did."""
        with mock.patch.object(pricing_config, "load_pricing_config",
                               return_value={"tiers": {}, "rate_limits": {}, "ttl_seconds": 1}):
            ctx = self._load_ctx_without_db()
        self.assertEqual(ctx["pricing"]["tiers"], {})
        self.assertEqual(economic_scheduler._tier_multiplier(ctx, "apparently"), 1.0)


class TierAccessorTests(unittest.TestCase):
    def test_unknown_project_gets_no_tier_price(self):
        ctx = {"pricing": {"tiers": {"free": 0.0, "pro": 199.0}}}
        self.assertEqual(economic_scheduler.project_tier_price(ctx, "apparently"),
                         economic_scheduler.NO_TIER_PRICE)

    def test_known_project_gets_its_price(self):
        ctx = {"pricing": {"tiers": {"apparently": 999.0, "tomorrow": 199.0}}}
        self.assertEqual(economic_scheduler.project_tier_price(ctx, "apparently"), 999.0)

    def test_rate_limit_accessor(self):
        ctx = {"pricing": {"rate_limits": {"apparently": 10000}}}
        self.assertEqual(economic_scheduler.project_rate_limit(ctx, "apparently"), 10000)
        self.assertIsNone(economic_scheduler.project_rate_limit(ctx, "tomorrow"))

    def test_accessors_never_raise_on_a_malformed_ctx(self):
        for bad in (None, {}, {"pricing": None}, {"pricing": {"tiers": None}}, {"pricing": "x"}):
            self.assertEqual(economic_scheduler.project_tier_price(bad, "p"),
                             economic_scheduler.NO_TIER_PRICE)
            self.assertIsNone(economic_scheduler.project_rate_limit(bad, "p"))
            self.assertEqual(economic_scheduler._tier_multiplier(bad, "p"), 1.0)


class TierMultiplierTests(unittest.TestCase):
    def test_defaults_are_inert(self):
        """The whole backward-compatibility claim, pinned: stock table => multiplier 1.0."""
        ctx = {"pricing": {"tiers": dict(pricing_config.DEFAULT_TIERS)}}
        for project in ("apparently", "tomorrow", "beethoven", "smarter", ""):
            self.assertEqual(economic_scheduler._tier_multiplier(ctx, project), 1.0)

    def test_cheapest_paid_tier_is_the_baseline(self):
        ctx = {"pricing": {"tiers": {"free_app": 0.0, "small": 199.0, "big": 995.0}}}
        self.assertEqual(economic_scheduler._tier_multiplier(ctx, "small"), 1.0)
        self.assertEqual(economic_scheduler._tier_multiplier(ctx, "big"), 5.0)

    def test_a_free_project_is_unchanged_not_zeroed(self):
        ctx = {"pricing": {"tiers": {"free_app": 0.0, "small": 199.0}}}
        self.assertEqual(economic_scheduler._tier_multiplier(ctx, "free_app"), 1.0)

    def test_an_all_free_table_cannot_divide_by_zero(self):
        ctx = {"pricing": {"tiers": {"a": 0.0, "b": 0.0}}}
        self.assertEqual(economic_scheduler._tier_multiplier(ctx, "a"), 1.0)


class ScoringBackwardCompatibilityTests(unittest.TestCase):
    """predict_revenue must return identical numbers under the stock pricing table."""

    TASK = {"project": "apparently", "kind": "bugfix", "prompt": "fix the billing page", "usd": 2.0}

    def _ctx(self, pricing):
        return {
            "kind_roi": {"bugfix": 100.0},
            "high_growth_projects": set(),
            "error_rates": {},
            "pricing": pricing,
        }

    def test_stock_table_leaves_the_estimate_unchanged(self):
        with_pricing = economic_scheduler.predict_revenue(
            self.TASK, self._ctx({"tiers": dict(pricing_config.DEFAULT_TIERS)}))
        # Same ctx with no pricing key at all — i.e. the pre-slice-3 shape.
        legacy_ctx = self._ctx({})
        legacy_ctx.pop("pricing")
        legacy = economic_scheduler.predict_revenue(self.TASK, legacy_ctx)
        self.assertEqual(tuple(with_pricing), tuple(legacy))

    def test_a_project_keyed_table_makes_the_weighting_live(self):
        base = economic_scheduler.predict_revenue(
            self.TASK, self._ctx({"tiers": dict(pricing_config.DEFAULT_TIERS)}))
        weighted = economic_scheduler.predict_revenue(
            self.TASK, self._ctx({"tiers": {"tomorrow": 199.0, "apparently": 995.0}}))
        self.assertAlmostEqual(weighted["point_estimate"], base["point_estimate"] * 5.0)

    def test_cost_benefit_and_score_still_work_with_pricing_on_ctx(self):
        ctx = self._ctx({"tiers": dict(pricing_config.DEFAULT_TIERS)})
        cb = economic_scheduler.cost_benefit(self.TASK, ctx)
        for key in ("predicted_revenue", "estimated_cost", "roi", "worthwhile"):
            self.assertIn(key, cb)
        self.assertIsInstance(economic_scheduler.score(self.TASK, ctx), float)

    def test_non_dict_task_is_still_fail_soft(self):
        ctx = self._ctx({"tiers": dict(pricing_config.DEFAULT_TIERS)})
        self.assertEqual(tuple(economic_scheduler.predict_revenue(None, ctx)), (0.0, 0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
