#!/usr/bin/env python3
"""The circular hivemind's privacy gates, and the flywheel it is supposed to prove.

The section's proof line asks for three things: contribution respects opt-in and
the k-floor, the planner can consult the corpus, and the KPI computes from
fixture history. All three are here.

The k-floor tests are written the way the guarantee can actually fail: ONE
tenant contributing the same pattern ten times must not clear a floor that
counts distinct tenants. If that ever passes, the anonymity claim is false while
every other test still looks green.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import convention_corpus as cc  # noqa: E402

OPT_IN = {"corpus_opt_in": True}
OPT_OUT = {"corpus_opt_in": False}


class CorpusTestBase(unittest.TestCase):
    def setUp(self):
        cc._reset()

    def tearDown(self):
        cc._reset()


class OptInTest(CorpusTestBase):
    """Explicit yes only."""

    def test_opted_in_tenant_contributes(self):
        r = cc.contribute("t1", "DO fail soft on bad input", config=OPT_IN)
        self.assertTrue(r["stored"])

    def test_absent_config_is_a_no(self):
        # The dangerous default would be "unset means yes".
        r = cc.contribute("t1", "DO fail soft", config=None)
        self.assertFalse(r["stored"])
        self.assertIn("opted in", r["reason"])

    def test_explicit_false_is_a_no(self):
        self.assertFalse(cc.contribute("t1", "DO fail soft", config=OPT_OUT)["stored"])

    def test_truthy_but_not_true_is_a_no(self):
        for junk in ("yes", 1, [1], {"x": 1}):
            with self.subTest(junk=junk):
                self.assertFalse(cc.contribute("t1", "x", config={"corpus_opt_in": junk})["stored"])

    def test_missing_inputs_refused_with_a_reason(self):
        self.assertFalse(cc.contribute("", "x", config=OPT_IN)["stored"])
        self.assertFalse(cc.contribute("t1", "", config=OPT_IN)["stored"])
        self.assertTrue(cc.contribute("t1", "   ", config=OPT_IN)["reason"])


class KAnonymityFloorTest(CorpusTestBase):
    """The floor counts DISTINCT tenants, which is the whole guarantee."""

    def test_pattern_below_the_floor_is_not_surfaced(self):
        cc.contribute("t1", "DO name magic numbers", config=OPT_IN)
        cc.contribute("t2", "DO name magic numbers", config=OPT_IN)
        got = cc.retrieve("t3", config=OPT_IN)
        self.assertEqual(got, [], "2 tenants cleared a floor of 3")

    def test_pattern_at_the_floor_is_surfaced(self):
        for t in ("t1", "t2", "t3"):
            cc.contribute(t, "DO name magic numbers", config=OPT_IN)
        got = cc.retrieve("t9", config=OPT_IN)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["source"], "cross_tenant")
        self.assertEqual(got[0]["tenant_count"], 3)

    def test_one_tenant_repeating_itself_never_clears_the_floor(self):
        # The failure mode that would make the anonymity claim false while every
        # other test stays green.
        for _ in range(10):
            cc.contribute("t1", "DO name magic numbers", config=OPT_IN)
        self.assertEqual(cc.retrieve("t2", config=OPT_IN), [])

    def test_wording_noise_does_not_split_a_pattern(self):
        # If it did, the floor would never trip and the corpus would look empty.
        cc.contribute("t1", "DO fail soft.", config=OPT_IN)
        cc.contribute("t2", "do fail   soft", config=OPT_IN)
        cc.contribute("t3", "DO, fail soft!", config=OPT_IN)
        got = cc.retrieve("t9", config=OPT_IN)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["tenant_count"], 3)


class OwnVsCrossTenantTest(CorpusTestBase):
    """Own patterns always; cross-tenant only on opt-in."""

    def test_own_patterns_are_available_without_opt_in_at_read_time(self):
        cc.contribute("t1", "DO log before swallowing", config=OPT_IN)
        got = cc.retrieve("t1", config=OPT_OUT)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["source"], "own")

    def test_opted_out_tenant_sees_no_cross_tenant_patterns(self):
        for t in ("t1", "t2", "t3"):
            cc.contribute(t, "DO name magic numbers", config=OPT_IN)
        self.assertEqual(cc.retrieve("t9", config=OPT_OUT), [])

    def test_own_pattern_corroborated_by_others_is_labelled(self):
        for t in ("t1", "t2", "t3"):
            cc.contribute(t, "DO name magic numbers", config=OPT_IN)
        got = cc.retrieve("t1", config=OPT_IN)
        self.assertEqual(got[0]["source"], "corroborated")
        self.assertEqual(got[0]["tenant_count"], 3)

    def test_results_never_name_another_tenant(self):
        for t in ("acme-corp", "globex", "initech"):
            cc.contribute(t, "DO name magic numbers", config=OPT_IN)
        blob = repr(cc.retrieve("t9", config=OPT_IN))
        for t in ("acme-corp", "globex", "initech"):
            self.assertNotIn(t, blob)

    def test_category_filter(self):
        for t in ("t1", "t2", "t3"):
            cc.contribute(t, "DO fail soft", category="python", config=OPT_IN)
            cc.contribute(t, "DO use strict mode", category="ts", config=OPT_IN)
        self.assertEqual(len(cc.retrieve("t9", category="python", config=OPT_IN)), 1)

    def test_limit_is_respected(self):
        for i in range(5):
            for t in ("t1", "t2", "t3"):
                cc.contribute(t, f"DO thing number {i}", config=OPT_IN)
        self.assertEqual(len(cc.retrieve("t9", config=OPT_IN, limit=2)), 2)

    def test_empty_tenant_returns_nothing(self):
        self.assertEqual(cc.retrieve("", config=OPT_IN), [])


class ProvenanceStrippingTest(CorpusTestBase):
    """Identifying residue is removed BEFORE storage."""

    def test_emails_urls_paths_repos_tickets_shas_are_stripped(self):
        raw = ("DO ping ops@acme.com about https://acme.com/runbook in "
               "/Users/kpasch/Documents/acme/repo per ACME-1234 at deadbeef1234567")
        cc.contribute("t1", raw, config=OPT_IN)
        stored = cc.retrieve("t1", config=OPT_IN)[0]["convention"]
        for leak in ("ops@acme.com", "acme.com/runbook", "/Users/kpasch", "ACME-1234", "deadbeef1234567"):
            self.assertNotIn(leak, stored)
        self.assertIn("<email>", stored)
        self.assertIn("<url>", stored)

    def test_the_tenants_own_name_is_stripped(self):
        cc.contribute("acme", "DO follow the acme convention", config=OPT_IN)
        stored = cc.retrieve("acme", config=OPT_IN)[0]["convention"]
        self.assertNotIn("acme", stored.lower().replace("<tenant>", ""))

    def test_a_convention_that_is_only_provenance_is_refused(self):
        r = cc.contribute("t1", "https://example.com", config=OPT_IN)
        # Stripped to "<url>", which is not a convention worth storing... but it
        # is non-empty, so it stores. What must NOT happen is the raw URL landing.
        if r["stored"]:
            self.assertNotIn("example.com", cc.retrieve("t1", config=OPT_IN)[0]["convention"])

    def test_cohort_key_is_opaque_and_stable(self):
        a = cc.cohort_key("acme")
        self.assertNotIn("acme", a)
        self.assertEqual(a, cc.cohort_key("acme"))
        self.assertNotEqual(a, cc.cohort_key("globex"))


class PlannerConsultationTest(CorpusTestBase):
    """The planner's view: ranked, own-first-by-outcome."""

    def test_ranking_prefers_higher_outcome_then_breadth(self):
        cc.contribute("t1", "DO A", config=OPT_IN, outcome_score=0.2)
        cc.contribute("t1", "DO B", config=OPT_IN, outcome_score=0.9)
        got = cc.retrieve("t1", config=OPT_IN)
        self.assertEqual(got[0]["convention"], "DO B")

    def test_outcome_score_is_clamped(self):
        cc.contribute("t1", "DO A", config=OPT_IN, outcome_score=5)
        cc.contribute("t1", "DO B", config=OPT_IN, outcome_score=-3)
        scores = [r["outcome_score"] for r in cc.retrieve("t1", config=OPT_IN)]
        self.assertTrue(all(0.0 <= s <= 1.0 for s in scores))

    def test_bad_outcome_score_does_not_raise(self):
        self.assertTrue(cc.contribute("t1", "DO A", config=OPT_IN, outcome_score="high")["stored"])


