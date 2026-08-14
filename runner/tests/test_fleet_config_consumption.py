#!/usr/bin/env python3
"""fleet_config rows that are stored but never consumed must say so.

load_config logged every key it APPLIED and nothing about the keys it dropped, so a knob
pushed into fleet_config that the loader refuses looked exactly like one that worked: the
row is there, the dashboard shows it, nothing happens. The key names in
test_the_live_offenders_are_classified_as_ignored are real rows from the live table.
"""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import fleet_control


class FakeDB:
    def __init__(self, rows):
        self.rows = rows

    def select(self, table, params=None):
        assert table == "fleet_config"
        return [dict(r) for r in self.rows]

    def update(self, *a, **k):
        return None

    def insert(self, *a, **k):
        return None


def _rows(pairs):
    return [{"key": k, "value": v} for k, v in pairs]


class ConfigConsumptionTest(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        self._db = fleet_control.db
        self._approval = fleet_control.config_approval
        fleet_control.config_approval = types.SimpleNamespace(blocked_keys=lambda: set())
        # This host's real runner/.env pins several keys (MERGE_TRAIN_SCAN_LIMIT among
        # them). Clear the pin list so the suite tests the code rather than the machine.
        os.environ["ORCH_CONFIG_ENV_PINS"] = ""
        fleet_control._applied_config.clear()
        fleet_control._reported_ignored.clear()
        fleet_control._last_consumption.update(applied={}, ignored={}, at=None)

    def tearDown(self):
        fleet_control.db = self._db
        fleet_control.config_approval = self._approval
        os.environ.clear()
        os.environ.update(self._env)
        fleet_control._applied_config.clear()
        fleet_control._reported_ignored.clear()

    def _load(self, pairs):
        fleet_control.db = FakeDB(_rows(pairs))
        return fleet_control.load_config()

    # --- applied keys still work exactly as before ----------------------------------
    def test_a_safe_key_is_applied_and_reported_as_applied(self):
        self._load([("ORCH_MAX_PARALLEL", "12")])
        self.assertEqual(os.environ["ORCH_MAX_PARALLEL"], "12")
        report = fleet_control.config_consumption()
        self.assertEqual(report["applied"], {"ORCH_MAX_PARALLEL": "12"})
        self.assertEqual(report["ignored"], {})

    def test_return_value_still_counts_applied_keys(self):
        self.assertEqual(self._load([("ORCH_A", "1"), ("ORCH_B", "2")]), 2)

    def test_an_unsafe_key_does_not_reach_the_environment(self):
        self._load([("AUTOPILOT_SWEEP_LIMIT", "40")])
        self.assertNotIn("AUTOPILOT_SWEEP_LIMIT", os.environ)

    # --- the reporting this task exists for -----------------------------------------
    def test_unsafe_prefix_is_named_with_a_reason(self):
        self._load([("AUTOPILOT_SWEEP_LIMIT", "40")])
        self.assertEqual(fleet_control.config_consumption()["ignored"],
                         {"AUTOPILOT_SWEEP_LIMIT": fleet_control.IGNORE_UNSAFE_KEY})

    def test_credential_marker_outranks_a_safe_prefix(self):
        # ORCH_ is a safe prefix, but a TOKEN-shaped key must still be refused, and the
        # reason must say credential rather than the vaguer unsafe-key.
        self._load([("ORCH_GIT_TOKEN", "abc123")])
        self.assertEqual(fleet_control.config_consumption()["ignored"],
                         {"ORCH_GIT_TOKEN": fleet_control.IGNORE_CREDENTIAL})
        self.assertNotIn("ORCH_GIT_TOKEN", os.environ)

    def test_credential_reason_does_not_leak_the_value(self):
        self._load([("ORCH_API_KEY", "sk-super-secret")])
        report = fleet_control.config_consumption()
        self.assertNotIn("sk-super-secret", repr(report))

    def test_approval_blocked_key_is_named(self):
        fleet_control.config_approval = types.SimpleNamespace(
            blocked_keys=lambda: {"ORCH_MAX_PARALLEL"})
        self._load([("ORCH_MAX_PARALLEL", "99")])
        self.assertEqual(fleet_control.config_consumption()["ignored"],
                         {"ORCH_MAX_PARALLEL": fleet_control.IGNORE_APPROVAL_BLOCKED})

    def test_pinned_key_is_reported_as_not_consumed_from_the_db(self):
        # A pin is deliberate, but the DB value still did not take effect — the operator
        # asking "why didn't my push land" needs to see it.
        os.environ["ORCH_CONFIG_ENV_PINS"] = "RAM_FLOOR_GB"
        os.environ["RAM_FLOOR_GB"] = "6"
        self._load([("RAM_FLOOR_GB", "1.0")])
        self.assertEqual(fleet_control.config_consumption()["ignored"],
                         {"RAM_FLOOR_GB": fleet_control.IGNORE_PINNED})
        self.assertEqual(os.environ["RAM_FLOOR_GB"], "6", "the pin must still win")

    def test_null_value_is_named(self):
        self._load([("ORCH_MAX_PARALLEL", None)])
        self.assertEqual(fleet_control.config_consumption()["ignored"],
                         {"ORCH_MAX_PARALLEL": fleet_control.IGNORE_EMPTY})

    def test_applied_and_ignored_are_reported_together(self):
        self._load([("ORCH_MAX_PARALLEL", "12"), ("GEMINI_MODEL", "gemini-2.5-flash")])
        report = fleet_control.config_consumption()
        self.assertEqual(report["applied"], {"ORCH_MAX_PARALLEL": "12"})
        self.assertEqual(report["ignored"],
                         {"GEMINI_MODEL": fleet_control.IGNORE_UNSAFE_KEY})

    def test_the_live_offenders_are_classified_as_ignored(self):
        # Real rows sitting in fleet_config on 2026-08-06, every one inert.
        offenders = ["AUTOPILOT_BLOCKER_INTERVAL", "AUTOPILOT_RANK_INTERVAL",
                     "AUTOPILOT_RECOVERY_INTERVAL", "AUTOPILOT_RELEASE_BLOCKER_INTERVAL",
                     "AUTOPILOT_RELEASE_TRAIN_ONLY_HOTLANE", "AUTOPILOT_SWEEP_LIMIT",
                     "CONFIDENCE_GATE", "CONFIDENCE_THRESHOLD", "GEMINI_MODEL",
                     "GEMINI_CHEAP_MODEL", "OPENAI_STRONG_MODEL", "OPENAI_FAST_MODEL",
                     "OPENAI_CHEAP_MODEL", "PROMOTION_STATE", "PREWARM_N",
                     "PREVIEW_FEATURE_X"]
        self._load([(k, "x") for k in offenders])
        ignored = fleet_control.config_consumption()["ignored"]
        for key in offenders:
            self.assertEqual(ignored.get(key), fleet_control.IGNORE_UNSAFE_KEY, key)

    def test_families_the_allowlist_does_cover_are_not_flagged(self):
        # The 2026-07-30 fix added these prefixes; the report must not re-accuse them.
        for key in ("OLLAMA_KEEP_ALIVE", "COMMITTEE_WEB_EVIDENCE", "LEGAL_DOCKET_BATCH",
                    "MERGE_TRAIN_SCAN_LIMIT", "RELEASE_MIN_BATCH", "QUEUE_GEN_CEILING",
                    "RAM_HARD_PCT", "PER_TASK_GB", "MAX_PARALLEL"):
            with self.subTest(key=key):
                fleet_control._reported_ignored.clear()
                self._load([(key, "x")])
                self.assertEqual(fleet_control.config_consumption()["ignored"], {}, key)

    # --- log discipline --------------------------------------------------------------
    def test_each_ignored_key_is_logged_once_not_every_loop(self):
        import io
        pairs = [("AUTOPILOT_SWEEP_LIMIT", "40")]
        buf = io.StringIO()
        real_stderr, sys.stderr = sys.stderr, buf
        try:
            for _ in range(5):
                self._load(pairs)
        finally:
            sys.stderr = real_stderr
        self.assertEqual(buf.getvalue().count("STORED BUT NOT APPLIED"), 1)

    def test_a_changed_reason_is_logged_again(self):
        import io
        buf = io.StringIO()
        real_stderr, sys.stderr = sys.stderr, buf
        try:
            self._load([("ORCH_MAX_PARALLEL", None)])            # null-value
            fleet_control.config_approval = types.SimpleNamespace(
                blocked_keys=lambda: {"ORCH_MAX_PARALLEL"})
            self._load([("ORCH_MAX_PARALLEL", "9")])             # now approval-blocked
        finally:
            sys.stderr = real_stderr
        self.assertEqual(buf.getvalue().count("STORED BUT NOT APPLIED"), 2)

    # --- fail-soft -------------------------------------------------------------------
    def test_a_dead_database_does_not_raise_and_still_reports(self):
        class DeadDB:
            def select(self, *a, **k):
                raise RuntimeError("supabase unreachable")

        fleet_control.db = DeadDB()
        self.assertEqual(fleet_control.load_config(), 0)
        self.assertEqual(fleet_control.config_consumption()["ignored"], {})

    def test_report_is_a_copy_callers_cannot_corrupt(self):
        self._load([("ORCH_MAX_PARALLEL", "12")])
        report = fleet_control.config_consumption()
        report["applied"]["ORCH_MAX_PARALLEL"] = "tampered"
        self.assertEqual(fleet_control.config_consumption()["applied"]["ORCH_MAX_PARALLEL"], "12")

    def test_report_carries_a_timestamp(self):
        self.assertIsNone(fleet_control.config_consumption()["at"])
        self._load([("ORCH_MAX_PARALLEL", "12")])
        self.assertIsNotNone(fleet_control.config_consumption()["at"])


class ClassifyKeyTest(unittest.TestCase):
    """_classify_key must mirror load_config's conditions, in the same order."""

    def test_none_means_the_key_will_be_consumed(self):
        self.assertIsNone(fleet_control._classify_key("ORCH_X", "1", set(), set()))

    def test_credential_is_checked_before_prefix(self):
        self.assertEqual(fleet_control._classify_key("ORCH_SECRET_THING", "v", set(), set()),
                         fleet_control.IGNORE_CREDENTIAL)

    def test_empty_key_and_none_value(self):
        self.assertEqual(fleet_control._classify_key("", "v", set(), set()),
                         fleet_control.IGNORE_EMPTY)
        self.assertEqual(fleet_control._classify_key("ORCH_X", None, set(), set()),
                         fleet_control.IGNORE_EMPTY)

    def test_every_reason_is_a_distinct_string(self):
        reasons = [fleet_control.IGNORE_UNSAFE_KEY, fleet_control.IGNORE_CREDENTIAL,
                   fleet_control.IGNORE_APPROVAL_BLOCKED, fleet_control.IGNORE_PINNED,
                   fleet_control.IGNORE_EMPTY]
        self.assertEqual(len(set(reasons)), len(reasons))


if __name__ == "__main__":
    unittest.main()
