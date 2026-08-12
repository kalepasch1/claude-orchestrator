#!/usr/bin/env python3
"""Tests for runner_generation: admission, write fencing, drain, rollout.

Proof command:  python3 -m unittest runner.tests.test_runner_generation_fencing -v

Pins the five behaviours the two-Mac incident needed and did not have:
  1. two-Mac race    — same seat, two generations; only the admitted one writes
  2. restart         — generation is monotonic across process restarts
  3. rollout         — fences with no generation are admitted ONLY pre-admission
  4. missing fields  — partial/garbage fences degrade, never raise
  5. stale writer    — block-start / allow-safe-finish is preserved
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ORCH_DB_URL", "")
os.environ.setdefault("ORCH_DB_ENABLED", "false")

import runner_generation as rg


def fence(runner="seat-a", gen=2, contract="c0ffee", sha="deadbeef", host="MacA"):
    return {"runner_id": runner, "generation": gen, "contract_hash": contract,
            "code_sha": sha, "host": host}


def admission(runner="seat-a", gen=2, contract="c0ffee"):
    return {"runner_id": runner, "generation": gen, "contract_hash": contract}


class IdentityTest(unittest.TestCase):
    """runner_id is immutable per install; generation is monotonic per process."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = (rg.RUNNER_ID_FILE, rg.GENERATION_FILE, rg._runner_id, rg._generation)
        rg.RUNNER_ID_FILE = os.path.join(self._tmp.name, "runner_id")
        rg.GENERATION_FILE = os.path.join(self._tmp.name, "runner_generation")
        rg._runner_id = None
        rg._generation = None

    def tearDown(self):
        rg.RUNNER_ID_FILE, rg.GENERATION_FILE, rg._runner_id, rg._generation = self._saved
        self._tmp.cleanup()

    def test_runner_id_is_stable_across_restarts(self):
        first = rg.runner_id()
        rg._runner_id = None  # simulate a fresh process reading the same install
        self.assertEqual(rg.runner_id(), first)

    def test_generation_is_monotonic_across_restarts(self):
        seen = []
        for _ in range(3):
            rg._generation = None
            seen.append(rg.next_generation())
        self.assertEqual(seen, [1, 2, 3])
        self.assertEqual(seen, sorted(seen))

    def test_generation_recovers_from_corrupt_state_file(self):
        with open(rg.GENERATION_FILE, "w") as fh:
            fh.write("not-a-number")
        rg._generation = None
        self.assertEqual(rg.next_generation(), 1)

    def test_generation_survives_unwritable_runtime_dir(self):
        rg.GENERATION_FILE = os.path.join(self._tmp.name, "missing", "x", "gen")
        rg._generation = None
        self.assertIsInstance(rg.next_generation(), int)  # fail-soft, no raise

    def test_fence_token_carries_all_five_fields(self):
        token = rg.fence_token()
        for key in ("runner_id", "generation", "code_sha", "contract_hash", "token"):
            self.assertIn(key, token)

    def test_fence_digest_changes_when_generation_changes(self):
        a = rg.fence_digest(fence(gen=1))
        b = rg.fence_digest(fence(gen=2))
        self.assertNotEqual(a, b)

    def test_proof_is_serializable(self):
        snapshot = rg.proof()
        self.assertEqual(snapshot["runner_id"], rg.runner_id())
        self.assertIn("fence_token", snapshot)


class TwoMacRaceTest(unittest.TestCase):
    """Same seat, two live incarnations: only the admitted generation may write."""

    def test_admitted_generation_may_claim(self):
        allowed, _ = rg.may_claim(fence(gen=2), admission(gen=2))
        self.assertTrue(allowed)

    def test_superseded_generation_may_not_claim(self):
        allowed, reason = rg.may_claim(fence(gen=1), admission(gen=2))
        self.assertFalse(allowed)
        self.assertIn(rg.STALE_GENERATION, reason)

    def test_unadmitted_ahead_generation_may_not_claim(self):
        allowed, reason = rg.may_claim(fence(gen=3), admission(gen=2))
        self.assertFalse(allowed)
        self.assertIn(rg.UNADMITTED_RUNNER, reason)

    def test_other_seat_may_not_claim_under_this_admission(self):
        allowed, reason = rg.may_claim(fence(runner="seat-b"), admission(runner="seat-a"))
        self.assertFalse(allowed)
        self.assertIn(rg.UNADMITTED_RUNNER, reason)

    def test_exactly_one_of_two_racing_macs_is_admitted(self):
        adm = admission(gen=7)
        mac_a = fence(gen=7, host="MacA")
        mac_b = fence(gen=6, host="MacB")
        verdicts = [rg.may_claim(mac_a, adm)[0], rg.may_claim(mac_b, adm)[0]]
        self.assertEqual(verdicts.count(True), 1)

    def test_contract_mismatch_is_refused(self):
        allowed, reason = rg.may_claim(fence(contract="stale00"), admission(contract="c0ffee"))
        self.assertFalse(allowed)
        self.assertIn(rg.CONTRACT_MISMATCH, reason)

    def test_all_canonical_operations_are_fenced(self):
        stale, adm = fence(gen=1), admission(gen=2)
        for check in (rg.may_claim, rg.may_integrate, rg.may_release, rg.may_mutate_canonical):
            self.assertFalse(check(stale, adm)[0], check.__name__)