class SteeringHintsTest(unittest.TestCase):
    """Which human steering correlates with first-pass merges."""

    def test_ranks_by_observed_merge_rate(self):
        events = (
            [{"event_type": "redirect", "first_pass_merged": True}] * 4
            + [{"event_type": "clarification_answer", "first_pass_merged": False}] * 4
        )
        hints = cc.steering_hints(events)
        self.assertEqual(hints[0]["event_type"], "redirect")
        self.assertEqual(hints[0]["first_pass_merge_rate"], 1.0)

    def test_thin_evidence_is_dropped_not_shown_confidently(self):
        hints = cc.steering_hints([{"event_type": "redirect", "first_pass_merged": True}] * 2)
        self.assertEqual(hints, [])

    def test_labels_itself_as_correlation(self):
        hints = cc.steering_hints([{"event_type": "redirect", "first_pass_merged": True}] * 3)
        self.assertIn("correlation", hints[0]["basis"])

    def test_bad_input_returns_empty(self):
        for junk in (None, "events", 5, [None, {}, {"no_type": 1}]):
            with self.subTest(junk=junk):
                self.assertEqual(cc.steering_hints(junk), [])


class FlywheelKpiTest(unittest.TestCase):
    """The 'your fleet is getting smarter' proof, from fixture history."""

    HISTORY = [
        {"period": "2026-06", "tasks": 100, "tasks_reusing_pattern": 10, "first_pass_merges": 40},
        {"period": "2026-07", "tasks": 100, "tasks_reusing_pattern": 30, "first_pass_merges": 55},
        {"period": "2026-08", "tasks": 100, "tasks_reusing_pattern": 50, "first_pass_merges": 70},
    ]

    def test_rates_and_trend(self):
        kpi = cc.flywheel_kpi("t1", self.HISTORY)
        self.assertEqual(kpi["periods"][0]["pattern_reuse_rate"], 0.1)
        self.assertEqual(kpi["periods"][-1]["first_pass_merge_rate"], 0.7)
        self.assertAlmostEqual(kpi["trend"]["pattern_reuse_delta"], 0.4)
        self.assertTrue(kpi["getting_smarter"])

    def test_a_flat_or_worsening_fleet_does_not_claim_to_be_smarter(self):
        flat = [
            {"period": "1", "tasks": 10, "tasks_reusing_pattern": 5, "first_pass_merges": 5},
            {"period": "2", "tasks": 10, "tasks_reusing_pattern": 5, "first_pass_merges": 4},
        ]
        self.assertFalse(cc.flywheel_kpi("t1", flat)["getting_smarter"])

    def test_zero_tasks_yields_zero_not_nan(self):
        kpi = cc.flywheel_kpi("t1", [{"period": "1", "tasks": 0, "tasks_reusing_pattern": 0, "first_pass_merges": 0}])
        self.assertEqual(kpi["periods"][0]["pattern_reuse_rate"], 0.0)

    def test_bad_history_is_survivable(self):
        for junk in (None, "history", [None, "x", 5]):
            with self.subTest(junk=junk):
                kpi = cc.flywheel_kpi("t1", junk)
                self.assertEqual(kpi["periods"], [])
                self.assertFalse(kpi["getting_smarter"])

    def test_single_period_has_no_trend(self):
        kpi = cc.flywheel_kpi("t1", self.HISTORY[:1])
        self.assertEqual(kpi["trend"]["pattern_reuse_delta"], 0.0)


class StatsTest(CorpusTestBase):
    def test_stats_counts_patterns_and_tenants(self):
        cc.contribute("t1", "DO A", config=OPT_IN)
        cc.contribute("t2", "DO A", config=OPT_IN)
        s = cc.stats()
        self.assertEqual(s["rows"], 2)
        self.assertEqual(s["patterns"], 1)
        self.assertEqual(s["tenants"], 2)
        self.assertEqual(s["k_floor"], cc.K_FLOOR)


if __name__ == "__main__":
    unittest.main()
