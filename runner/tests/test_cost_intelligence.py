import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cost_intelligence as ci


def _o(usd=1.0, integrated=True, tests_passed=True, coder="claude",
      input_tokens=10000, output_tokens=2000, project="acme"):
    return {"usd": usd, "integrated": integrated, "tests_passed": tests_passed,
            "coder": coder, "input_tokens": input_tokens, "output_tokens": output_tokens,
            "project": project}


class DirectEfficiencyTest(unittest.TestCase):
    def test_basic_ratios(self):
        outcomes = [_o(usd=2.0), _o(usd=2.0), _o(usd=0, integrated=False, tests_passed=False)]
        d = ci.direct_efficiency(outcomes)
        self.assertEqual(d["attempts"], 3)
        self.assertEqual(d["n_merged"], 2)
        self.assertAlmostEqual(d["merge_rate"], 2 / 3, places=4)
        self.assertEqual(d["usd_per_merge"], 2.0)  # 4.0 total / 2 merged

    def test_fresh_merge_excludes_reuse_coders(self):
        outcomes = [
            _o(usd=5.0, coder="claude"),
            _o(usd=0.0, coder="zero-token"),
            _o(usd=0.0, coder="compiled-intent"),
        ]
        d = ci.direct_efficiency(outcomes)
        self.assertEqual(d["n_fresh_merged"], 1)
        self.assertEqual(d["avg_fresh_merge_usd"], 5.0)

    def test_empty_outcomes_no_crash(self):
        d = ci.direct_efficiency([])
        self.assertEqual(d["attempts"], 0)
        self.assertIsNone(d["merge_rate"])
        self.assertIsNone(d["usd_per_merge"])


class IndirectSavingsTest(unittest.TestCase):
    def test_separates_cost_avoidance_from_additive_value(self):
        outcomes = [
            _o(usd=4.0, coder="claude"),          # fresh baseline: $4/merge
            _o(usd=0.0, coder="zero-token"),
            _o(usd=0.0, coder="zero-token"),
            _o(usd=0.1, coder="compiled-intent"),
        ]
        cap_instances = [{"capability_id": "c1", "project": "b"}, {"capability_id": "c1", "project": "c"}]
        direct = ci.direct_efficiency(outcomes)
        result = ci.indirect_savings(outcomes, cap_instances, direct)
        self.assertEqual(result["zero_token_events"], 2)
        self.assertEqual(result["compiled_intent_events"], 1)
        self.assertEqual(result["cost_avoidance_events"], 3)   # already inside n_merged
        self.assertEqual(result["capability_reuse_events"], 2)
        self.assertEqual(result["additive_value_events"], 2)   # separate from n_merged
        self.assertEqual(result["total_reuse_events"], 5)      # reporting-only combined count
        # gross = 5 events * $4 counterfactual = $20; actual spend on reuse events = $0.1
        self.assertEqual(result["gross_avoided_usd"], 20.0)
        self.assertEqual(result["net_avoided_usd"], 19.9)

    def test_no_reuse_events_yields_zero_savings(self):
        outcomes = [_o(usd=1.0)]
        direct = ci.direct_efficiency(outcomes)
        result = ci.indirect_savings(outcomes, [], direct)
        self.assertEqual(result["total_reuse_events"], 0)
        self.assertEqual(result["additive_value_events"], 0)
        self.assertEqual(result["gross_avoided_usd"], 0.0)

    def test_net_never_goes_negative(self):
        # pathological: reuse events cost MORE than the counterfactual (shouldn't normally
        # happen, but the formula must not report negative "savings")
        outcomes = [_o(usd=0.01, coder="claude"), _o(usd=5.0, coder="zero-token")]
        direct = ci.direct_efficiency(outcomes)
        result = ci.indirect_savings(outcomes, [], direct)
        self.assertGreaterEqual(result["net_avoided_usd"], 0.0)


