#!/usr/bin/env python3
"""Wave C slice 4 — golden-path templates + strategy-aware generation (Part 4, clauses 3 & 4)."""
import os
import sys
import unittest

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
sys.path.insert(0, RUNNER)

import golden_path as gp  # noqa: E402


def shard(slug, vertical="sweepstakes", **kwargs):
    base = {"slug": slug, "vertical": vertical, "merged": True, "attempts": 1,
            "review_cycles": 0, "test_pass": True, "days_to_merge": 1}
    base.update(kwargs)
    return base


class OutcomeScoreTests(unittest.TestCase):
    def test_a_clean_first_pass_merge_scores_highest(self):
        self.assertEqual(gp.outcome_score(shard("a")), 1.0)

    def test_a_shard_that_needed_four_attempts_scores_far_lower(self):
        """Similarity ranking cannot tell these apart. Outcome ranking must."""
        clean = gp.outcome_score(shard("a"))
        struggled = gp.outcome_score(shard("b", attempts=4))
        self.assertLess(struggled, clean / 3)

    def test_an_unmerged_shard_is_never_a_template(self):
        self.assertEqual(gp.outcome_score(shard("a", merged=False)), 0.0)

    def test_a_reverted_shard_is_disqualified_not_merely_penalised(self):
        self.assertEqual(gp.outcome_score(shard("a", reverted=True)), 0.0)

    def test_review_cycles_reduce_the_score(self):
        self.assertLess(gp.outcome_score(shard("a", review_cycles=3)),
                        gp.outcome_score(shard("a", review_cycles=0)))

    def test_a_post_merge_incident_reduces_the_score_sharply(self):
        self.assertLess(gp.outcome_score(shard("a", post_merge_incidents=1)),
                        gp.outcome_score(shard("a")) * 0.7)

    def test_a_slow_merge_is_worth_less_to_copy(self):
        self.assertLess(gp.outcome_score(shard("a", days_to_merge=30)),
                        gp.outcome_score(shard("a", days_to_merge=1)))

    def test_scoring_is_fail_soft(self):
        for value in (None, "x", 42, []):
            self.assertEqual(gp.outcome_score(value), 0.0, repr(value))
        self.assertGreaterEqual(gp.outcome_score({"merged": True, "attempts": "junk"}), 0.0)


class DistilTests(unittest.TestCase):
    def _pool(self, n=20):
        return [shard(f"s{i}", attempts=1 if i < 2 else 3 + i % 3) for i in range(n)]

    def test_only_the_top_decile_survives(self):
        result = gp.distil(self._pool(20), vertical="sweepstakes")
        self.assertEqual(result["eligible"], 20)
        self.assertEqual(len(result["golden"]), 2)

    def test_the_survivors_are_the_best_outcomes_not_the_first_seen(self):
        result = gp.distil(self._pool(20), vertical="sweepstakes")
        self.assertEqual({s["slug"] for s in result["golden"]}, {"s0", "s1"})

    def test_a_thin_vertical_yields_no_template_and_says_why(self):
        result = gp.distil([shard("a"), shard("b")], vertical="sweepstakes")
        self.assertEqual(result["golden"], [])
        self.assertIn("one team's habit", result["reason"])

    def test_unmerged_and_reverted_shards_never_reach_the_pool(self):
        pool = ([shard(f"ok{i}") for i in range(6)]
                + [shard("bad", merged=False), shard("worse", reverted=True)])
        self.assertEqual(gp.distil(pool, vertical="sweepstakes")["eligible"], 6)

    def test_verticals_do_not_contaminate_each_other(self):
        pool = ([shard(f"s{i}", vertical="sweepstakes") for i in range(6)]
                + [shard(f"l{i}", vertical="lending") for i in range(6)])
        result = gp.distil(pool, vertical="lending")
        self.assertTrue(all(s["vertical"] == "lending" for s in result["golden"]))

    def test_a_cutoff_score_is_reported_so_the_bar_is_visible(self):
        self.assertIsNotNone(gp.distil(self._pool(20), vertical="sweepstakes")["cutoff"])

    def test_golden_paths_covers_every_vertical_present(self):
        pool = ([shard(f"s{i}", vertical="sweepstakes") for i in range(6)]
                + [shard(f"l{i}", vertical="lending") for i in range(6)])
        self.assertEqual(sorted(gp.golden_paths(pool)), ["lending", "sweepstakes"])

    def test_template_for_returns_the_single_best_or_none(self):
        self.assertEqual(gp.template_for(self._pool(20), "sweepstakes")["slug"], "s0")
        self.assertIsNone(gp.template_for([], "sweepstakes"))

    def test_distillation_is_fail_soft(self):
        self.assertEqual(gp.distil(None)["golden"], [])
        self.assertEqual(gp.distil(["junk", None])["golden"], [])
        self.assertEqual(gp.golden_paths(None), {})


