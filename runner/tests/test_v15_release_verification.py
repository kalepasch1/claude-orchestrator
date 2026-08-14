import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import v15_release_verification as rv


def all_gates(ok=True):
    return rv.GateResults(correctness=ok, privacy=ok, safety=ok,
                          cost_ok=ok, tail_latency_ok=ok)


class TestNoDeployPath(unittest.TestCase):
    """The separation this module exists to keep."""

    def test_module_exposes_no_deploy_or_push_entry_point(self):
        for forbidden in ("deploy", "push", "merge", "release", "rollout", "apply_migration"):
            self.assertFalse(hasattr(rv, forbidden), f"must not expose {forbidden}()")

    def test_migration_plan_plans_but_does_not_apply(self):
        plan = rv.migration_plan([{"name": "m1", "reviewed": True, "idempotent": True,
                                   "path": "established"}])
        self.assertTrue(plan["all_clear"])
        self.assertIn("release train", plan["note"])

    def test_report_states_that_no_deploy_was_performed(self):
        report = rv.release_report([rv.Dependency("d", True, True)],
                                   list(rv.FLEET_APPS), rv.EvidenceLog())
        self.assertEqual(report["deploys_performed"], 0)


class TestReadiness(unittest.TestCase):
    def test_unmerged_dependency_blocks_verification(self):
        deps = [rv.Dependency("a", merged=True, tests_green=True),
                rv.Dependency("b", merged=False)]
        state = rv.readiness(deps)
        self.assertFalse(state["ready"])
        self.assertEqual(state["unmerged"], ["b"])

    def test_merged_but_red_dependency_blocks_verification(self):
        deps = [rv.Dependency("a", merged=True, tests_green=False)]
        self.assertFalse(rv.readiness(deps)["ready"])
        self.assertEqual(rv.readiness(deps)["failing"], ["a"])

    def test_all_merged_and_green_is_ready(self):
        deps = [rv.Dependency("a", True, True), rv.Dependency("b", True, True)]
        self.assertTrue(rv.readiness(deps)["ready"])

    def test_an_empty_dependency_set_is_not_ready(self):
        """Nothing to verify is not the same as everything verified."""
        self.assertFalse(rv.readiness([])["ready"])

    def test_require_ready_raises_rather_than_returning_false(self):
        with self.assertRaises(rv.DependenciesNotReady):
            rv.require_ready([rv.Dependency("a", merged=False)])


class TestCoverage(unittest.TestCase):
    def test_all_ten_apps_plus_orchestrator_are_required(self):
        self.assertEqual(len(rv.FLEET_APPS), 10)
        self.assertIn("orchestrator", rv.FLEET_APPS)

    def test_missing_app_is_reported(self):
        result = rv.coverage([a for a in rv.FLEET_APPS if a != "vigil"])
        self.assertFalse(result["complete"])
        self.assertEqual(result["missing"], ["vigil"])

    def test_full_coverage_is_complete(self):
        self.assertTrue(rv.coverage(list(rv.FLEET_APPS))["complete"])

    def test_unknown_apps_do_not_count_toward_coverage(self):
        self.assertFalse(rv.coverage(["not-an-app"] * 20)["complete"])


class TestUnverifiedClaims(unittest.TestCase):
    def test_a_missing_measurement_is_unverified_not_a_default_ratio(self):
        result = rv.compare_to_baseline(None, None)
        self.assertEqual(result["status"], "unverified")
        self.assertIsNone(result["ratio"])

    def test_a_zero_baseline_does_not_divide(self):
        self.assertEqual(rv.compare_to_baseline(0.0, 1.0)["status"], "unverified")

    def test_a_real_measurement_reports_the_observed_ratio(self):
        result = rv.compare_to_baseline(baseline=10.0, measured=5.0)
        self.assertEqual(result["status"], "measured")
        self.assertAlmostEqual(result["ratio"], 2.0)
        self.assertFalse(result["meets_advertised_range"])   # 2x is not 50x

    def test_the_advertised_range_is_labelled_a_target_not_a_result(self):
        result = rv.compare_to_baseline(100.0, 1.0)
        self.assertTrue(result["meets_advertised_range"])
        self.assertIn("TARGETS", result["note"])
        self.assertEqual(result["advertised_range"], [50.0, 500.0])

    def test_claims_without_measurements_are_explicitly_labelled(self):
        labelled = rv.label_unverified_claims(
            ["50x faster retrieval", "2x fewer retransmissions"],
            {"2x fewer retransmissions": rv.compare_to_baseline(10.0, 5.0)})
        by_claim = {c["claim"]: c["status"] for c in labelled}
        self.assertEqual(by_claim["50x faster retrieval"], "unverified")
        self.assertEqual(by_claim["2x fewer retransmissions"], "measured")


