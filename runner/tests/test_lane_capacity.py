#!/usr/bin/env python3
"""Deterministic tests for lane_capacity: the pre-claim credential/capacity gate.

Covers exactly the five scenarios named in the queue item:
  1. weekly limit          -> quarantined as capacity, long cooldown, self-healing
  2. refresh failure       -> quarantined as credential, distinct cause + operator action
  3. recovery              -> a cleared account becomes claimable again
  4. all lanes down        -> should_claim() is False; claiming pauses
  5. task-attempt preserve -> preserves_attempt() is True for every fleet-side cause

Plus the property that made the outage expensive: only the UNHEALTHY account is
quarantined, and an expired OAuth session is never mistaken for exhausted capacity.
No clock sleeping, no network, no DB — every test is deterministic.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ORCH_DB_URL", "")
os.environ.setdefault("ORCH_DB_ENABLED", "false")

import lane_capacity as lc

WEEKLY = "Claude usage limit reached - your weekly limit resets at 2026-08-14T09:00Z"
OAUTH = "Failed to authenticate: OAuth session expired and could not be refreshed"
TRANSIENT = "API error 503: Overloaded, please try again"


class FakePool:
    """Minimal account_pool stand-in: same surface lane_capacity actually touches."""

    def __init__(self, accts, cooling=()):
        self.accts = accts
        self.cooling = set(cooling)
        self.exhausted_calls = []

    def _healthy(self, a):
        return (a or {}).get("name") not in self.cooling

    def mark_exhausted(self, a):
        self.exhausted_calls.append((a or {}).get("name"))
        self.cooling.add((a or {}).get("name"))
        return None


def _cap(accts, cooling=()):
    return lc.LaneCapacity(pool=FakePool(list(accts), cooling))


SUB_A = {"name": "personal-max", "type": "login"}
SUB_B = {"name": "team-max", "type": "login"}
API_A = {"name": "api-billing", "type": "api", "api_key_env": "ANTHROPIC_API_KEY_TEST"}


class ClassificationTest(unittest.TestCase):
    """Weekly exhaustion, dead OAuth and a blip must be three different answers."""

    def test_weekly_limit_is_capacity(self):
        self.assertEqual(lc.classify(WEEKLY), lc.CAUSE_WEEKLY_LIMIT)

    def test_refresh_failure_is_credential(self):
        self.assertEqual(lc.classify(OAUTH), lc.CAUSE_OAUTH_EXPIRED)

    def test_transient_provider_error_is_transient(self):
        self.assertEqual(lc.classify(TRANSIENT), lc.CAUSE_TRANSIENT)

    def test_oauth_wins_over_limit_wording(self):
        """The exact confusion that caused the outage: both phrases in one message."""
        both = "usage limit reached; also: OAuth token expired and could not be refreshed"
        self.assertEqual(lc.classify(both), lc.CAUSE_OAUTH_EXPIRED)

    def test_empty_text_is_healthy(self):
        for blank in ("", "   ", None):
            self.assertEqual(lc.classify(blank), lc.CAUSE_HEALTHY)

    def test_unrecognized_text_is_unknown_not_a_failure(self):
        self.assertEqual(lc.classify("wrote 3 files, all tests green"), lc.CAUSE_UNKNOWN)

    def test_classify_is_fail_soft_on_weird_input(self):
        self.assertEqual(lc.classify(b"OAuth session expired"), lc.CAUSE_OAUTH_EXPIRED)
        self.assertIn(lc.classify(object()), (lc.CAUSE_UNKNOWN, lc.CAUSE_HEALTHY))

    def test_reset_marker_is_extracted_when_present(self):
        self.assertIsNotNone(lc.parse_reset(WEEKLY))
        self.assertIsNone(lc.parse_reset(OAUTH))

    def test_cooldowns_differ_by_cause(self):
        self.assertGreater(lc.cooldown_for(lc.CAUSE_WEEKLY_LIMIT),
                           lc.cooldown_for(lc.CAUSE_TRANSIENT))

    def test_cooldowns_are_env_tunable(self):
        with patch.dict(os.environ, {"ORCH_LANE_TRANSIENT_COOLDOWN": "7"}):
            self.assertEqual(lc.cooldown_for(lc.CAUSE_TRANSIENT), 7)

    def test_bad_env_value_falls_back_to_default(self):
        with patch.dict(os.environ, {"ORCH_LANE_TRANSIENT_COOLDOWN": "not-a-number"}):
            self.assertEqual(lc.cooldown_for(lc.CAUSE_TRANSIENT), 120)


class OperatorSurfaceTest(unittest.TestCase):
    """Capacity state must tell the operator what to do — and leak nothing."""

    def test_oauth_names_a_concrete_operator_action(self):
        self.assertIn("login", lc.action_for(lc.CAUSE_OAUTH_EXPIRED))

    def test_self_healing_causes_have_no_operator_action(self):
        self.assertEqual(lc.action_for(lc.CAUSE_TRANSIENT), "")
        self.assertEqual(lc.action_for(lc.CAUSE_HEALTHY), "")

    def test_capacity_state_reports_reset_and_action(self):
        cap = _cap([SUB_A])
        cap.quarantine(SUB_A, WEEKLY)
        lane = cap.capacity_state()["lanes"][0]
        self.assertEqual(lane["cause"], lc.CAUSE_WEEKLY_LIMIT)
        self.assertIsNotNone(lane["reset"])
        self.assertGreater(lane["cooldown_remaining_s"], 0)
        self.assertTrue(lane["action"])

    def test_capacity_state_never_contains_credential_material(self):
        secret = "sk-ant-SUPERSECRET"
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY_TEST": secret}):
            cap = _cap([API_A])
            cap.probe(API_A, force=True)
            blob = repr(cap.capacity_state())
        self.assertNotIn(secret, blob)

    def test_missing_api_key_reports_the_var_name_not_a_value(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY_TEST", None)
            cap = _cap([API_A])
            result = cap.probe(API_A, force=True)
        self.assertEqual(result["cause"], lc.CAUSE_OAUTH_EXPIRED)
        self.assertIn("ANTHROPIC_API_KEY_TEST", result["detail"])


class QuarantineIsolationTest(unittest.TestCase):
    """Only the unhealthy account is taken out — the rest keep working."""

    def test_only_the_failing_account_is_quarantined(self):
        cap = _cap([SUB_A, SUB_B])
        cap.quarantine(SUB_A, OAUTH)
        self.assertFalse(cap.is_healthy(SUB_A))
        self.assertTrue(cap.is_healthy(SUB_B))

    def test_routing_moves_to_the_healthy_account(self):
        cap = _cap([SUB_A, SUB_B])
        cap.quarantine(SUB_A, WEEKLY)
        self.assertEqual((cap.healthy_lane() or {}).get("name"), "team-max")

    def test_dead_credential_is_not_reported_as_exhausted_capacity(self):
        """Regression guard: marking OAuth failure 'exhausted' re-offered it every 20 min."""
        pool = FakePool([SUB_A, SUB_B])
        cap = lc.LaneCapacity(pool=pool)
        cap.quarantine(SUB_A, OAUTH)
        self.assertEqual(pool.exhausted_calls, [])

    def test_weekly_exhaustion_still_forwards_to_the_account_pool(self):
        pool = FakePool([SUB_A, SUB_B])
        cap = lc.LaneCapacity(pool=pool)
        cap.quarantine(SUB_A, WEEKLY)
        self.assertEqual(pool.exhausted_calls, ["personal-max"])

    def test_subscription_lane_is_preferred_over_api_lane(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY_TEST": "x"}):
            cap = _cap([API_A, SUB_A])
            self.assertEqual((cap.healthy_lane() or {}).get("name"), "personal-max")

    def test_api_lane_is_used_when_no_subscription_lane_is_healthy(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY_TEST": "x"}):
            cap = _cap([API_A, SUB_A])
            cap.quarantine(SUB_A, WEEKLY)
            self.assertEqual((cap.healthy_lane() or {}).get("name"), "api-billing")

    def test_pool_cooldown_alone_marks_the_lane_unhealthy(self):
        cap = _cap([SUB_A, SUB_B], cooling=["personal-max"])
        self.assertFalse(cap.is_healthy(SUB_A))
        self.assertTrue(cap.is_healthy(SUB_B))


class RecoveryTest(unittest.TestCase):
    """A fixed lane must become claimable again without a restart."""

    def test_clearing_one_account_restores_it(self):
        cap = _cap([SUB_A])
        cap.quarantine(SUB_A, OAUTH)
        self.assertFalse(cap.is_healthy(SUB_A))
        cap.clear(SUB_A)
        self.assertTrue(cap.is_healthy(SUB_A))

    def test_clearing_everything_restores_claiming(self):
        cap = _cap([SUB_A, SUB_B])
        cap.quarantine(SUB_A, OAUTH)
        cap.quarantine(SUB_B, WEEKLY)
        self.assertFalse(cap.should_claim()[0])
        cap.clear()
        self.assertTrue(cap.should_claim()[0])

    def test_cooldown_expiry_restores_the_lane(self):
        with patch.dict(os.environ, {"ORCH_LANE_TRANSIENT_COOLDOWN": "0"}):
            cap = _cap([SUB_A])
            cap.quarantine(SUB_A, TRANSIENT)
            self.assertTrue(cap.is_healthy(SUB_A))

    def test_probe_result_is_cached_then_refreshed_on_force(self):
        cap = _cap([SUB_A])
        self.assertFalse(cap.probe(SUB_A, force=True)["cached"])
        self.assertTrue(cap.probe(SUB_A)["cached"])
        self.assertFalse(cap.probe(SUB_A, force=True)["cached"])

    def test_invalidate_forces_a_recheck(self):
        cap = _cap([SUB_A])
        cap.probe(SUB_A, force=True)
        cap.invalidate("personal-max")
        self.assertFalse(cap.probe(SUB_A)["cached"])


class ClaimGateTest(unittest.TestCase):
    """The whole point: pause claiming instead of burning attempts."""

    def test_claiming_allowed_while_any_lane_is_healthy(self):
        cap = _cap([SUB_A, SUB_B])
        cap.quarantine(SUB_A, WEEKLY)
        ok, reason = cap.should_claim()
        self.assertTrue(ok)
        self.assertIn("team-max", reason)

    def test_claiming_pauses_when_all_lanes_are_down(self):
        cap = _cap([SUB_A, SUB_B])
        cap.quarantine(SUB_A, WEEKLY)
        cap.quarantine(SUB_B, OAUTH)
        ok, reason = cap.should_claim()
        self.assertFalse(ok)
        self.assertIn("paused", reason)

    def test_pause_reason_names_both_distinct_causes(self):
        cap = _cap([SUB_A, SUB_B])
        cap.quarantine(SUB_A, WEEKLY)
        cap.quarantine(SUB_B, OAUTH)
        reason = cap.should_claim()[1]
        self.assertIn(lc.CAUSE_WEEKLY_LIMIT, reason)
        self.assertIn(lc.CAUSE_OAUTH_EXPIRED, reason)

    def test_capacity_state_flags_the_pause_and_lists_actions(self):
        cap = _cap([SUB_A])
        cap.quarantine(SUB_A, OAUTH)
        state = cap.capacity_state()
        self.assertTrue(state["claiming_paused"])
        self.assertEqual(state["healthy_lanes"], 0)
        self.assertTrue(state["operator_actions"])
        self.assertIsNotNone(state["paused_since"])

    def test_no_configured_accounts_does_not_stall_the_fleet(self):
        cap = _cap([])
        self.assertTrue(cap.should_claim()[0])

    def test_gate_is_fail_soft_when_the_pool_raises(self):
        class Boom:
            @property
            def accts(self):
                raise RuntimeError("pool down")

        cap = lc.LaneCapacity(pool=Boom())
        self.assertTrue(cap.should_claim()[0])

    def test_probe_error_leaves_the_lane_claimable(self):
        cap = _cap([SUB_A])
        with patch.object(cap, "_pool_healthy", side_effect=RuntimeError("boom")):
            result = cap.probe(SUB_A, force=True)
        self.assertEqual(result["cause"], lc.CAUSE_UNKNOWN)
        self.assertTrue(cap.should_claim()[0])


class AttemptPreservationTest(unittest.TestCase):
    """A fleet-side failure must never be charged to the task."""

    def test_every_fleet_side_cause_preserves_the_attempt(self):
        for cause in (lc.CAUSE_WEEKLY_LIMIT, lc.CAUSE_OAUTH_EXPIRED, lc.CAUSE_TRANSIENT):
            self.assertTrue(lc.preserves_attempt(cause), cause)

    def test_healthy_and_unknown_do_not_preserve_the_attempt(self):
        """An unrecognized failure is probably the task's own; charge it normally."""
        self.assertFalse(lc.preserves_attempt(lc.CAUSE_HEALTHY))
        self.assertFalse(lc.preserves_attempt(lc.CAUSE_UNKNOWN))

    def test_the_two_outage_log_lines_both_preserve_the_attempt(self):
        for text in (WEEKLY, OAUTH):
            self.assertTrue(lc.preserves_attempt(lc.classify(text)), text)


class ModuleSingletonTest(unittest.TestCase):
    """CLAUDE.md convention: module functions delegate to one singleton."""

    def setUp(self):
        lc._capacity = None

    def tearDown(self):
        lc._capacity = None

    def test_module_functions_share_one_instance(self):
        pool = FakePool([SUB_A, SUB_B])
        lc._capacity = lc.LaneCapacity(pool=pool)
        lc.quarantine(SUB_A, OAUTH)
        self.assertEqual((lc.healthy_lane() or {}).get("name"), "team-max")
        self.assertTrue(lc.should_claim()[0])
        lc.clear()
        self.assertTrue(lc.capacity_state()["healthy_lanes"] >= 1)

    def test_stats_is_an_alias_of_capacity_state(self):
        lc._capacity = lc.LaneCapacity(pool=FakePool([SUB_A]))
        self.assertEqual(set(lc.stats()), set(lc.capacity_state()))


if __name__ == "__main__":
    unittest.main()
