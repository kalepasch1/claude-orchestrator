#!/usr/bin/env python3
"""Focused tests for the fleet_config key gate — which env keys are disabled, and why.

_classify_key is the whole of it: it decides whether a row in fleet_config reaches
os.environ on this host, and returns the reason when it does not. Four separate
protections are stacked in it — credential markers, the safe-prefix allowlist, an open
approval card, and a host's local pin — and none of them had a test.

The credential branch is the one the 2026-08-02 plaintext-credential incident produced,
and the comment above _safe_key says in as many words that two copies of this predicate
drift and that the drift is what the incident cost. A guard nobody exercises is a guard
that has already started drifting; these pin each branch and their precedence.

Pure: no database, no network. _classify_key takes `blocked` and `pins` as arguments
precisely so it can be asked these questions directly.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fleet_control


class SafeKeyTest(unittest.TestCase):
    """The allowlist: only tuning knobs travel fleet-wide."""

    def test_orch_prefixed_tuning_keys_are_safe(self):
        for key in ["ORCH_MAX_PARALLEL", "MAX_PARALLEL_CEILING", "RAM_FLOOR_GB",
                    "DEPLOY_WINDOW_H", "OLLAMA_MODEL", "CADE_ENABLED"]:
            self.assertTrue(fleet_control._safe_key(key), key)

    def test_keys_outside_the_allowlist_are_not_safe(self):
        for key in ["HOME", "PATH", "DATABASE_URL", "SUPABASE_URL", "ANTHROPIC_BASE_URL"]:
            self.assertFalse(fleet_control._safe_key(key), key)

    def test_a_credential_marker_outranks_a_safe_prefix(self):
        # This is the incident in one assertion: an ORCH_-prefixed name is on the
        # allowlist, and it must STILL be refused when it is shaped like a credential.
        for key in ["ORCH_GITHUB_PAT", "ORCH_API_KEY", "ORCH_SESSION_TOKEN",
                    "ORCH_DB_PASSWORD", "ORCH_CLIENT_SECRET", "ORCH_VAULT_CREDENTIAL"]:
            self.assertFalse(fleet_control._safe_key(key), key)

    def test_a_non_string_key_is_refused_rather_than_raising(self):
        # This runs over every row the control plane returns; a malformed one must not
        # take the whole config load down.
        for key in [None, 42, object()]:
            self.assertFalse(fleet_control._safe_key(key))


class ClassifyKeyTest(unittest.TestCase):
    """The reason a key does not reach os.environ — or None when it does."""

    def test_a_consumable_key_classifies_as_none(self):
        self.assertIsNone(fleet_control._classify_key("ORCH_MAX_PARALLEL", "8", set(), set()))

    def test_empty_key_or_value(self):
        self.assertEqual(fleet_control._classify_key("", "8", set(), set()),
                         fleet_control.IGNORE_EMPTY)
        self.assertEqual(fleet_control._classify_key("ORCH_MAX_PARALLEL", None, set(), set()),
                         fleet_control.IGNORE_EMPTY)

    def test_credential_marker_is_checked_before_anything_else(self):
        # Ordering is the point: a credential-shaped key must report as a credential even
        # when it would also be blocked, pinned, or unsafe. The reason is what an operator
        # reads, and 'awaiting-approval' on a leaked token is the wrong story.
        reason = fleet_control._classify_key(
            "ORCH_API_KEY", "sk-live", {"ORCH_API_KEY"}, {"ORCH_API_KEY"})
        self.assertEqual(reason, fleet_control.IGNORE_CREDENTIAL)

    def test_unsafe_key_is_reported_as_unsafe(self):
        self.assertEqual(fleet_control._classify_key("HOME", "/tmp", set(), set()),
                         fleet_control.IGNORE_UNSAFE_KEY)

    def test_an_open_approval_card_blocks_a_safe_key(self):
        self.assertEqual(
            fleet_control._classify_key("ORCH_MAX_PARALLEL", "0", {"ORCH_MAX_PARALLEL"}, set()),
            fleet_control.IGNORE_APPROVAL_BLOCKED,
        )

    def test_a_local_pin_wins_over_the_fleet_value(self):
        # Pins are compared upper-cased; a host that pinned a knob keeps its own value.
        self.assertEqual(
            fleet_control._classify_key("RAM_FLOOR_GB", "2", set(), {"RAM_FLOOR_GB"}),
            fleet_control.IGNORE_PINNED,
        )

    def test_approval_block_is_checked_before_a_pin(self):
        # Both apply; the operator needs to hear about the unreviewed change first.
        self.assertEqual(
            fleet_control._classify_key(
                "ORCH_MAX_PARALLEL", "0", {"ORCH_MAX_PARALLEL"}, {"ORCH_MAX_PARALLEL"}),
            fleet_control.IGNORE_APPROVAL_BLOCKED,
        )

    def test_every_ignore_reason_is_a_distinct_non_empty_string(self):
        # These strings are logged and compared; two of them colliding would merge two
        # different failures into one report.
        reasons = [fleet_control.IGNORE_EMPTY, fleet_control.IGNORE_CREDENTIAL,
                   fleet_control.IGNORE_UNSAFE_KEY, fleet_control.IGNORE_APPROVAL_BLOCKED,
                   fleet_control.IGNORE_PINNED]
        self.assertEqual(len(set(reasons)), len(reasons))
        for r in reasons:
            self.assertIsInstance(r, str)
            self.assertTrue(r)


class EnvPinsTest(unittest.TestCase):
    """ORCH_CONFIG_ENV_PINS names the knobs this machine keeps for itself."""

    def setUp(self):
        self._saved = os.environ.get("ORCH_CONFIG_ENV_PINS")

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("ORCH_CONFIG_ENV_PINS", None)
        else:
            os.environ["ORCH_CONFIG_ENV_PINS"] = self._saved

    def test_pins_are_parsed_upper_cased_and_trimmed(self):
        os.environ["ORCH_CONFIG_ENV_PINS"] = " ram_floor_gb , MAX_PARALLEL_CEILING "
        self.assertEqual(fleet_control._env_pins(), {"RAM_FLOOR_GB", "MAX_PARALLEL_CEILING"})

    def test_no_pins_is_an_empty_set_not_an_error(self):
        os.environ["ORCH_CONFIG_ENV_PINS"] = ""
        self.assertEqual(fleet_control._env_pins(), set())


if __name__ == "__main__":
    unittest.main()
