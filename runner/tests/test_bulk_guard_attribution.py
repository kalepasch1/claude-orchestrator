#!/usr/bin/env python3
"""Guardrail 2: every bulk state change must be ATTRIBUTABLE and honestly counted.

37 rows in bulk_state_change_audit (2026-08-04 .. 2026-08-23) carried actor='unknown' and
row_count=-1, all operation='bulk_update' to_state='MERGED'. Both values came from this
module's own defaults: `actor="unknown"` on check()/audited_bulk_update(), and -1 written
whenever the count query had failed. The rows satisfied the schema and answered neither of
the two questions the audit table exists to answer.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bulk_update_guard as guard  # noqa: E402


class ResolveActorTest(unittest.TestCase):
    def test_a_named_actor_is_kept(self):
        self.assertEqual(guard.resolve_actor("merge-train"), "merge-train")

    def test_the_literal_word_unknown_is_never_returned(self):
        for value in (None, "", "   ", "unknown", "UNKNOWN"):
            with mock.patch.dict(os.environ, {}, clear=True):
                resolved = guard.resolve_actor(value)
            self.assertNotEqual(resolved.lower(), "unknown", repr(value))
            self.assertTrue(resolved, "an empty actor is no better than 'unknown'")

    def test_env_supplies_the_actor_when_the_caller_does_not(self):
        with mock.patch.dict(os.environ, {"ORCH_ACTOR": "release-train"}, clear=True):
            self.assertEqual(guard.resolve_actor(None), "release-train")
            self.assertEqual(guard.resolve_actor("unknown"), "release-train")

    def test_an_unknown_env_value_does_not_win_either(self):
        with mock.patch.dict(os.environ, {"ORCH_ACTOR": "unknown"}, clear=True):
            self.assertNotEqual(guard.resolve_actor(None).lower(), "unknown")

    def test_the_fallback_identifies_the_process(self):
        """Not as good as a caller naming itself, but always enough to find it."""
        with mock.patch.dict(os.environ, {}, clear=True):
            resolved = guard.resolve_actor(None)
        self.assertTrue(resolved.startswith("unattributed:"), resolved)
        self.assertIn(f"pid{os.getpid()}", resolved)

    def test_it_is_length_bounded(self):
        self.assertLessEqual(len(guard.resolve_actor("x" * 500)), 200)


class AuditRecordTest(unittest.TestCase):
    """The local JSONL record is the authoritative one, so assert on it."""

    def _audit(self, **kwargs):
        with tempfile.TemporaryDirectory() as home:
            env = {"CLAUDE_ORCH_HOME": home}
            with mock.patch.dict(os.environ, env, clear=True):
                guard._audit(**kwargs)
            path = os.path.join(home, "logs", "bulk-update-guard.log")
            with open(path, encoding="utf-8") as fh:
                return [json.loads(line) for line in fh if line.strip()]

    def test_a_missing_actor_is_resolved_before_it_is_recorded(self):
        rows = self._audit(table="tasks", patch={"state": "MERGED"}, row_count=5,
                           actor=None, reason="why", token="tok")
        self.assertNotEqual(rows[0]["actor"].lower(), "unknown")

    def test_the_word_unknown_is_replaced_even_when_passed_explicitly(self):
        rows = self._audit(table="tasks", patch={"state": "MERGED"}, row_count=5,
                           actor="unknown", reason="why", token="tok")
        self.assertNotEqual(rows[0]["actor"].lower(), "unknown")

    def test_a_known_count_is_flagged_known_and_left_alone(self):
        rows = self._audit(table="tasks", patch={"state": "MERGED"}, row_count=9236,
                           actor="sweeper", reason="why", token="tok")
        self.assertTrue(rows[0]["row_count_known"])
        self.assertEqual(rows[0]["row_count"], 9236)
        self.assertNotIn("sentinel", rows[0]["reason"])

    def test_an_unknown_count_says_so_instead_of_passing_off_minus_one(self):
        """-1 is a sentinel nobody outside this file can interpret; the row must explain it."""
        rows = self._audit(table="tasks", patch={"state": "MERGED"}, row_count=None,
                           actor="sweeper", reason="why", token="tok")
        self.assertFalse(rows[0]["row_count_known"])
        self.assertIn("UNKNOWN", rows[0]["reason"])
        self.assertIn("sentinel", rows[0]["reason"])

    def test_the_original_reason_survives_the_annotation(self):
        rows = self._audit(table="tasks", patch={"state": "MERGED"}, row_count=None,
                           actor="sweeper", reason="compaction sweep", token="tok")
        self.assertIn("compaction sweep", rows[0]["reason"])


class DefaultsTest(unittest.TestCase):
    def test_no_public_entry_point_defaults_to_the_word_unknown(self):
        """The defect was a DEFAULT VALUE, so pin the defaults themselves."""
        import inspect

        for func in (guard.check, guard.audited_bulk_update):
            default = inspect.signature(func).parameters["actor"].default
            self.assertIsNone(default, f"{func.__name__} still defaults actor to {default!r}")


if __name__ == "__main__":
    unittest.main()
