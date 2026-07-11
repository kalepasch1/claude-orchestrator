import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cost_intelligence as ci
import improvement_roadmap as ir


def _baseline():
    outcomes = [
        {"usd": 4.0, "integrated": True, "tests_passed": True, "coder": "claude",
         "input_tokens": 20000, "output_tokens": 4000, "project": "a"},
        {"usd": 4.0, "integrated": True, "tests_passed": True, "coder": "claude",
         "input_tokens": 20000, "output_tokens": 4000, "project": "b"},
        {"usd": 0.0, "integrated": True, "tests_passed": True, "coder": "zero-token",
         "input_tokens": 0, "output_tokens": 0, "project": "a"},
    ]
    cap_instances = [{"capability_id": "c1", "project": "b"}, {"capability_id": "c1", "project": "c"}]
    direct = ci.direct_efficiency(outcomes)
    indirect = ci.indirect_savings(outcomes, cap_instances, direct)
    quality = ci.quality_adjustment(our_model="claude-sonnet-4-6", competitor_model="deepseek-v4-pro-max")
    total_usd = sum(o["usd"] for o in outcomes)
    comp = ci.competitor_comparison(direct, indirect, total_usd, quality=quality)
    total_units = direct["n_merged"] + indirect["additive_value_events"]
    blended = round(total_usd / total_units, 4) if total_units else None
    return {"direct": direct, "indirect": indirect, "competitor_deepseek": comp,
            "blended_cost_per_unit_of_delivered_value": blended}


class BuildRoadmapTest(unittest.TestCase):
    def test_no_baseline_data_does_not_fabricate(self):
        empty_baseline = {"direct": {"attempts": 0}, "indirect": {}, "competitor_deepseek": {}}
        r = ir.build_roadmap(baseline=empty_baseline)
        self.assertEqual(r["stages"], [])
        self.assertIn("error", r)

    def test_stage_0_matches_measured_baseline_exactly(self):
        baseline = _baseline()
        r = ir.build_roadmap(baseline=baseline)
        stage0 = r["stages"][0]
        self.assertEqual(stage0["projected_blended_cost_per_unit"],
                         baseline["blended_cost_per_unit_of_delivered_value"])

    def test_stages_are_monotonically_non_increasing_in_gap(self):
        # Each successive stage assumes MORE improvement levers, so the gap vs DeepSeek must
        # never get worse than an earlier stage.
        baseline = _baseline()
        r = ir.build_roadmap(baseline=baseline)
        gaps = [s["gap_multiple_vs_deepseek"] for s in r["stages"]]
        for earlier, later in zip(gaps, gaps[1:]):
            self.assertGreaterEqual(earlier, later)

    def test_final_stage_never_claims_500x_it_does_not_reach(self):
        baseline = _baseline()
        r = ir.build_roadmap(baseline=baseline)
        # This is a property test on the verdict logic itself, not a hardcoded expected number:
        # if the final stage's computed improvement factor is below 500, the verdict text must
        # not claim the 500x threshold was reached.
        final = r["stages"][-1]
        improvement_factor = r["baseline_gap_multiple"] / final["gap_multiple_vs_deepseek"]
        if improvement_factor < 500:
            self.assertIn("does not reach the 500x threshold", r["verdict"])
        else:
            self.assertIn("reaches the 500x threshold", r["verdict"])

    def test_assumptions_disclosed_for_every_non_baseline_stage(self):
        baseline = _baseline()
        r = ir.build_roadmap(baseline=baseline)
        for s in r["stages"][1:]:
            self.assertIn("Assumes:", s["assumptions"])


if __name__ == "__main__":
    unittest.main()
