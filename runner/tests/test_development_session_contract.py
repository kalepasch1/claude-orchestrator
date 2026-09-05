#!/usr/bin/env python3
"""Contracts for the portfolio-wide development session fabric.

Proof: python3 -m unittest runner.tests.test_development_session_contract -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import development_session_contract as dsc  # noqa: E402


class TestVersioning(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(dsc.parse_version("1.0"), (1, 0))
        self.assertEqual(dsc.parse_version(" 2.11 "), (2, 11))

    def test_parse_version_is_fail_soft(self):
        for bad in (None, "", "v1", "1", "1.0.0", 1.0, [], {}):
            self.assertIsNone(dsc.parse_version(bad), bad)

    def test_same_version_is_compatible(self):
        self.assertTrue(dsc.is_compatible(dsc.CONTRACT_VERSION))

    def test_major_bump_is_incompatible(self):
        self.assertFalse(dsc.is_compatible("2.0", "1.0"))
        self.assertFalse(dsc.is_compatible("1.0", "2.0"))

    def test_newer_minor_writer_is_refused_by_older_reader(self):
        self.assertFalse(dsc.is_compatible("1.4", "1.0"))

    def test_older_minor_writer_is_accepted(self):
        self.assertTrue(dsc.is_compatible("1.0", "1.4"))

    def test_garbage_version_is_not_compatible(self):
        self.assertFalse(dsc.is_compatible(None))
        self.assertFalse(dsc.is_compatible("nope"))


class TestStates(unittest.TestCase):
    def test_all_nine_states_are_pinned(self):
        self.assertEqual(dsc.STATES, (
            "CREATED", "PLANNING", "PLAN_REVIEW", "EXECUTING", "VERIFYING",
            "INTEGRATING", "RELEASING", "DEPLOYED_AND_VERIFIED", "BLOCKED",
        ))

    def test_done_and_merged_are_not_session_states(self):
        self.assertNotIn("DONE", dsc.STATES)
        self.assertNotIn("MERGED", dsc.STATES)

    def test_done_and_merged_are_not_production(self):
        for state in dsc.NON_PRODUCTION_TASK_STATES:
            self.assertFalse(dsc.is_production_state(state), state)

    def test_only_deployed_and_verified_is_production(self):
        self.assertTrue(dsc.is_production_state("DEPLOYED_AND_VERIFIED"))
        for state in dsc.STATES:
            if state != "DEPLOYED_AND_VERIFIED":
                self.assertFalse(dsc.is_production_state(state), state)

    def test_happy_path_is_walkable(self):
        path = ["CREATED", "PLANNING", "PLAN_REVIEW", "EXECUTING",
                "VERIFYING", "INTEGRATING", "RELEASING", "DEPLOYED_AND_VERIFIED"]
        for a, b in zip(path, path[1:]):
            self.assertTrue(dsc.can_transition(a, b), f"{a} -> {b}")

    def test_cannot_skip_verification(self):
        self.assertFalse(dsc.can_transition("EXECUTING", "RELEASING"))
        self.assertFalse(dsc.can_transition("PLANNING", "DEPLOYED_AND_VERIFIED"))

    def test_every_state_can_block(self):
        for state in dsc.STATES:
            if state in ("BLOCKED", "DEPLOYED_AND_VERIFIED"):
                continue
            self.assertTrue(dsc.can_transition(state, "BLOCKED"), state)

    def test_blocked_can_resume_anywhere_but_terminal(self):
        self.assertTrue(dsc.can_transition("BLOCKED", "EXECUTING"))
        self.assertFalse(dsc.can_transition("BLOCKED", "DEPLOYED_AND_VERIFIED"))

    def test_terminal_state_has_no_forward_transition(self):
        self.assertEqual(dsc.allowed_transitions("DEPLOYED_AND_VERIFIED"), ())

    def test_unknown_state_is_fail_soft_and_closed(self):
        self.assertEqual(dsc.allowed_transitions("NOPE"), ())
        self.assertEqual(dsc.allowed_transitions(None), ())
        self.assertFalse(dsc.can_transition("NOPE", "EXECUTING"))
        self.assertFalse(dsc.can_transition("CREATED", None))


class TestIdentityAndFencing(unittest.TestCase):
    def test_known_adapters_normalize(self):
        self.assertEqual(dsc.normalize_adapter("  Claude-Cowork "), "claude-cowork")

    def test_unusable_adapter_becomes_unknown(self):
        for bad in (None, "", "   ", 5, "has spaces"):
            self.assertEqual(dsc.normalize_adapter(bad), "unknown", bad)

    def test_valid_runner_identity(self):
        self.assertTrue(dsc.validate_runner_identity(
            {"host": "mac-studio", "generation": 3, "adapter": "codex"}))

    def test_runner_identity_requires_generation(self):
        v = dsc.validate_runner_identity({"host": "mac-studio"})
        self.assertFalse(v.ok)
        self.assertTrue(any("generation" in r for r in v.reasons))

    def test_runner_identity_rejects_bool_generation(self):
        self.assertFalse(dsc.validate_runner_identity({"host": "h", "generation": True}).ok)

    def test_runner_identity_is_fail_soft(self):
        self.assertFalse(dsc.validate_runner_identity(None).ok)
        self.assertFalse(dsc.validate_runner_identity("mac").ok)

    def test_fencing_token_is_deterministic(self):
        self.assertEqual(dsc.fencing_token("abc", 4), "abc:4")
        self.assertEqual(dsc.fencing_token("abc", 4), dsc.fencing_token("abc", 4))

    def test_fencing_token_survives_junk_generation(self):
        self.assertEqual(dsc.fencing_token("abc", None), "abc:0")
        self.assertEqual(dsc.fencing_token("abc", -9), "abc:0")

    def test_current_token_is_accepted(self):
        self.assertTrue(dsc.is_fencing_token_current("s1:5", "s1", 5))
        self.assertTrue(dsc.is_fencing_token_current("s1:6", "s1", 5))

    def test_stale_generation_is_fenced_off(self):
        self.assertFalse(dsc.is_fencing_token_current("s1:4", "s1", 5))

    def test_token_from_another_session_is_refused(self):
        self.assertFalse(dsc.is_fencing_token_current("s2:9", "s1", 5))

    def test_unparseable_token_fails_closed(self):
        for bad in (None, "", "s1", "s1:x", 7):
            self.assertFalse(dsc.is_fencing_token_current(bad, "s1", 1), bad)


class TestShas(unittest.TestCase):
    def test_is_sha(self):
        self.assertTrue(dsc.is_sha("6a3e6515"))
        self.assertTrue(dsc.is_sha("59b85efe" + "0" * 32))

    def test_is_sha_rejects_junk(self):
        for bad in (None, "", "zzzzzzz", "abc", 12345678, "6a3e6515" * 6):
            self.assertFalse(dsc.is_sha(bad), bad)

    def test_base_and_artifact_required_by_default(self):
        self.assertTrue(dsc.validate_shas({"base_sha": "abc1234", "artifact_sha": "def5678"}))

    def test_missing_sha_is_reported_not_raised(self):
        v = dsc.validate_shas({"base_sha": "abc1234"})
        self.assertFalse(v.ok)
        self.assertTrue(any("artifact_sha" in r for r in v.reasons))

    def test_unknown_sha_field_is_reported(self):
        v = dsc.validate_shas({"base_sha": "abc1234"}, require=("nope_sha",))
        self.assertFalse(v.ok)


class TestEvents(unittest.TestCase):
    def _event(self, **over):
        e = {"session_id": "s1", "seq": 1, "kind": "session.created",
             "idempotency_key": "k1", "contract_version": dsc.CONTRACT_VERSION,
             "payload": {}}
        e.update(over)
        return e

    def test_valid_event(self):
        self.assertTrue(dsc.validate_event(self._event()))

    def test_seq_must_be_positive_int(self):
        for bad in (0, -1, "1", 1.0, True, None):
            self.assertFalse(dsc.validate_event(self._event(seq=bad)).ok, bad)

    def test_idempotency_key_is_required(self):
        v = dsc.validate_event(self._event(idempotency_key=""))
        self.assertFalse(v.ok)
        self.assertTrue(any("idempotency_key" in r for r in v.reasons))

    def test_unknown_kind_is_reported(self):
        self.assertFalse(dsc.validate_event(self._event(kind="made.up")).ok)

    def test_incompatible_version_is_reported(self):
        self.assertFalse(dsc.validate_event(self._event(contract_version="9.9")).ok)

    def test_payload_must_be_a_mapping(self):
        self.assertFalse(dsc.validate_event(self._event(payload=["a"])).ok)

    def test_event_validation_is_fail_soft(self):
        self.assertFalse(dsc.validate_event(None).ok)
        self.assertFalse(dsc.validate_event("event").ok)

    def test_next_seq(self):
        self.assertEqual(dsc.next_seq(0), 1)
        self.assertEqual(dsc.next_seq(41), 42)

    def test_next_seq_is_fail_soft(self):
        for bad in (None, "x", -5, [],):
            self.assertEqual(dsc.next_seq(bad), 1, bad)

    def test_no_gaps_in_dense_sequence(self):
        self.assertEqual(dsc.find_seq_gaps([1, 2, 3, 4]), ())

    def test_gaps_are_found(self):
        self.assertEqual(dsc.find_seq_gaps([1, 2, 5]), (3, 4))

    def test_gap_detection_ignores_junk(self):
        self.assertEqual(dsc.find_seq_gaps([]), ())
        self.assertEqual(dsc.find_seq_gaps([1, None, "2", 3]), (2,))


class TestProofReceipts(unittest.TestCase):
    def _receipt(self, **over):
        r = {"kind": "test", "command": "python3 -m unittest runner.tests.test_x",
             "exit_code": 0, "artifact_sha": "6a3e6515"}
        r.update(over)
        return r

    def test_valid_receipt(self):
        self.assertTrue(dsc.validate_proof_receipt(self._receipt()))
        self.assertTrue(dsc.is_passing_proof(self._receipt()))

    def test_receipt_requires_artifact_sha(self):
        v = dsc.validate_proof_receipt(self._receipt(artifact_sha=None))
        self.assertFalse(v.ok)

    def test_nonzero_exit_is_not_a_passing_proof(self):
        self.assertFalse(dsc.is_passing_proof(self._receipt(exit_code=1)))

    def test_asserted_never_counts_as_proof(self):
        r = self._receipt(kind="asserted")
        self.assertTrue(dsc.validate_proof_receipt(r).ok)
        self.assertFalse(dsc.is_passing_proof(r))

    def test_unreproducible_command_is_reported(self):
        self.assertFalse(dsc.validate_proof_receipt(self._receipt(command="ok")).ok)

    def test_receipt_validation_is_fail_soft(self):
        self.assertFalse(dsc.validate_proof_receipt(None).ok)
        self.assertFalse(dsc.is_passing_proof(None))


class TestSteeringDecisions(unittest.TestCase):
    def test_valid_decision(self):
        self.assertTrue(dsc.validate_steering_decision(
            {"decision": "continue", "actor": "planner", "rationale": "plan holds"}))

    def test_rationale_is_required(self):
        v = dsc.validate_steering_decision({"decision": "revise", "actor": "qa"})
        self.assertFalse(v.ok)
        self.assertTrue(any("rationale" in r for r in v.reasons))

    def test_owner_only_decisions_refuse_a_machine_actor(self):
        for decision in dsc.OWNER_ONLY_DECISIONS:
            v = dsc.validate_steering_decision(
                {"decision": decision, "actor": "coder-bot",
                 "actor_kind": "agent", "rationale": "because"})
            self.assertFalse(v.ok, decision)

    def test_owner_may_make_owner_only_decisions(self):
        self.assertTrue(dsc.validate_steering_decision(
            {"decision": "rollback", "actor": "kalepasch1",
             "actor_kind": "owner", "rationale": "bad release"}))

    def test_unknown_decision_is_refused(self):
        self.assertFalse(dsc.validate_steering_decision(
            {"decision": "yolo", "actor": "x", "rationale": "y"}).ok)

    def test_decision_validation_is_fail_soft(self):
        self.assertFalse(dsc.validate_steering_decision(None).ok)


class TestClosure(unittest.TestCase):
    def test_merged_cannot_close_a_session(self):
        v = dsc.validate_closure({"state": "MERGED"})
        self.assertFalse(v.ok)
        self.assertTrue(any("not a session state" in r for r in v.reasons))

    def test_done_cannot_close_a_session(self):
        self.assertFalse(dsc.validate_closure({"state": "DONE"}).ok)

    def test_non_terminal_close_needs_only_a_known_state(self):
        self.assertTrue(dsc.validate_closure({"state": "BLOCKED"}))

    def test_deployed_requires_all_three_shas_and_a_passing_proof(self):
        session = {"state": "DEPLOYED_AND_VERIFIED", "base_sha": "abc1234",
                   "artifact_sha": "def5678", "release_sha": "9999abc"}
        proof = {"kind": "deploy-check", "command": "curl -sf https://example.test",
                 "exit_code": 0, "artifact_sha": "def5678"}
        self.assertTrue(dsc.validate_closure(session, [proof]))

    def test_deployed_without_release_sha_is_refused(self):
        session = {"state": "DEPLOYED_AND_VERIFIED", "base_sha": "abc1234",
                   "artifact_sha": "def5678"}
        proof = {"kind": "test", "command": "python3 -m unittest x",
                 "exit_code": 0, "artifact_sha": "def5678"}
        self.assertFalse(dsc.validate_closure(session, [proof]).ok)

    def test_deployed_without_any_passing_proof_is_refused(self):
        session = {"state": "DEPLOYED_AND_VERIFIED", "base_sha": "abc1234",
                   "artifact_sha": "def5678", "release_sha": "9999abc"}
        self.assertFalse(dsc.validate_closure(session, []).ok)
        self.assertFalse(dsc.validate_closure(session, None).ok)

    def test_closure_is_fail_soft(self):
        self.assertFalse(dsc.validate_closure(None).ok)
        self.assertFalse(dsc.validate_closure({"state": "NOPE"}).ok)


class TestRollbackAndRollout(unittest.TestCase):
    def test_rollback_reopens_at_integrating(self):
        out = dsc.rollback({"state": "DEPLOYED_AND_VERIFIED", "release_sha": "9999abc"})
        self.assertEqual(out["state"], dsc.INTEGRATING)

    def test_rollback_clears_release_but_keeps_the_audit_trail(self):
        out = dsc.rollback({"state": "DEPLOYED_AND_VERIFIED", "base_sha": "abc1234",
                            "artifact_sha": "def5678", "release_sha": "9999abc"})
        self.assertIsNone(out["release_sha"])
        self.assertEqual(out["base_sha"], "abc1234")
        self.assertEqual(out["artifact_sha"], "def5678")
        self.assertEqual(out["rolled_back_from"], "DEPLOYED_AND_VERIFIED")

    def test_rollback_does_not_mutate_the_input(self):
        session = {"state": "RELEASING", "release_sha": "9999abc"}
        dsc.rollback(session)
        self.assertEqual(session["state"], "RELEASING")

    def test_rollback_is_fail_soft(self):
        self.assertEqual(dsc.rollback(None)["state"], dsc.INTEGRATING)
        self.assertIsNone(dsc.rollback("junk")["rolled_back_from"])

    def test_rollout_plan_is_ordered_migration_first(self):
        plan = dsc.rollout_plan()
        self.assertTrue(plan["compatible"])
        self.assertIn("migration", plan["steps"][0])
        self.assertIn("writers", plan["steps"][2])
        self.assertEqual(plan["contract_version"], dsc.CONTRACT_VERSION)

    def test_rollout_plan_flags_an_unparseable_writer(self):
        self.assertFalse(dsc.rollout_plan("nope")["compatible"])


class TestModuleHygiene(unittest.TestCase):
    def test_contract_module_imports_nothing_from_the_orchestrator(self):
        """Every layer depends on this module, so it must never be the import that fails."""
        import ast
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "development_session_contract.py")
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            tree = ast.parse(fh.read())
        stdlib = {"os", "re", "time", "typing", "__future__"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertIn(alias.name.split(".")[0], stdlib, alias.name)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                self.assertIn((node.module or "").split(".")[0], stdlib, node.module)


if __name__ == "__main__":
    unittest.main()
