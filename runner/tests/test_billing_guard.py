"""Behavioural tests for billing_guard's pause scoping, ownership and escalation.

Two properties matter most here and both are regressions we have actually shipped:

  1. billing_guard must only ever auto-resume a pause IT placed. The old code called
     pause_arbiter.recheck() on every clean run, which would happily lift a global pause
     that the waste guard, the cost circuit, or a human STOP had put there.
  2. billing_guard must stop re-tripping on the same cause forever. Three identical
     consecutive trips escalate exactly one material approval card and then go quiet,
     instead of re-pausing the fleet every cycle with nobody watching.

Every test points CLAUDE_ORCH_HOME at a fresh temp dir so the on-disk streak state is
isolated per test, and patches `db` so no test can ever write a real approval row.
"""
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import billing_guard


def _subscription_guard(keys=(), api_allowed=False, subscription_mode=True, overflow=False):
    return types.SimpleNamespace(
        audit=lambda: {
            "subscription_mode": subscription_mode,
            "api_allowed": api_allowed,
            "api_keys_present": list(keys),
            "overflow": overflow,
        },
        enforce=lambda: {"stripped": list(keys)},
    )


class BillingGuardBase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="billing_guard_test_")
        self.addCleanup(shutil.rmtree, self.home, True)
        patcher = patch.dict(os.environ, {"CLAUDE_ORCH_HOME": self.home})
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_state(self, **kwargs):
        with open(os.path.join(self.home, "billing_guard_state.json"), "w") as f:
            json.dump(kwargs, f)

    def read_state(self):
        return billing_guard._load_state()


class CauseKeyTest(BillingGuardBase):
    def test_identical_findings_produce_identical_key(self):
        f = ["REAL API spend today $41.10 > trip $2.00"]
        self.assertEqual(billing_guard._cause_key(f), billing_guard._cause_key(list(f)))

    def test_drifting_dollar_amounts_are_the_same_cause(self):
        a = ["REAL API spend today $41.10 > trip $2.00"]
        b = ["REAL API spend today $87.63 > trip $2.00"]
        self.assertEqual(billing_guard._cause_key(a), billing_guard._cause_key(b))

    def test_different_causes_produce_different_keys(self):
        a = ["REAL API spend today $41.10 > trip $2.00"]
        b = ["subscription_guard audit failed: boom"]
        self.assertNotEqual(billing_guard._cause_key(a), billing_guard._cause_key(b))

    def test_key_is_order_independent(self):
        a = ["alpha finding", "beta finding"]
        self.assertEqual(billing_guard._cause_key(a), billing_guard._cause_key(list(reversed(a))))

    def test_empty_findings_do_not_raise(self):
        self.assertIsInstance(billing_guard._cause_key([]), str)
        self.assertIsInstance(billing_guard._cause_key(None), str)

    def test_key_is_short_and_stable_shape(self):
        key = billing_guard._cause_key(["anything at all"])
        self.assertEqual(len(key), 16)
        self.assertTrue(all(c in "0123456789abcdef" for c in key))


class StateHelpersTest(BillingGuardBase):
    def test_missing_state_file_loads_as_empty_dict(self):
        self.assertEqual(billing_guard._load_state(), {})

    def test_corrupt_state_file_loads_as_empty_dict(self):
        with open(os.path.join(self.home, "billing_guard_state.json"), "w") as f:
            f.write("{ this is not json")
        self.assertEqual(billing_guard._load_state(), {})

    def test_non_dict_state_file_loads_as_empty_dict(self):
        with open(os.path.join(self.home, "billing_guard_state.json"), "w") as f:
            json.dump(["a", "list"], f)
        self.assertEqual(billing_guard._load_state(), {})

    def test_save_then_load_roundtrips(self):
        billing_guard._save_state({"cause_key": "abc", "streak": 2})
        self.assertEqual(billing_guard._load_state()["streak"], 2)

    def test_save_to_unwritable_home_is_fail_soft(self):
        with patch.dict(os.environ, {"CLAUDE_ORCH_HOME": "/proc/nonexistent-billing-guard"}):
            billing_guard._save_state({"streak": 1})  # must not raise

    def test_state_file_follows_env_without_reimport(self):
        self.assertTrue(billing_guard._state_file().startswith(self.home))