class CompetitorComparisonTest(unittest.TestCase):
    def test_deepseek_price_applied_to_our_tokens(self):
        direct = {"avg_fresh_merge_input_tokens": 1_000_000, "avg_fresh_merge_output_tokens": 1_000_000,
                  "avg_fresh_merge_usd": 0.0, "n_merged": 0}
        indirect = {"additive_value_events": 0}
        c = ci.competitor_comparison(direct, indirect, total_usd_spent=0.0)
        expected = ci.DEEPSEEK_PRICE_INPUT_PER_M + ci.DEEPSEEK_PRICE_OUTPUT_PER_M
        self.assertAlmostEqual(c["raw_deepseek_usd_per_solve"], expected, places=4)

    def test_never_claims_per_token_price_parity_when_we_cost_more(self):
        # our $/solve ($5) is far above DeepSeek's raw token-price equivalent for the same
        # tokens (a few cents) — the verdict MUST say we do not beat per-token price. This
        # guards against ever silently flipping this to a false "we're cheaper" claim.
        direct = {"avg_fresh_merge_input_tokens": 20000, "avg_fresh_merge_output_tokens": 4000,
                  "avg_fresh_merge_usd": 5.0, "n_merged": 10}
        indirect = {"additive_value_events": 0}
        c = ci.competitor_comparison(direct, indirect, total_usd_spent=50.0)
        self.assertIn("do not claim otherwise", c["raw_per_token_verdict"])

    def test_portfolio_verdict_reflects_real_arithmetic_not_assumed(self):
        # construct numbers where our actual cost for the covered units is DEMONSTRABLY
        # higher than DeepSeek-with-no-reuse would cost, and confirm the verdict says so
        # instead of defaulting to a favorable claim.
        direct = {"avg_fresh_merge_input_tokens": 1000, "avg_fresh_merge_output_tokens": 200,
                  "avg_fresh_merge_usd": 100.0, "n_merged": 1}
        indirect = {"additive_value_events": 0}
        c = ci.competitor_comparison(direct, indirect, total_usd_spent=100.0)
        # DeepSeek raw cost for 1 unit at these tiny token counts is a fraction of a cent —
        # our actual cost ($100) must NOT be reported as lower.
        self.assertLess(c["deepseek_cost_if_solved_independently_every_time"],
                        c["our_actual_cost_for_same_coverage"])
        self.assertIn("still lower total cost", c["portfolio_verdict"])

    def test_zero_tokens_yields_zero_cost(self):
        direct = {"avg_fresh_merge_input_tokens": 0, "avg_fresh_merge_output_tokens": 0,
                  "avg_fresh_merge_usd": 0.0, "n_merged": 0}
        c = ci.competitor_comparison(direct, {"additive_value_events": 0}, total_usd_spent=0.0)
        self.assertEqual(c["raw_deepseek_usd_per_solve"], 0.0)


class QualityAdjustmentTest(unittest.TestCase):
    def test_retry_multiplier_favors_higher_scoring_model(self):
        q = ci.quality_adjustment(our_model="claude-opus-4-8", competitor_model="deepseek-v4-pro-max")
        # Opus scores higher on swe_bench_verified (88.6 vs 80.6) -> multiplier > 1
        self.assertGreater(q["retry_multiplier"], 1.0)

    def test_near_parity_multiplier_close_to_one(self):
        q = ci.quality_adjustment(our_model="claude-sonnet-4-6", competitor_model="deepseek-v4-pro-max")
        # Sonnet (79.6) vs DeepSeek Pro-Max (80.6) on Verified: DeepSeek is actually slightly
        # higher-scoring here — multiplier must be honestly < 1, not clamped to 1.0.
        self.assertLess(q["retry_multiplier"], 1.0)

    def test_points_per_dollar_computed_for_both(self):
        q = ci.quality_adjustment(our_model="claude-opus-4-8", competitor_model="deepseek-v4-pro-max")
        self.assertIsNotNone(q["our_points_per_dollar"])
        self.assertIsNotNone(q["competitor_points_per_dollar"])
        # DeepSeek's points-per-dollar should dramatically exceed Opus's given the price gap.
        self.assertGreater(q["competitor_points_per_dollar"], q["our_points_per_dollar"] * 5)

    def test_missing_model_no_crash(self):
        q = ci.quality_adjustment(our_model="not-a-real-model", competitor_model="deepseek-v4-pro-max")
        self.assertIsNone(q["retry_multiplier"])
        self.assertIsNone(q["our_points_per_dollar"])


