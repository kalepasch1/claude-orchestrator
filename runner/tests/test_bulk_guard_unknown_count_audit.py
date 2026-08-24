#!/usr/bin/env python3
"""The `row_count=-1, actor='unknown'` audit rows must explain themselves.

investigate-audit-anomaly-20260814-p3qz spent a full investigation on 37 rows in
bulk_state_change_audit reading row_count=-1 / actor='unknown', concluding they were
"impossible for a legitimate batch UPDATE" and proposing a CHECK (row_count >= 0)
constraint.

They are the guard working. `check()` refuses an UNBOUNDED state flip when the affected-row
count cannot be read, unless an operator sets ORCH_ALLOW_BULK_STATE_CHANGE; when the operator
does, `_audit` records a transition whose count was never knowable.
bulk_state_change_audit.row_count is `integer NOT NULL`, so -1 is the only available encoding
of "undetermined". actor='unknown' was the parameter default, not a rogue writer.

These tests pin that reading, and pin that the proposed constraint must not be added.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bulk_update_guard as guard


class _Recorder:
    """Captures the audit row instead of writing to Postgres."""

    def __init__(self):
        self.rows = []

    def insert(self, table, row):
        self.rows.append((table, row))
        return row


class UnknownCountAuditTest(unittest.TestCase):
    PATCH = {"state": "MERGED"}

    def setUp(self):
        self.recorder = _Recorder()
        # The local JSONL write is the part that must never be skipped, so let it happen —
        # into a temp dir, not the real .runtime/logs.
        import tempfile
        self.tmp = tempfile.mkdtemp()
        p = patch.dict(os.environ, {"CLAUDE_ORCH_HOME": self.tmp}, clear=False)
        p.start()
        self.addCleanup(p.stop)
        sys.modules.setdefault("db", None)

    def _audit_with(self, row_count, actor=None, reason="", token="operator confirmed"):
        fake_db = self.recorder
        with patch.dict(sys.modules, {"db": fake_db}):
            guard._audit("tasks", self.PATCH, row_count, actor, reason, token)
        self.assertEqual(len(self.recorder.rows), 1)
        table, row = self.recorder.rows[0]
        self.assertEqual(table, "bulk_state_change_audit")
        return row

    def test_unknown_count_is_stored_as_the_named_sentinel(self):
        row = self._audit_with(None)
        self.assertEqual(row["row_count"], guard.ROW_COUNT_UNKNOWN)

    def test_the_sentinel_row_says_what_it_means(self):
        """A `select *` must not read as corruption ever again."""
        row = self._audit_with(None, reason="db.update(tasks, match=['slug'])")
        self.assertIn("COUNT-UNDETERMINED", row["reason"])
        self.assertIn("not a negative count", row["reason"])
        # the caller's own reason survives alongside the note
        self.assertIn("db.update(tasks", row["reason"])

    def test_a_known_count_carries_no_note_and_no_sentinel(self):
        row = self._audit_with(9236, reason="deliberate backfill")
        self.assertEqual(row["row_count"], 9236)
        self.assertNotIn("COUNT-UNDETERMINED", row["reason"])
        self.assertEqual(row["reason"], "deliberate backfill")

    def test_zero_rows_is_a_real_count_not_an_unknown(self):
        row = self._audit_with(0)
        self.assertEqual(row["row_count"], 0)
        self.assertNotIn("COUNT-UNDETERMINED", row["reason"])

    def test_actor_falls_back_to_orch_actor_before_the_unknown_literal(self):
        with patch.dict(os.environ, {"ORCH_ACTOR": "merge-train"}, clear=False):
            row = self._audit_with(3, actor=None)
        self.assertEqual(row["actor"], "merge-train")

    def test_actor_is_unknown_only_when_there_is_genuinely_nothing_to_report(self):
        env = {k: v for k, v in os.environ.items() if k != "ORCH_ACTOR"}
        env["CLAUDE_ORCH_HOME"] = self.tmp
        with patch.dict(os.environ, env, clear=True):
            row = self._audit_with(3, actor=None)
        self.assertEqual(row["actor"], "unknown")

    def test_an_explicit_actor_always_wins(self):
        with patch.dict(os.environ, {"ORCH_ACTOR": "merge-train"}, clear=False):
            row = self._audit_with(3, actor="phantom_reclassify")
        self.assertEqual(row["actor"], "phantom_reclassify")


class LocalRecordMatchesTheDbRowTest(unittest.TestCase):
    """The JSONL record is documented as authoritative, so it must not disagree with Postgres.

    It used to: the JSONL kept row_count=None while the DB row became -1.
    """

    def test_jsonl_and_db_row_agree_on_an_unknown_count(self):
        import json
        import tempfile
        tmp = tempfile.mkdtemp()
        recorder = _Recorder()
        with patch.dict(os.environ, {"CLAUDE_ORCH_HOME": tmp}, clear=False), \
             patch.dict(sys.modules, {"db": recorder}):
            guard._audit("tasks", {"state": "MERGED"}, None, "actor-x", "why", "tok")

        with open(os.path.join(tmp, "logs", "bulk-update-guard.log")) as fh:
            local = json.loads(fh.read().strip().splitlines()[-1])
        _table, db_row = recorder.rows[0]

        self.assertEqual(local["row_count"], db_row["row_count"])
        self.assertEqual(local["row_count"], guard.ROW_COUNT_UNKNOWN)
        self.assertTrue(local["row_count_unknown"])
        self.assertEqual(local["reason"], db_row["reason"])
        self.assertEqual(local["actor"], db_row["actor"])


class DoNotConstrainRowCountTest(unittest.TestCase):
    def test_the_sentinel_is_negative_on_purpose(self):
        """Pins the decision NOT to add CHECK (row_count >= 0).

        Such a constraint would reject this exact insert, so the single most dangerous write
        in the system — an operator-authorised flip of an unbounded number of rows — would
        become the one that is never audited. If a future change makes the sentinel
        non-negative, that constraint becomes safe and this test should be revisited
        deliberately rather than silently.
        """
        self.assertLess(guard.ROW_COUNT_UNKNOWN, 0)
        row = _Recorder()
        import tempfile
        with patch.dict(os.environ, {"CLAUDE_ORCH_HOME": tempfile.mkdtemp()}, clear=False), \
             patch.dict(sys.modules, {"db": row}):
            guard._audit("tasks", {"state": "MERGED"}, None, "a", "r", "t")
        stored = row.rows[0][1]["row_count"]
        self.assertLess(
            stored, 0,
            "the audit insert stores a negative row_count on the unknown-count path, so "
            "CHECK (row_count >= 0) would reject it and leave that write unaudited")


if __name__ == "__main__":
    unittest.main(verbosity=2)