class StructureRequirementTests(unittest.TestCase):
    def test_the_specs_own_worked_example_is_covered(self):
        """'sweepstakes entry generates AMOE flows + state gates natively'."""
        requirements = " ".join(gp.structure_requirements("sweepstakes")).lower()
        self.assertIn("amoe", requirements)
        self.assertIn("per-state eligibility gating", requirements)
        self.assertIn("consideration", requirements)

    def test_money_transmission_forbids_custody_on_every_path(self):
        self.assertIn("no custody of customer funds on any path",
                      gp.structure_requirements("money-transmission"))

    def test_lending_requires_apr_before_commitment(self):
        self.assertTrue(any("APR" in r for r in gp.structure_requirements("lending")))

    def test_case_and_whitespace_do_not_defeat_the_lookup(self):
        self.assertEqual(gp.structure_requirements("  SWEEPSTAKES "),
                         gp.structure_requirements("sweepstakes"))

    def test_an_unknown_structure_returns_nothing_rather_than_guessing(self):
        self.assertEqual(gp.structure_requirements("something-invented"), [])
        self.assertEqual(gp.structure_requirements(None), [])


class StrategyContextTests(unittest.TestCase):
    APPROVED = {"structure": "sweepstakes", "approved": True, "jurisdictions": ["us-ca", "us-ny"]}

    def test_an_approved_structure_becomes_generation_context(self):
        context = gp.strategy_context(self.APPROVED)
        self.assertTrue(context["ok"])
        self.assertEqual(context["structure"], "sweepstakes")
        self.assertIn("AMOE", context["prompt"])
        self.assertIn("us-ca", context["prompt"])

    def test_the_prompt_says_the_requirements_are_not_review_findings(self):
        self.assertIn("BORN with these", gp.strategy_context(self.APPROVED)["prompt"])

    def test_generation_is_blocked_when_no_structure_is_approved(self):
        context = gp.strategy_context({"structure": "sweepstakes", "approved": False})
        self.assertFalse(context["ok"])
        self.assertIn("NOT approved", context["reason"])

    def test_generation_is_blocked_when_there_is_no_structure_at_all(self):
        context = gp.strategy_context({})
        self.assertFalse(context["ok"])
        self.assertIn("retrofitting", context["reason"])

    def test_a_golden_template_is_named_in_the_context_when_one_exists(self):
        context = gp.strategy_context(self.APPROVED, template={"slug": "s0"})
        self.assertEqual(context["template_slug"], "s0")
        self.assertIn("best-outcome merged shard", context["prompt"])

    def test_an_unknown_structure_is_called_a_gap_not_a_free_pass(self):
        context = gp.strategy_context({"structure": "novel-thing", "approved": True})
        self.assertTrue(context["ok"])
        self.assertIn("gap in this module", context["prompt"])
        self.assertIn("not as permission to skip", context["prompt"])

    def test_context_building_is_fail_soft(self):
        for value in (None, "x", 42, []):
            self.assertFalse(gp.strategy_context(value)["ok"], repr(value))


class MissingRequirementTests(unittest.TestCase):
    def test_an_unimplemented_amoe_flow_is_reported_before_review(self):
        missing = gp.missing_requirements("sweepstakes", ["per-state eligibility gating"])
        self.assertTrue(any("alternate method of entry" in m for m in missing))

    def test_a_fully_covered_structure_reports_nothing_missing(self):
        self.assertEqual(gp.missing_requirements(
            "sweepstakes", gp.structure_requirements("sweepstakes")), [])

    def test_an_unknown_structure_reports_nothing(self):
        self.assertEqual(gp.missing_requirements("nope", []), [])

    def test_missing_requirements_is_fail_soft(self):
        self.assertEqual(gp.missing_requirements(None, None), [])


class RenderTests(unittest.TestCase):
    def test_a_blocked_context_is_reported_as_blocked(self):
        self.assertIn("BLOCKED", gp.render(context=gp.strategy_context({})))

    def test_a_thin_vertical_explains_itself(self):
        text = gp.render(distilled=gp.distil([shard("a")], vertical="sweepstakes"))
        self.assertIn("habit", text)

    def test_render_is_fail_soft(self):
        self.assertIsInstance(gp.render(), str)
        self.assertIsInstance(gp.render(None, None), str)


if __name__ == "__main__":
    unittest.main()
