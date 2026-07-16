#!/usr/bin/env python3
"""Tests for value-per-token routing in model_policy."""
import os, sys, unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestRevenueKeywords(unittest.TestCase):
    def test_returns_set(self):
        from model_policy import revenue_keywords
        kw = revenue_keywords()
        self.assertIsInstance(kw, set)
        self.assertGreater(len(kw), 5)

    def test_core_keywords_present(self):
        from model_policy import revenue_keywords
        kw = revenue_keywords()
        for word in ("pricing", "billing", "payment", "contract", "onboarding"):
            self.assertIn(word, kw)


class TestValueScore(unittest.TestCase):
    def test_baseline_task(self):
        from model_policy import value_score
        score = value_score({"kind": "mechanical", "slug": "fix-typo"})
        self.assertGreaterEqual(score, 1.0)
        self.assertLessEqual(score, 10.0)

    def test_revenue_slug_boosts_score(self):
        from model_policy import value_score
        plain = value_score({"kind": "build", "slug": "refactor-utils"})
        rich  = value_score({"kind": "build", "slug": "billing-payment-upgrade"})
        self.assertGreater(rich, plain)

    def test_hard_kind_boosts_score(self):
        from model_policy import value_score
        build = value_score({"kind": "build", "slug": "foo"})
        hard  = value_score({"kind": "hard",  "slug": "foo"})
        self.assertGreater(hard, build)

    def test_tested_and_reviewed_boost(self):
        from model_policy import value_score
        base   = value_score({"kind": "build", "slug": "billing"})
        tested = value_score({"kind": "build", "slug": "billing", "tested": True})
        both   = value_score({"kind": "build", "slug": "billing", "tested": True, "reviewed": True})
        self.assertGreater(tested, base)
        self.assertGreater(both, tested)

    def test_capped_at_10(self):
        from model_policy import value_score
        task = {"kind": "hard", "slug": "billing-payment-pricing-contract-onboarding",
                "tested": True, "reviewed": True}
        self.assertLessEqual(value_score(task), 10.0)


class TestValuePerToken(unittest.TestCase):
    def test_free_provider_highest_vpt(self):
        from model_policy import value_per_token
        task = {"kind": "build", "slug": "billing-flow"}
        vpt_local = value_per_token(task, "local", "llama3.1")
        vpt_opus  = value_per_token(task, "claude", "claude-opus-4-8")
        # local is free -> should have much higher value-per-token
        self.assertGreater(vpt_local, vpt_opus)

    def test_opus_identified_by_model_name(self):
        from model_policy import value_per_token
        task = {"kind": "hard", "slug": "pricing"}
        vpt_opus   = value_per_token(task, "claude", "claude-opus-4-8")
        vpt_sonnet = value_per_token(task, "claude", "claude-sonnet-4-6")
        # Opus costs more per token so vpt should be lower for same task
        self.assertLess(vpt_opus, vpt_sonnet)

    def test_positive_for_any_task(self):
        from model_policy import value_per_token
        task = {"kind": "mechanical", "slug": "readme-update"}
        vpt = value_per_token(task, "deepseek", "deepseek-v4-flash")
        self.assertGreater(vpt, 0)


class TestChooseValueRouting(unittest.TestCase):
    @patch.dict(os.environ, {"ORCH_VALUE_ROUTING": "true"})
    def test_high_value_hard_routes_opus(self):
        from model_policy import choose
        task = {"kind": "hard", "slug": "billing-payment-upgrade", "tested": True}
        provider, model, reason = choose("hard", agentic=True, task=task)
        self.assertEqual(provider, "claude")
        self.assertIn("opus", model)
        self.assertIn("value-routing", reason)

    @patch.dict(os.environ, {"ORCH_VALUE_ROUTING": "false"})
    def test_value_routing_off_no_override(self):
        from model_policy import choose
        task = {"kind": "hard", "slug": "billing-payment-upgrade", "tested": True}
        _p, _m, reason = choose("hard", agentic=True, task=task)
        self.assertNotIn("value-routing", reason)

    @patch.dict(os.environ, {"ORCH_VALUE_ROUTING": "true"})
    def test_low_value_not_routed_to_opus(self):
        from model_policy import choose
        task = {"kind": "mechanical", "slug": "fix-typo"}
        _p, _m, reason = choose("mechanical", agentic=False, task=task)
        self.assertNotIn("value-routing", reason)

    @patch.dict(os.environ, {})
    def test_no_env_var_no_value_routing(self):
        from model_policy import choose
        task = {"kind": "hard", "slug": "billing-payment-upgrade", "tested": True}
        _p, _m, reason = choose("hard", agentic=True, task=task)
        self.assertNotIn("value-routing", reason)


class TestAnalysisIncludesValueRouting(unittest.TestCase):
    @patch.dict(os.environ, {"ORCH_VALUE_ROUTING": "true"})
    def test_analysis_has_value_routing_key(self):
        from model_policy import analysis
        out = analysis()
        self.assertIn("value_routing", out)
        self.assertTrue(out["value_routing"]["enabled"])
        self.assertIn("threshold", out["value_routing"])
        self.assertIn("revenue_keywords", out["value_routing"])
        self.assertIn("sample", out["value_routing"])

    @patch.dict(os.environ, {"ORCH_VALUE_ROUTING": "false"})
    def test_analysis_disabled(self):
        from model_policy import analysis
        out = analysis()
        self.assertIn("value_routing", out)
        self.assertFalse(out["value_routing"]["enabled"])
        self.assertNotIn("sample", out["value_routing"])


if __name__ == "__main__":
    unittest.main()