class OwnershipGateTest(BillingGuardBase):
    """A clean billing run must never lift a pause billing_guard did not place."""

    def _run_clean(self, recheck_return=None, recheck_side_effect=None):
        arbiter = types.SimpleNamespace(
            recheck=MagicMock(return_value=recheck_return or {"action": "lifted", "reason": "cleared"},
                              side_effect=recheck_side_effect),
            pause=MagicMock(),
        )
        mods = {
            "subscription_guard": _subscription_guard(),
            "claude_cli": types.SimpleNamespace(status=lambda: {"usd_last_day": 0}),
            "pause_arbiter": arbiter,
            "kill_switch": types.SimpleNamespace(pause=MagicMock(), resume=MagicMock()),
            "db": types.SimpleNamespace(insert=MagicMock()),
        }
        with patch.dict(sys.modules, mods):
            out = billing_guard.run()
        return out, arbiter

    def test_no_prior_state_means_no_recheck(self):
        out, arbiter = self._run_clean()
        self.assertTrue(out["ok"])
        self.assertFalse(out["resumed"])
        arbiter.recheck.assert_not_called()

    def test_not_holding_pause_means_no_recheck(self):
        self.write_state(cause_key="k", streak=1, holding_pause=False)
        out, arbiter = self._run_clean()
        self.assertFalse(out["resumed"])
        arbiter.recheck.assert_not_called()

    def test_foreign_pause_is_never_lifted(self):
        self.write_state(cause_key="k", streak=1, holding_pause=True, pause_by="waste_guard")
        out, arbiter = self._run_clean()
        self.assertFalse(out["resumed"])
        arbiter.recheck.assert_not_called()

    def test_own_pause_is_lifted_when_cause_cleared(self):
        self.write_state(cause_key="k", streak=1, holding_pause=True, pause_by="billing_guard")
        out, arbiter = self._run_clean()
        self.assertTrue(out["resumed"])
        arbiter.recheck.assert_called_once()

    def test_own_pause_not_lifted_when_arbiter_declines(self):
        self.write_state(cause_key="k", streak=1, holding_pause=True, pause_by="billing_guard")
        out, arbiter = self._run_clean(recheck_return={"action": "none", "reason": "not clear yet"})
        self.assertFalse(out["resumed"])
        arbiter.recheck.assert_called_once()

    def test_arbiter_exception_is_fail_soft(self):
        self.write_state(cause_key="k", streak=1, holding_pause=True, pause_by="billing_guard")
        out, _ = self._run_clean(recheck_side_effect=RuntimeError("arbiter down"))
        self.assertTrue(out["ok"])
        self.assertFalse(out["resumed"])

    def test_clean_run_drops_holding_flag_but_keeps_streak(self):
        self.write_state(cause_key="k", streak=2, holding_pause=True, pause_by="billing_guard")
        self._run_clean()
        st = self.read_state()
        self.assertFalse(st["holding_pause"])
        self.assertEqual(st["streak"], 2)
        self.assertNotIn("pause_by", st)