class CompetitorComparisonQualityTest(unittest.TestCase):
    def test_quality_adjusted_fields_present_when_quality_passed(self):
        direct = {"avg_fresh_merge_input_tokens": 20000, "avg_fresh_merge_output_tokens": 4000,
                  "avg_fresh_merge_usd": 5.0, "n_merged": 10}
        indirect = {"additive_value_events": 0}
        quality = ci.quality_adjustment(our_model="claude-opus-4-8", competitor_model="deepseek-v4-pro-max")
        c = ci.competitor_comparison(direct, indirect, total_usd_spent=50.0, quality=quality)
        self.assertIsNotNone(c["deepseek_usd_per_solve_quality_adjusted"])
        self.assertIsNotNone(c["deepseek_cost_quality_adjusted"])
        # quality-adjusted DeepSeek cost should scale by retry_multiplier vs the raw figure
        expected = round(c["raw_deepseek_usd_per_solve"] * quality["retry_multiplier"], 4)
        self.assertAlmostEqual(c["deepseek_usd_per_solve_quality_adjusted"], expected, places=4)

    def test_quality_fields_none_when_quality_omitted(self):
        direct = {"avg_fresh_merge_input_tokens": 20000, "avg_fresh_merge_output_tokens": 4000,
                  "avg_fresh_merge_usd": 5.0, "n_merged": 10}
        indirect = {"additive_value_events": 0}
        c = ci.competitor_comparison(direct, indirect, total_usd_spent=50.0)
        self.assertIsNone(c["deepseek_usd_per_solve_quality_adjusted"])
        self.assertIsNone(c["deepseek_cost_quality_adjusted"])

    def test_never_flips_per_token_verdict_due_to_quality(self):
        # Quality adjustment must never touch raw_per_token_verdict -- that verdict is about
        # raw token price only, and must keep saying we don't beat it even with quality passed.
        direct = {"avg_fresh_merge_input_tokens": 20000, "avg_fresh_merge_output_tokens": 4000,
                  "avg_fresh_merge_usd": 5.0, "n_merged": 10}
        indirect = {"additive_value_events": 0}
        quality = ci.quality_adjustment(our_model="claude-opus-4-8", competitor_model="deepseek-v4-pro-max")
        c = ci.competitor_comparison(direct, indirect, total_usd_spent=50.0, quality=quality)
        self.assertIn("do not claim otherwise", c["raw_per_token_verdict"])


class SelfImprovementSignalTest(unittest.TestCase):
    def test_reuse_velocity_averaged_per_capability(self):
        instances = [
            {"capability_id": "c1"}, {"capability_id": "c1"}, {"capability_id": "c1"},
            {"capability_id": "c2"},
        ]
        s = ci.self_improvement_signal([{"id": "c1"}, {"id": "c2"}], instances)
        self.assertEqual(s["capability_instances_in_window"], 4)
        self.assertEqual(s["avg_reuse_per_published_capability"], 2.0)  # 4 instances / 2 capabilities

    def test_no_capabilities_no_crash(self):
        s = ci.self_improvement_signal([], [])
        self.assertEqual(s["avg_reuse_per_published_capability"], 0.0)


class ComputeIntegrationTest(unittest.TestCase):
    def test_blended_value_does_not_double_count_reuse_coders(self):
        outcomes = [
            _o(usd=4.0, coder="claude"),
            _o(usd=0.0, coder="zero-token"),   # inside n_merged already
        ]
        direct = ci.direct_efficiency(outcomes)
        self.assertEqual(direct["n_merged"], 2)
        indirect = ci.indirect_savings(outcomes, [{"capability_id": "c1"}], direct)
        # units of value = n_merged (2) + additive_value_events (1 capability reuse) = 3,
        # NOT n_merged + total_reuse_events (2 + 2 = 4, which would double-count zero-token)
        total_units = direct["n_merged"] + indirect["additive_value_events"]
        self.assertEqual(total_units, 3)


class ReportWritersTest(unittest.TestCase):
    def test_writes_both_files_and_external_has_no_raw_counts(self):
        import tempfile, shutil
        out_dir = tempfile.mkdtemp()
        try:
            outcomes = [_o(usd=3.0), _o(usd=0.0, coder="zero-token")]
            direct = ci.direct_efficiency(outcomes)
            indirect = ci.indirect_savings(outcomes, [], direct)
            quality_sonnet = ci.quality_adjustment(our_model="claude-sonnet-4-6",
                                                    competitor_model="deepseek-v4-pro-max")
            quality_opus = ci.quality_adjustment(our_model="claude-opus-4-8",
                                                 competitor_model="deepseek-v4-pro-max")
            payload = {
                "generated_at": "2026-07-10T00:00:00",
                "window_days": 30,
                "direct": direct,
                "indirect": indirect,
                "competitor_deepseek": ci.competitor_comparison(direct, indirect, total_usd_spent=3.0,
                                                                 quality=quality_sonnet),
                "quality_adjustment_sonnet": quality_sonnet,
                "quality_adjustment_opus": quality_opus,
                "self_improvement": ci.self_improvement_signal([], []),
                "blended_cost_per_unit_of_delivered_value": 1.5,
            }
            internal_path = ci._write_internal_report(payload, out_dir)
            external_path = ci._write_external_report(payload, out_dir)
            self.assertTrue(os.path.isfile(internal_path))
            self.assertTrue(os.path.isfile(external_path))
            external_text = open(external_path).read()
            # external must never leak the raw event-count methodology
            self.assertNotIn("zero_token_events", external_text)
            self.assertNotIn("capability_reuse_events", external_text)
            # external must never leak raw quality-index model names/scores either
            self.assertNotIn("retry_multiplier", external_text)
            self.assertNotIn("swe_bench_verified", external_text)
            internal_text = open(internal_path).read()
            self.assertIn("Do not share this file externally", internal_text)
            self.assertIn("retry_multiplier", internal_text)
            self.assertIn("Honest finding", internal_text)
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