class RolloutCompatibilityTest(unittest.TestCase):
    """Old runners send no generation. That is fine until admissions exist."""

    def test_legacy_fence_admitted_before_any_admission(self):
        legacy = {"runner_id": "seat-a", "code_sha": "old"}
        self.assertEqual(rg.classify(legacy, None), rg.LEGACY_PRE_ROLLOUT)
        self.assertTrue(rg.may_claim(legacy, None)[0])

    def test_legacy_fence_refused_once_admission_published(self):
        legacy = {"runner_id": "seat-a", "code_sha": "old"}
        allowed, reason = rg.may_claim(legacy, admission())
        self.assertFalse(allowed)
        self.assertIn(rg.UNADMITTED_RUNNER, reason)

    def test_new_fence_admitted_before_any_admission(self):
        self.assertEqual(rg.classify(fence(), None), rg.ADMITTED)

    def test_admission_without_generation_is_treated_as_absent(self):
        self.assertEqual(rg.normalize_admission({"runner_id": "seat-a"}), {})
        self.assertTrue(rg.may_claim(fence(), {"runner_id": "seat-a"})[0])

    def test_admission_with_unparseable_generation_is_ignored(self):
        self.assertEqual(rg.normalize_admission({"runner_id": "a", "generation": "x"}), {})

    def test_admission_without_contract_hash_skips_contract_check(self):
        adm = {"runner_id": "seat-a", "generation": 2}
        self.assertTrue(rg.may_claim(fence(contract="anything"), adm)[0])


class MissingFieldTest(unittest.TestCase):
    """Partial and hostile fences degrade to a refusal; nothing raises."""

    def test_empty_fence_is_malformed(self):
        self.assertEqual(rg.classify({}, admission()), rg.MALFORMED_FENCE)
        self.assertFalse(rg.may_claim({}, admission())[0])

    def test_none_fence_is_malformed(self):
        self.assertEqual(rg.classify(None, admission()), rg.MALFORMED_FENCE)

    def test_non_mapping_fence_is_malformed(self):
        for junk in ("string", 42, ["list"]):
            self.assertEqual(rg.classify(junk, admission()), rg.MALFORMED_FENCE)

    def test_unparseable_generation_is_dropped_not_defaulted(self):
        normalized = rg.normalize_fence({"runner_id": "a", "generation": "abc"})
        self.assertNotIn("generation", normalized)

    def test_string_generation_is_coerced(self):
        self.assertEqual(rg.normalize_fence({"runner_id": "a", "generation": "5"})["generation"], 5)

    def test_blank_fields_are_dropped(self):
        normalized = rg.normalize_fence({"runner_id": "a", "code_sha": "  ", "host": ""})
        self.assertEqual(set(normalized), {"runner_id"})


class StaleWriterTest(unittest.TestCase):
    """Block start, allow safe finish — the rule that keeps fencing safe."""

    def test_stale_writer_may_still_finish(self):
        allowed, reason = rg.may_finish(fence(gen=1), admission(gen=2))
        self.assertTrue(allowed)
        self.assertIn("safe-finish", reason)

    def test_stale_writer_may_still_write_an_artifact(self):
        self.assertTrue(rg.may("artifact", fence(gen=1), admission(gen=2))[0])

    def test_stale_writer_may_still_heartbeat(self):
        self.assertTrue(rg.may("heartbeat", fence(gen=1), admission(gen=2))[0])

    def test_stale_writer_may_not_mutate_canonical_proof(self):
        self.assertFalse(rg.may_mutate_canonical(fence(gen=1), admission(gen=2))[0])

    def test_unknown_operation_fails_closed(self):
        self.assertFalse(rg.may("delete_everything", fence(gen=1), admission(gen=2))[0])


