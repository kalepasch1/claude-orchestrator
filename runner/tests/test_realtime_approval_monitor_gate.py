#!/usr/bin/env python3
"""The real-time monitor's auto-approve gate must fail closed.

`AUTO_APPROVE_RULES` approves every pending card whose kind is not legal or secret. That
is an extremely wide door for a background thread to hold open, and the only thing
narrowing it was `_is_alarm`, which matched five phrases against three fields. A card
titled "vendor step 3" whose body said "wire $12,000" passed all of it — and a card
asking for two approvers got one, from a thread.

These tests pin the three narrowings: money/production/destructive language anywhere in
the card blocks auto-approval, a two-key card is never single-key approved, and every
unreadable input resolves to manual rather than to approved.
"""
from __future__ import annotations

import os
import sys
import types
import unittest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

# A private `db` stub, installed only for THIS import.
#
# This was `if "db" not in sys.modules: sys.modules["db"] = stub`, which is wrong
# in both directions and test_sys_modules_shadowing exists to catch it: under
# pytest conftest imports the real db first, so the guard SKIPS and realtime_approval_monitor
# binds the live client; run standalone, the guard fires and leaves a stub in
# sys.modules that every test collected afterwards then receives. The guard had
# to go, not just move.
#
# import_with_stubs gives this module a private copy bound to the stub and
# restores sys.modules exactly as it found it, so nothing leaks either way.
import env_during_import  # noqa: E402

_stub = types.ModuleType("db")
_stub.select = lambda *a, **k: []
_stub.update = lambda *a, **k: None
_stub.insert = lambda *a, **k: None

rtm = env_during_import.import_with_stubs("realtime_approval_monitor", db=_stub)


def _card(**overrides):
    card = {"id": "c1", "status": "pending", "kind": "code", "title": "routine change"}
    card.update(overrides)
    return card


class AutoApproveStillWorksTest(unittest.TestCase):
    def test_an_ordinary_pending_card_is_still_auto_approved(self):
        action, _ = rtm._check_auto_rules(_card())
        self.assertEqual(action, "auto_approve")

    def test_secret_cards_are_still_manual(self):
        action, reason = rtm._check_auto_rules(_card(kind="secret"))
        self.assertEqual(action, "manual")
        self.assertIn("secret", reason)

    def test_novel_legal_cards_are_still_manual(self):
        action, _ = rtm._check_auto_rules(_card(kind="legal", legal_risk_level="novel"))
        self.assertEqual(action, "manual")

    def test_the_original_alarm_patterns_still_fire(self):
        for phrase in ("key leak", "secret leak", "billing firewall"):
            action, _ = rtm._check_auto_rules(_card(title=f"incident: {phrase}"))
            self.assertEqual(action, "manual", phrase)


class MoneyAndProductionTest(unittest.TestCase):
    def test_money_movement_in_the_body_is_caught(self):
        card = _card(title="vendor step 3", body="wire transfer of $12,000 to supplier")
        action, reason = rtm._check_auto_rules(card)
        self.assertEqual(action, "manual", "a background thread must not approve a wire")
        self.assertIn("alarm", reason)

    def test_a_dollar_transfer_in_the_title_is_caught(self):
        action, _ = rtm._check_auto_rules(_card(title="transfer $4,000 to ops"))
        self.assertEqual(action, "manual")

    def test_production_release_is_caught(self):
        action, _ = rtm._check_auto_rules(_card(detail="deploy to production now"))
        self.assertEqual(action, "manual")

    def test_destructive_database_language_is_caught(self):
        for phrase in ("drop table users", "truncate the ledger", "revoke the token"):
            action, _ = rtm._check_auto_rules(_card(description=phrase))
            self.assertEqual(action, "manual", phrase)

    def test_outbound_communication_is_caught(self):
        action, _ = rtm._check_auto_rules(_card(payload="send email to the customer list"))
        self.assertEqual(action, "manual")


class TwoKeyTest(unittest.TestCase):
    def test_a_two_key_card_is_never_single_key_approved(self):
        action, reason = rtm._check_auto_rules(_card(approvals_required=2))
        self.assertEqual(action, "manual")
        self.assertIn("second approver", reason)

    def test_a_two_key_card_with_a_second_approver_is_allowed(self):
        action, _ = rtm._check_auto_rules(_card(approvals_required=2,
                                                second_approver="someone"))
        self.assertEqual(action, "auto_approve")

    def test_one_key_is_unaffected(self):
        action, _ = rtm._check_auto_rules(_card(approvals_required=1))
        self.assertEqual(action, "auto_approve")

    def test_an_unreadable_requirement_fails_closed(self):
        action, _ = rtm._check_auto_rules(_card(approvals_required="two"))
        self.assertEqual(action, "manual")


class FailClosedTest(unittest.TestCase):
    def test_a_non_dict_card_is_manual_not_approved(self):
        for bad in (None, "card", 5, []):
            action, _ = rtm._check_auto_rules(bad)
            self.assertEqual(action, "manual", repr(bad))

    def test_a_card_whose_fields_explode_is_treated_as_alarming(self):
        class Hostile(dict):
            def get(self, *args, **kwargs):
                raise RuntimeError("boom")

        self.assertTrue(rtm._is_alarm(Hostile()))

    def test_check_auto_rules_never_raises(self):
        for card in (_card(title=None), _card(body=object()), _card(value=b"\xff"), {}):
            try:
                rtm._check_auto_rules(card)
            except Exception as exc:  # noqa: BLE001 — the assertion IS "no exception"
                self.fail(f"_check_auto_rules raised {type(exc).__name__}: {exc}")

    def test_disabling_auto_rules_still_short_circuits(self):
        saved = rtm.AUTO_RULES_ENABLED
        try:
            rtm.AUTO_RULES_ENABLED = False
            action, reason = rtm._check_auto_rules(_card())
            self.assertEqual(action, "manual")
            self.assertIn("disabled", reason)
        finally:
            rtm.AUTO_RULES_ENABLED = saved


class PollIntervalTest(unittest.TestCase):
    """POLL_INTERVAL was a bare int() at module scope: one bad fleet push of the key
    raised ValueError mid-import and took down every importer of the monitor."""

    KEY = "ORCH_RTMON_POLL_INTERVAL"

    def setUp(self):
        self._saved = os.environ.get(self.KEY)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop(self.KEY, None)
        else:
            os.environ[self.KEY] = self._saved

    def test_a_malformed_interval_falls_back_instead_of_raising(self):
        for bad in ("abc", "", "   ", "-5", "0"):
            os.environ[self.KEY] = bad
            self.assertEqual(rtm._env_int(self.KEY, 300), 300, bad)

    def test_a_valid_interval_is_used(self):
        os.environ[self.KEY] = "45"
        self.assertEqual(rtm._env_int(self.KEY, 300), 45)

    def test_an_absent_interval_uses_the_default(self):
        os.environ.pop(self.KEY, None)
        self.assertEqual(rtm._env_int(self.KEY, 300), 300)


if __name__ == "__main__":
    unittest.main()
