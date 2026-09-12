#!/usr/bin/env python3
"""Tests for signed_plan_execution_router.py — signed plans + economic routing."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import signed_plan_execution_router as spr


def slice_(sid="s1", files=("runner/a.py",), **kw):
    base = {"slice_id": sid, "file_scope": list(files), "tests": ["python3 -m unittest x"],
            "min_capability": 5, "max_cost_usd": 1.0}
    base.update(kw)
    return base


def plan_(slices=None, **kw):
    base = {"plan_id": "p1", "task_slug": "demo", "task_class": "build",
            "rationale": "prose that is not normative",
            "slices": list(slices or [slice_()])}
    base.update(kw)
    return base


CATALOG = [
    {"provider": "local", "model": "llama3.2:3b", "cost_per_slice": 0.0, "capability": 4},
    {"provider": "deepseek", "model": "deepseek-v4-flash", "cost_per_slice": 0.01, "capability": 6},
    {"provider": "google", "model": "gemini-4.0-flash", "cost_per_slice": 0.03, "capability": 7},
    {"provider": "claude", "model": "claude-opus-5", "cost_per_slice": 1.20, "capability": 10},
]
ALL_PROVIDERS = ["local", "deepseek", "google", "claude"]


class TestSigning(unittest.TestCase):
    def test_sign_then_verify(self):
        p = spr.sign_plan(plan_())
        self.assertTrue(spr.verify_plan(p))
        self.assertTrue(spr.assert_signed(p))

    def test_unsigned_plan_is_refused(self):
        self.assertFalse(spr.verify_plan(plan_()))
        with self.assertRaises(spr.ContractViolation):
            spr.assert_signed(plan_())

    def test_changing_file_scope_breaks_the_signature(self):
        p = spr.sign_plan(plan_())
        p["slices"][0]["file_scope"].append("runner/sneaky.py")
        self.assertFalse(spr.verify_plan(p))
        with self.assertRaises(spr.ContractViolation):
            spr.assert_signed(p)

    def test_changing_required_tests_breaks_the_signature(self):
        p = spr.sign_plan(plan_())
        p["slices"][0]["tests"] = []
        self.assertFalse(spr.verify_plan(p))

    def test_non_normative_prose_may_drift(self):
        p = spr.sign_plan(plan_())
        p["rationale"] = "the council reworded its reasoning"
        p["slices"][0]["hint"] = "look at plan_stage.py first"
        self.assertTrue(spr.verify_plan(p), "prose must not be part of the contract")

    def test_digest_is_order_independent(self):
        a = plan_([slice_("s1", ["runner/a.py", "runner/b.py"]), slice_("s2", ["runner/c.py"])])
        b = plan_([slice_("s2", ["runner/c.py"]), slice_("s1", ["runner/b.py", "runner/a.py"])])
        self.assertEqual(spr.plan_digest(a), spr.plan_digest(b))

    def test_signature_version_mismatch_is_refused(self):
        p = spr.sign_plan(plan_())
        p["signature_version"] = "spv0"
        self.assertFalse(spr.verify_plan(p))


class TestSliceScopes(unittest.TestCase):
    def test_disjoint_slices_validate(self):
        self.assertTrue(spr.validate_slices(
            [slice_("s1", ["runner/a.py"]), slice_("s2", ["runner/b.py"])]))

    def test_overlapping_file_scopes_rejected(self):
        slices = [slice_("s1", ["runner/a.py", "runner/shared.py"]),
                  slice_("s2", ["runner/shared.py"])]
        self.assertEqual(spr.overlapping_slices(slices),
                         [("s1", "s2", ["runner/shared.py"])])
        with self.assertRaises(spr.ContractViolation) as cm:
            spr.validate_slices(slices)
        self.assertIn("runner/shared.py", str(cm.exception))

    def test_path_normalization_catches_disguised_overlap(self):
        slices = [slice_("s1", ["./runner/a.py"]), slice_("s2", ["runner/a.py"])]
        self.assertTrue(spr.overlapping_slices(slices))

    def test_empty_scope_and_duplicate_ids_rejected(self):
        with self.assertRaises(spr.ContractViolation):
            spr.validate_slices([slice_("s1", [])])
        with self.assertRaises(spr.ContractViolation):
            spr.validate_slices([slice_("s1"), slice_("s1", ["runner/b.py"])])
        with self.assertRaises(spr.ContractViolation):
            spr.validate_slices([])


class TestEconomicRouting(unittest.TestCase):
    def test_cheapest_capable_available_model_wins(self):
        pick = spr.select_route(slice_(), CATALOG, ALL_PROVIDERS)
        self.assertEqual(pick["provider"], "deepseek",
                         "local is cheaper but not capable enough; claude is capable but dear")

    def test_unavailable_provider_fails_over_to_next_cheapest(self):
        pick = spr.select_route(slice_(), CATALOG, ["google", "claude"])
        self.assertEqual(pick["provider"], "google")

    def test_no_available_provider_raises(self):
        with self.assertRaises(spr.NoRouteAvailable):
            spr.select_route(slice_(), CATALOG, ["local"])

    def test_budget_cap_excludes_frontier_model(self):
        with self.assertRaises(spr.NoRouteAvailable):
            spr.select_route(slice_(min_capability=10, max_cost_usd=0.10), CATALOG, ALL_PROVIDERS)

    def test_higher_capability_requirement_climbs_the_ladder(self):
        pick = spr.select_route(slice_(min_capability=7, max_cost_usd=None), CATALOG, ALL_PROVIDERS)
        self.assertEqual(pick["provider"], "google")

    def test_route_is_deterministic(self):
        picks = {spr.select_route(slice_(), CATALOG, ALL_PROVIDERS)["provider"] for _ in range(5)}
        self.assertEqual(len(picks), 1)


class TestReviewerIndependence(unittest.TestCase):
    def test_legal_change_needs_a_different_family(self):
        self.assertTrue(spr.requires_independent_reviewer("legal"))
        rev = spr.select_reviewer(slice_(), CATALOG, ALL_PROVIDERS,
                                  implementer_provider="deepseek", task_class="legal")
        self.assertNotEqual(rev["provider"], "deepseek")

    def test_security_and_broad_and_material_all_require_independence(self):
        for tclass in ("security", "broad", "material"):
            self.assertTrue(spr.requires_independent_reviewer(tclass), tclass)

    def test_routine_build_may_reuse_the_same_family(self):
        self.assertFalse(spr.requires_independent_reviewer("build"))
        rev = spr.select_reviewer(slice_(), CATALOG, ALL_PROVIDERS,
                                  implementer_provider="deepseek", task_class="build")
        self.assertEqual(rev["provider"], "deepseek")


class TestDeviation(unittest.TestCase):
    def test_exact_match_is_within_scope(self):
        dev = spr.plan_deviation(slice_("s1", ["runner/a.py"]), ["runner/a.py"])
        self.assertTrue(dev["within_scope"])
        self.assertEqual(dev["unplanned"], [])
        self.assertEqual(dev["unwritten"], [])

    def test_unplanned_file_is_a_contract_violation(self):
        slc = slice_("s1", ["runner/a.py"])
        dev = spr.plan_deviation(slc, ["runner/a.py", "runner/b.py"])
        self.assertFalse(dev["within_scope"])
        self.assertEqual(dev["unplanned"], ["runner/b.py"])
        with self.assertRaises(spr.ContractViolation):
            spr.assert_within_scope(slc, ["runner/a.py", "runner/b.py"])

    def test_unwritten_file_is_recorded_but_not_a_violation(self):
        slc = slice_("s1", ["runner/a.py", "runner/b.py"])
        dev = spr.assert_within_scope(slc, ["runner/a.py"])
        self.assertEqual(dev["unwritten"], ["runner/b.py"])


class TestEscalation(unittest.TestCase):
    def test_low_confidence_escalates(self):
        self.assertTrue(spr.should_escalate({"confidence": 0.2}))

    def test_high_confidence_does_not(self):
        self.assertFalse(spr.should_escalate({"confidence": 0.9}))

    def test_missing_context_and_failing_tests_escalate(self):
        self.assertTrue(spr.should_escalate({"missing_context": True, "confidence": 0.99}))
        self.assertTrue(spr.should_escalate({"tests_failed": True, "confidence": 0.99}))

    def test_escalation_is_targeted_at_one_slice(self):
        req = spr.escalation_request(slice_("s7"), {"confidence": 0.1, "missing_context": True},
                                     note="cannot find the ledger table")
        self.assertEqual(req["slice_id"], "s7")
        self.assertEqual(req["scope"], "slice")
        self.assertIn("low_confidence", req["reasons"])
        self.assertIn("missing_context", req["reasons"])


class TestReceiptsAndCost(unittest.TestCase):
    def test_receipt_captures_planned_actual_model_and_cost(self):
        p = spr.sign_plan(plan_())
        r = spr.execution_receipt(p, p["slices"][0], "deepseek", "deepseek-v4-flash",
                                  ["runner/a.py"], cost_usd=0.011, latency_s=42.0,
                                  tests=["python3 -m unittest x"], tests_passed=True,
                                  state="DEPLOYED_AND_VERIFIED", reviewer_provider="google")
        self.assertTrue(r["plan_verified"])
        self.assertEqual(r["planned_files"], ["runner/a.py"])
        self.assertEqual(r["actual_files"], ["runner/a.py"])
        self.assertTrue(r["deviation"]["within_scope"])
        self.assertTrue(r["reviewer_independent"])
        self.assertEqual(r["provider"], "deepseek")
        self.assertEqual(r["cost_usd"], 0.011)

    def test_receipt_flags_a_tampered_plan_and_same_family_review(self):
        p = spr.sign_plan(plan_())
        p["slices"][0]["file_scope"] = ["runner/elsewhere.py"]
        r = spr.execution_receipt(p, p["slices"][0], "deepseek", "m",
                                  ["runner/elsewhere.py"], reviewer_provider="deepseek")
        self.assertFalse(r["plan_verified"])
        self.assertFalse(r["reviewer_independent"])

    def test_cost_per_verified_counts_wasted_spend(self):
        rows = [
            {"cost_usd": 1.00, "state": "DEPLOYED_AND_VERIFIED"},
            {"cost_usd": 0.50, "state": "QUARANTINED"},
            {"cost_usd": 0.50, "state": "DEPLOYED_AND_VERIFIED"},
        ]
        acct = spr.cost_per_deployed_and_verified(rows)
        self.assertEqual(acct["verified"], 2)
        self.assertEqual(acct["total_cost_usd"], 2.0)
        self.assertEqual(acct["cost_per_verified_usd"], 1.0)
        self.assertEqual(acct["wasted_cost_usd"], 0.5)

    def test_cost_per_verified_is_none_when_nothing_shipped(self):
        acct = spr.cost_per_deployed_and_verified([{"cost_usd": 3.0, "state": "BLOCKED"}])
        self.assertIsNone(acct["cost_per_verified_usd"])
        self.assertEqual(acct["wasted_cost_usd"], 3.0)

    def test_empty_accounting_is_safe(self):
        acct = spr.cost_per_deployed_and_verified([])
        self.assertEqual(acct["receipts"], 0)
        self.assertIsNone(acct["cost_per_verified_usd"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