class DrainTest(unittest.TestCase):
    """Contract-mismatched hosts drain, and the alert is durable and separate."""

    def test_no_drain_plan_for_admitted_fence(self):
        self.assertIsNone(rg.drain_plan(fence(), admission()))

    def test_no_drain_plan_for_legacy_pre_rollout(self):
        self.assertIsNone(rg.drain_plan({"runner_id": "seat-a"}, None))

    def test_drain_plan_names_both_generations(self):
        plan = rg.drain_plan(fence(gen=1), admission(gen=4))
        self.assertEqual(plan["kind"], rg.ALERT_KIND)
        self.assertEqual(plan["generation"], 1)
        self.assertEqual(plan["admitted_generation"], 4)
        self.assertEqual(plan["verdict"], rg.STALE_GENERATION)

    def test_drain_plan_names_expected_contract(self):
        plan = rg.drain_plan(fence(contract="stale00"), admission(contract="c0ffee"))
        self.assertEqual(plan["expected_contract_hash"], "c0ffee")

    def test_alert_is_recorded_in_its_own_transaction(self):
        writes = []
        ok = rg.record_drain_alert(rg.drain_plan(fence(gen=1), admission(gen=2)),
                                   insert=lambda table, row: writes.append((table, row)))
        self.assertTrue(ok)
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0][0], "runner_alerts")

    def test_alert_failure_is_fail_soft(self):
        def boom(table, row):
            raise RuntimeError("db down")
        self.assertFalse(rg.record_drain_alert(rg.drain_plan(fence(gen=1), admission(gen=2)),
                                               insert=boom))

    def test_enforce_refuses_and_alerts(self):
        writes = []
        allowed, _ = rg.enforce("claim", fence(gen=1), admission(gen=2),
                                insert=lambda t, r: writes.append(r))
        self.assertFalse(allowed)
        self.assertEqual(len(writes), 1)

    def test_enforce_allows_and_does_not_alert(self):
        writes = []
        allowed, _ = rg.enforce("claim", fence(), admission(),
                                insert=lambda t, r: writes.append(r))
        self.assertTrue(allowed)
        self.assertEqual(writes, [])

    def test_enforce_safe_finish_never_alerts(self):
        writes = []
        allowed, _ = rg.enforce("finish", fence(gen=1), admission(gen=2),
                                insert=lambda t, r: writes.append(r))
        self.assertTrue(allowed)
        self.assertEqual(writes, [])


class PausedHostGuardIntegrationTest(unittest.TestCase):
    """The drain is enforced where every train already asks permission to start."""

    def setUp(self):
        import paused_host_guard
        self.guard = paused_host_guard

    def test_drained_host_may_not_start(self):
        drained, reason = self.guard.host_is_drained(
            {"runner_id": rg.runner_id(), "generation": rg.generation() + 5})
        self.assertTrue(drained)
        self.assertIn(rg.STALE_GENERATION, reason)

    def test_admitted_host_may_start(self):
        drained, _ = self.guard.host_is_drained(
            {"runner_id": rg.runner_id(), "generation": rg.generation()})
        self.assertFalse(drained)

    def test_unknown_seat_is_fail_open(self):
        # No admission row for this seat yet: pre-rollout, so nothing is drained.
        drained, _ = self.guard.host_is_drained({})
        self.assertFalse(drained)

    def test_flag_off_costs_no_query(self):
        # may_start() is on every train's hot path; fencing must not add a query
        # until the operator flips ORCH_RUNNER_FENCING.
        saved = os.environ.pop("ORCH_RUNNER_FENCING", None)
        try:
            with patch.object(self.guard, "_pause_reason", side_effect=AssertionError("no lookup")):
                self.assertEqual(self.guard.host_is_drained(), (False, ""))
        finally:
            if saved is not None:
                os.environ["ORCH_RUNNER_FENCING"] = saved


class RuntimeContractIntegrationTest(unittest.TestCase):
    """check() now names the incarnation, not just the code it holds."""

    def test_check_reports_runner_identity(self):
        import runtime_contract
        proof = runtime_contract.check()
        self.assertEqual(proof.get("runner_id"), rg.runner_id())
        self.assertIsInstance(proof.get("generation"), int)

    def test_check_still_reports_the_contract(self):
        import runtime_contract
        proof = runtime_contract.check()
        for key in ("ok", "detail", "contract_hash", "contract_version", "code_sha"):
            self.assertIn(key, proof)


if __name__ == "__main__":
    unittest.main(verbosity=2)