class TestGatesAndPromotion(unittest.TestCase):
    def test_all_five_gates_must_pass(self):
        self.assertEqual(len(rv.GateResults.ORDER), 5)
        for gate in rv.GateResults.ORDER:
            results = all_gates(True)
            setattr(results, gate, False)
            self.assertEqual(rv.evaluate_gates(results)["failed_gates"], [gate])

    def test_correctness_failure_is_reported_before_cost(self):
        results = all_gates(True)
        results.correctness = False
        results.cost_ok = False
        self.assertEqual(rv.evaluate_gates(results)["failed_gates"],
                         ["correctness", "cost_ok"])

    def test_promotion_advances_exactly_one_stage(self):
        decision = rv.promote("speculative_chains", "canary", all_gates(True))
        self.assertTrue(decision["promoted"])
        self.assertEqual(decision["next_stage"], "rollout")

    def test_a_failed_gate_blocks_promotion(self):
        results = all_gates(True)
        results.privacy = False
        decision = rv.promote("holographic_retrieval", "canary", results)
        self.assertFalse(decision["promoted"])
        self.assertEqual(decision["current_stage"], decision["next_stage"])
        self.assertIn("privacy", decision["failed_gates"])

    def test_the_final_stage_cannot_be_promoted_further(self):
        decision = rv.promote("causal_attention", "general", all_gates(True))
        self.assertFalse(decision["promoted"])
        self.assertTrue(decision["at_final_stage"])

    def test_an_unknown_stage_is_refused(self):
        with self.assertRaises(ValueError):
            rv.promote("x", "everywhere", all_gates(True))

    def test_require_promotable_raises_with_the_failing_gates(self):
        results = all_gates(True)
        results.safety = False
        with self.assertRaises(rv.PromotionRefused) as ctx:
            rv.require_promotable("anomaly_curriculum", "canary", results)
        self.assertIn("safety", str(ctx.exception))


class TestMigrationGate(unittest.TestCase):
    def test_unreviewed_migration_is_rejected(self):
        plan = rv.migration_plan([{"name": "m", "reviewed": False,
                                   "idempotent": True, "path": "established"}])
        self.assertFalse(plan["all_clear"])
        self.assertIn("not_reviewed", plan["rejected"][0]["reasons"])

    def test_non_idempotent_migration_is_rejected(self):
        plan = rv.migration_plan([{"name": "m", "reviewed": True,
                                   "idempotent": False, "path": "established"}])
        self.assertIn("not_idempotent", plan["rejected"][0]["reasons"])

    def test_a_migration_bypassing_the_established_path_is_rejected(self):
        plan = rv.migration_plan([{"name": "m", "reviewed": True,
                                   "idempotent": True, "path": "manual_psql"}])
        self.assertIn("bypasses_established_migration_path", plan["rejected"][0]["reasons"])


class TestImmutableEvidence(unittest.TestCase):
    def test_chain_verifies_when_intact(self):
        log = rv.EvidenceLog()
        for i in range(4):
            log.append("gate_result", f"cap{i}", {"passed": True}, at=1000 + i)
        self.assertTrue(log.verify()["intact"])
        self.assertEqual(log.verify()["records"], 4)

    def test_a_tampered_payload_is_detected(self):
        log = rv.EvidenceLog()
        log.append("gate_result", "cap", {"passed": False}, at=1000)
        log.append("gate_result", "cap2", {"passed": True}, at=1001)
        original = log.records()[0]
        # Rewrite history: flip the recorded result, keep the stored digest.
        log._records[0] = rv.EvidenceRecord(
            original.seq, original.kind, original.subject, {"passed": True},
            original.at, original.prev_hash, original.digest)
        verdict = log.verify()
        self.assertFalse(verdict["intact"])
        self.assertEqual(verdict["broken"][0]["reason"], "payload_tampered")

    def test_a_broken_link_is_detected(self):
        log = rv.EvidenceLog()
        a = log.append("x", "s", {"v": 1}, at=1)
        b = log.append("x", "s", {"v": 2}, at=2)
        log._records[1] = rv.EvidenceRecord(
            b.seq, b.kind, b.subject, b.payload, b.at, "deadbeef" * 4, b.digest)
        self.assertEqual(log.verify()["broken"][0]["reason"], "broken_link")

    def test_promotion_decisions_are_recorded_as_evidence(self):
        log = rv.EvidenceLog()
        rv.promote("metabolic_budget", "canary", all_gates(True), evidence=log)
        records = log.records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].kind, "promotion_decision")
        self.assertTrue(records[0].payload["promoted"])
        self.assertTrue(log.verify()["intact"])

    def test_an_empty_log_is_trivially_intact(self):
        self.assertTrue(rv.EvidenceLog().verify()["intact"])


if __name__ == "__main__":
    unittest.main()