class TripAndEscalationTest(BillingGuardBase):
    def _run_trip(self, usd=99, keys=(), strict=False, arbiter=None, db=None,
                  kill_switch=None, status_exc=None):
        arbiter = arbiter or types.SimpleNamespace(pause=MagicMock(), recheck=MagicMock())
        db = db or types.SimpleNamespace(insert=MagicMock())
        kill_switch = kill_switch or types.SimpleNamespace(pause=MagicMock(), resume=MagicMock())
        if status_exc:
            def _status():
                raise status_exc
        else:
            def _status():
                return {"usd_last_day": usd}
        mods = {
            "subscription_guard": _subscription_guard(keys=keys),
            "claude_cli": types.SimpleNamespace(status=_status),
            "pause_arbiter": arbiter,
            "db": db,
            "kill_switch": kill_switch,
        }
        env = {"ORCH_BILLING_KEY_PRESENCE_PAUSES": "true" if strict else "false"}
        with patch.dict(sys.modules, mods), patch.dict(os.environ, env):
            out = billing_guard.run()
        return out, arbiter, db, kill_switch

    def test_real_spend_pauses_via_arbiter_with_no_ttl(self):
        out, arbiter, _, _ = self._run_trip(usd=99)
        self.assertFalse(out["ok"])
        self.assertIn("REAL API spend", out["findings"][0])
        arbiter.pause.assert_called_once()
        call = arbiter.pause.call_args
        self.assertEqual(call.args[0], "billing_real_spend_or_audit_failure")
        self.assertIsNone(call.kwargs.get("ttl_s"))

    def test_pause_is_scoped_by_billing_guard_and_carries_cause_key(self):
        out, arbiter, _, _ = self._run_trip(usd=99)
        call = arbiter.pause.call_args
        self.assertEqual(call.kwargs.get("by"), "billing_guard")
        self.assertIn(f"[cause={out['cause_key']}]", call.args[1])

    def test_strict_key_presence_pauses_via_arbiter_with_ttl(self):
        out, arbiter, _, _ = self._run_trip(usd=0, keys=["ANTHROPIC_API_KEY"], strict=True)
        self.assertFalse(out["ok"])
        arbiter.pause.assert_called_once()
        call = arbiter.pause.call_args
        self.assertEqual(call.args[0], "billing_key_presence")
        self.assertEqual(call.kwargs.get("ttl_s"), 900)

    def test_key_presence_in_subscription_mode_warns_and_resumes_without_pausing(self):
        self.write_state(cause_key="k", streak=1, holding_pause=True, pause_by="billing_guard")
        arbiter = types.SimpleNamespace(
            recheck=MagicMock(return_value={"action": "lifted", "reason": "billing_key_presence cleared"}),
            pause=MagicMock(),
        )
        mods = {
            "subscription_guard": _subscription_guard(keys=["ANTHROPIC_API_KEY"]),
            "claude_cli": types.SimpleNamespace(status=lambda: {"usd_last_day": 0}),
            "pause_arbiter": arbiter,
            "kill_switch": types.SimpleNamespace(pause=MagicMock(), resume=MagicMock()),
            "db": types.SimpleNamespace(insert=MagicMock()),
        }
        with patch.dict(sys.modules, mods), patch.dict(
                os.environ, {"ORCH_BILLING_KEY_PRESENCE_PAUSES": "false"}):
            out = billing_guard.run()

        self.assertTrue(out["ok"])
        self.assertTrue(out["resumed"])
        self.assertIn("ANTHROPIC_API_KEY", out["warnings"][0])
        arbiter.pause.assert_not_called()
        arbiter.recheck.assert_called_once()

    def test_audit_failure_is_not_key_presence_only(self):
        out, arbiter, _, _ = self._run_trip(usd=0, status_exc=RuntimeError("cli down"))
        self.assertFalse(out["ok"])
        self.assertEqual(arbiter.pause.call_args.args[0], "billing_real_spend_or_audit_failure")

    def test_first_trip_records_streak_one_and_ownership(self):
        out, _, _, _ = self._run_trip(usd=99)
        self.assertEqual(out["streak"], 1)
        st = self.read_state()
        self.assertTrue(st["holding_pause"])
        self.assertEqual(st["pause_by"], "billing_guard")

    def test_second_identical_trip_still_pauses_and_increments_streak(self):
        self._run_trip(usd=99)
        out, arbiter, _, _ = self._run_trip(usd=99)
        self.assertEqual(out["streak"], 2)
        self.assertFalse(out["suppressed"])
        arbiter.pause.assert_called_once()

    def test_third_identical_trip_stops_re_pausing(self):
        self._run_trip(usd=99)
        self._run_trip(usd=99)
        out, arbiter, _, kill_switch = self._run_trip(usd=99)
        self.assertEqual(out["streak"], billing_guard.ESCALATE_AFTER)
        self.assertTrue(out["suppressed"])
        self.assertTrue(out["escalated"])
        arbiter.pause.assert_not_called()
        kill_switch.pause.assert_not_called()

    def test_third_identical_trip_files_exactly_one_escalation_card(self):
        self._run_trip(usd=99)
        self._run_trip(usd=99)
        out, _, db, _ = self._run_trip(usd=99)
        self.assertTrue(out["escalation_filed"])
        db.insert.assert_called_once()
        table, row = db.insert.call_args.args
        self.assertEqual(table, "approvals")
        self.assertEqual(row["kind"], "material")
        self.assertIn("re-tripped", row["title"])

    def test_fourth_identical_trip_files_no_second_card(self):
        for _ in range(3):
            self._run_trip(usd=99)
        out, arbiter, db, _ = self._run_trip(usd=99)
        self.assertTrue(out["suppressed"])
        self.assertFalse(out["escalation_filed"])
        db.insert.assert_not_called()
        arbiter.pause.assert_not_called()

    def test_drifting_spend_amount_still_counts_as_the_same_cause(self):
        self._run_trip(usd=41.10)
        self._run_trip(usd=87.63)
        out, arbiter, _, _ = self._run_trip(usd=12.01)
        self.assertTrue(out["suppressed"])
        arbiter.pause.assert_not_called()

    def test_different_cause_resets_the_streak_and_pauses_again(self):
        self._run_trip(usd=99)
        self._run_trip(usd=99)
        out, arbiter, _, _ = self._run_trip(usd=0, status_exc=RuntimeError("cli down"))
        self.assertEqual(out["streak"], 1)
        self.assertFalse(out["suppressed"])
        arbiter.pause.assert_called_once()

    def test_stale_streak_is_not_carried_forward(self):
        self.write_state(cause_key=billing_guard._cause_key(
            ["REAL API spend today $99.00 > trip $2.00"]),
            streak=5, escalated=True, holding_pause=False, last_trip=0)
        out, arbiter, _, _ = self._run_trip(usd=99)
        self.assertEqual(out["streak"], 1)
        self.assertFalse(out["suppressed"])
        arbiter.pause.assert_called_once()

    def test_streak_survives_an_intervening_clean_run(self):
        # trip -> auto-resume -> trip is the pathological loop; a clean cycle in between
        # must not reset the counter, or the guard can re-pause forever without escalating.
        self._run_trip(usd=99)
        self._run_trip(usd=99)
        clean_mods = {
            "subscription_guard": _subscription_guard(),
            "claude_cli": types.SimpleNamespace(status=lambda: {"usd_last_day": 0}),
            "pause_arbiter": types.SimpleNamespace(
                recheck=MagicMock(return_value={"action": "lifted", "reason": "cleared"}),
                pause=MagicMock()),
            "kill_switch": types.SimpleNamespace(pause=MagicMock(), resume=MagicMock()),
            "db": types.SimpleNamespace(insert=MagicMock()),
        }
        with patch.dict(sys.modules, clean_mods):
            billing_guard.run()
        out, arbiter, _, _ = self._run_trip(usd=99)
        self.assertEqual(out["streak"], 3)
        self.assertTrue(out["suppressed"])
        arbiter.pause.assert_not_called()

    def test_arbiter_failure_falls_back_to_kill_switch(self):
        arbiter = types.SimpleNamespace(pause=MagicMock(side_effect=RuntimeError("down")),
                                        recheck=MagicMock())
        out, _, _, kill_switch = self._run_trip(usd=99, arbiter=arbiter)
        kill_switch.pause.assert_called_once()
        self.assertEqual(kill_switch.pause.call_args.kwargs.get("by"), "billing_guard")
        self.assertTrue(self.read_state()["holding_pause"])

    def test_total_pause_failure_records_no_ownership(self):
        arbiter = types.SimpleNamespace(pause=MagicMock(side_effect=RuntimeError("down")),
                                        recheck=MagicMock())
        kill_switch = types.SimpleNamespace(pause=MagicMock(side_effect=RuntimeError("down")),
                                            resume=MagicMock())
        out, _, _, _ = self._run_trip(usd=99, arbiter=arbiter, kill_switch=kill_switch)
        self.assertFalse(out["ok"])
        st = self.read_state()
        self.assertFalse(st["holding_pause"])
        self.assertIsNone(st["pause_by"])

    def test_unowned_pause_after_failed_trip_is_not_auto_resumed(self):
        arbiter = types.SimpleNamespace(pause=MagicMock(side_effect=RuntimeError("down")),
                                        recheck=MagicMock())
        kill_switch = types.SimpleNamespace(pause=MagicMock(side_effect=RuntimeError("down")),
                                            resume=MagicMock())
        self._run_trip(usd=99, arbiter=arbiter, kill_switch=kill_switch)
        clean_arbiter = types.SimpleNamespace(
            recheck=MagicMock(return_value={"action": "lifted"}), pause=MagicMock())
        mods = {
            "subscription_guard": _subscription_guard(),
            "claude_cli": types.SimpleNamespace(status=lambda: {"usd_last_day": 0}),
            "pause_arbiter": clean_arbiter,
            "kill_switch": types.SimpleNamespace(pause=MagicMock(), resume=MagicMock()),
            "db": types.SimpleNamespace(insert=MagicMock()),
        }
        with patch.dict(sys.modules, mods):
            out = billing_guard.run()
        self.assertFalse(out["resumed"])
        clean_arbiter.recheck.assert_not_called()

    def test_escalation_db_failure_is_fail_soft(self):
        self._run_trip(usd=99)
        self._run_trip(usd=99)
        db = types.SimpleNamespace(insert=MagicMock(side_effect=RuntimeError("db down")))
        out, _, _, _ = self._run_trip(usd=99, db=db)
        self.assertTrue(out["suppressed"])
        self.assertFalse(out["escalation_filed"])

    def test_normal_trip_card_includes_cause_key(self):
        out, _, db, _ = self._run_trip(usd=99)
        row = db.insert.call_args.args[1]
        self.assertIn(f"cause_key={out['cause_key']}", row["why"])


if __name__ == "__main__":
    unittest.main()
