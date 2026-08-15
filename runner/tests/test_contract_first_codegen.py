import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import contract_first_codegen as cg


def donor(slug, intent, merged=True, score=0.95, vertical="generic"):
    return cg.Donor(slug=slug, intent=intent, diff=f"--- diff for {slug}",
                    merged=merged, outcome_score=score, vertical=vertical)


class TestTransplantDiscipline(unittest.TestCase):
    def test_a_close_match_above_the_floor_is_transplanted(self):
        candidates = [donor("d1", "add rate limiting to the login endpoint")]
        result = cg.transplant("add rate limiting to the login endpoint",
                               "recipient", candidates)
        self.assertEqual(result["donor"], "d1")
        self.assertGreaterEqual(result["score"], cg.SIMILARITY_FLOOR)

    def test_a_weak_match_is_refused_rather_than_adapted(self):
        """Adapting an ill-fitting diff is how a tumor grows."""
        candidates = [donor("d1", "rewrite the billing invoice PDF renderer")]
        with self.assertRaises(cg.NoDonor) as ctx:
            cg.transplant("add rate limiting to login", "recipient", candidates)
        self.assertIn("below the 0.55 floor", str(ctx.exception))

    def test_the_raised_floor_is_the_spec_value(self):
        self.assertEqual(cg.SIMILARITY_FLOOR, 0.55)

    def test_an_unmerged_candidate_is_never_a_donor(self):
        """An unmerged diff is not a proven organ, it is an untested one."""
        candidates = [donor("d1", "identical intent text here", merged=False)]
        with self.assertRaises(cg.NoDonor):
            cg.transplant("identical intent text here", "r", candidates)

    def test_donor_selection_is_deterministic_on_ties(self):
        a = donor("aaa", "same intent text")
        b = donor("bbb", "same intent text")
        first, _ = cg.select_donor("same intent text", [a, b])
        second, _ = cg.select_donor("same intent text", [b, a])
        self.assertEqual(first.slug, second.slug)

    def test_no_candidates_at_all_is_refused_cleanly(self):
        with self.assertRaises(cg.NoDonor):
            cg.transplant("anything", "r", [])

    def test_the_ledger_records_provenance(self):
        ledger = cg.DispositionLedger()
        cg.transplant("add rate limiting to login endpoint", "recipient",
                      [donor("d1", "add rate limiting to login endpoint")], ledger)
        provenance = ledger.provenance("recipient")
        self.assertEqual(len(provenance), 1)
        self.assertEqual(provenance[0].donor_slug, "d1")

    def test_similarity_is_symmetric_and_bounded(self):
        a, b = "add rate limiting", "rate limiting added"
        self.assertAlmostEqual(cg.similarity(a, b), cg.similarity(b, a))
        self.assertLessEqual(cg.similarity(a, a), 1.0000001)
        self.assertEqual(cg.similarity("", "x"), 0.0)


class TestContractFirst(unittest.TestCase):
    def contract(self):
        return cg.build_contract("adds_two", ("def add(a: int, b: int) -> int",),
                                 ("assert add(1, 2) == 3",))

    def test_the_contract_is_emitted_before_implementation(self):
        contract = self.contract()
        self.assertIn("def test_adds_two", contract.test_source)
        self.assertIn("assert add(1, 2) == 3", contract.test_source)
        self.assertIn("def add(a: int, b: int) -> int", contract.test_source)

    def test_a_contract_with_no_assertions_is_refused(self):
        """A test that cannot fail is not a spec."""
        with self.assertRaises(ValueError):
            cg.build_contract("x", ("sig",), ())

    def test_a_contract_needs_a_name_and_signatures(self):
        with self.assertRaises(ValueError):
            cg.build_contract("", ("sig",), ("assert True",))
        with self.assertRaises(ValueError):
            cg.build_contract("x", (), ("assert True",))

    def test_an_implementation_is_refused_if_the_contract_never_failed(self):
        contract = cg.observe_contract_run(self.contract(), passed=True)
        with self.assertRaises(cg.ContractViolation) as ctx:
            cg.accept_implementation(contract, passes_now=True)
        self.assertIn("decoration", str(ctx.exception))

    def test_red_then_green_is_accepted(self):
        contract = cg.observe_contract_run(self.contract(), passed=False)
        result = cg.accept_implementation(contract, passes_now=True)
        self.assertTrue(result["accepted"])
        self.assertEqual(result["signatures"], ["def add(a: int, b: int) -> int"])

    def test_still_failing_is_not_accepted(self):
        contract = cg.observe_contract_run(self.contract(), passed=False)
        result = cg.accept_implementation(contract, passes_now=False)
        self.assertFalse(result["accepted"])

    def test_contract_digest_changes_with_content(self):
        a = cg.build_contract("x", ("s",), ("assert 1",))
        b = cg.build_contract("x", ("s",), ("assert 2",))
        self.assertNotEqual(a.digest(), b.digest())


class TestGoldenPaths(unittest.TestCase):
    def test_only_top_decile_merged_shards_become_templates(self):
        donors = [donor("great", "i", score=0.95, vertical="payments"),
                  donor("mediocre", "i", score=0.40, vertical="payments"),
                  donor("unmerged", "i", merged=False, score=0.99, vertical="payments")]
        templates = cg.distil_golden_paths(donors)
        self.assertEqual(templates["payments"]["sample_size"], 1)
        self.assertEqual(templates["payments"]["exemplar"], "great")

    def test_one_template_per_vertical(self):
        donors = [donor("a", "i", vertical="payments"),
                  donor("b", "i", vertical="identity")]
        self.assertEqual(sorted(cg.distil_golden_paths(donors)), ["identity", "payments"])

    def test_no_qualifying_shards_yields_no_template(self):
        self.assertEqual(cg.distil_golden_paths([donor("a", "i", score=0.1)]), {})


class TestStrategyAwareness(unittest.TestCase):
    def strategy(self, approved=True):
        return cg.Strategy(name="sweepstakes", approved=approved,
                           required_flows=("AMOE", "state_gate"),
                           forbidden=("purchase_required",))

    def test_an_unapproved_strategy_injects_no_context(self):
        """Generating against an unsigned structure is worse than generic."""
        context = cg.strategy_context(self.strategy(approved=False))
        self.assertIsNone(context["strategy"])
        self.assertIn("not approved", context["reason"])

    def test_an_approved_strategy_becomes_shard_context(self):
        context = cg.strategy_context(self.strategy())
        self.assertEqual(context["strategy"], "sweepstakes")
        self.assertIn("AMOE", context["required_flows"])

    def test_compliant_output_passes(self):
        generated = "def entry(): amoe_path(); state_gate(user)"
        result = cg.check_compliance(self.strategy(), generated)
        self.assertTrue(result["compliant"])

    def test_missing_required_flow_is_reported(self):
        result = cg.check_compliance(self.strategy(), "def entry(): state_gate(user)")
        self.assertFalse(result["compliant"])
        self.assertEqual(result["missing_required"], ["AMOE"])

    def test_forbidden_construct_is_reported(self):
        generated = "def entry(): amoe(); state_gate(); purchase_required()"
        result = cg.check_compliance(self.strategy(), generated)
        self.assertFalse(result["compliant"])
        self.assertEqual(result["forbidden_present"], ["purchase_required"])

    def test_compliance_is_not_checked_against_an_unapproved_strategy(self):
        result = cg.check_compliance(self.strategy(approved=False), "anything")
        self.assertFalse(result["checked"])


if __name__ == "__main__":
    unittest.main()
