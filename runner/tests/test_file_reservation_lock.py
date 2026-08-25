#!/usr/bin/env python3
"""file_reservation must actually take the lock it claims to take.

THE DEFECT THESE TESTS PIN
--------------------------
reserve(), release(), _clean_expired() and _ensure_table() were written as raw
SQL passed to `db.query(...)`.  The db module is a PostgREST client with no
query() and no raw-SQL channel, so every one of those calls raised
AttributeError.  Each was inside a handler that hid it:

  * _ensure_table() returned True regardless — "Table might already exist — try
    to proceed anyway" — so the caller was always told the table was ready.
  * reserve()'s handler looked for "duplicate" / "conflict" / "unique" in the
    error text.  "module 'db' has no attribute 'query'" contains none of them,
    so every file fell to the else-arm and was recorded as neither reserved nor
    blocked.
  * release() logged at debug and returned 0 while promising a count.

blocked_by() is written correctly against db.select, so it worked — and read an
empty relation forever, because nothing ever wrote one.  runner.py:1205 re-queues
a task only when blocked_by() is non-empty.  The fleet's file-level mutual
exclusion has therefore never blocked a single task.

The table itself does not exist either (checked against the live schema on
2026-08-25); runner/migrations/003_file_reservations.sql adds it and is
deliberately not applied.

Every test below fails against the pre-fix module.
"""
import datetime
import importlib
import os
import sys
import types
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import file_reservation  # noqa: E402


def _fresh_db():
    m = types.SimpleNamespace()
    m.select = MagicMock(return_value=[])
    m.insert = MagicMock(return_value={"id": "r1"})
    m.delete = MagicMock(return_value=[])
    return m


class _Base(unittest.TestCase):
    def setUp(self):
        self._real_db = file_reservation.db
        self.db = _fresh_db()
        file_reservation.db = self.db
        file_reservation._TABLE_STATE.update({"checked": False, "present": False})
        self._enabled = file_reservation.ENABLED
        file_reservation.ENABLED = True

    def tearDown(self):
        file_reservation.db = self._real_db
        file_reservation.ENABLED = self._enabled
        file_reservation._TABLE_STATE.update({"checked": False, "present": False})


class TestNoRawSqlChannel(_Base):
    def test_the_module_never_calls_a_db_function_that_does_not_exist(self):
        """The regression itself: db.query/db.sql/db.execute must not appear."""
        import ast
        tree = ast.parse(open(file_reservation.__file__, encoding='utf-8').read())
        calls = {n.func.attr for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and isinstance(n.func.value, ast.Name) and n.func.value.id == 'db'}
        self.assertEqual(calls & {'query', 'sql', 'execute'}, set())
        self.assertTrue(calls <= {'select', 'insert', 'delete', 'update', 'upsert', 'count'},
                        "unexpected db API used: %s" % sorted(calls))


class TestMissingTableIsReportedNotHidden(_Base):
    def test_reserve_refuses_instead_of_claiming_everything(self):
        self.db.select.side_effect = RuntimeError("relation does not exist")
        out = file_reservation.reserve({"id": "t1"}, "/repo", ["a.py", "b.py"])
        self.assertEqual(out["reserved"], [])
        self.assertIn("unavailable", out["error"])
        self.db.insert.assert_not_called()

    def test_blocked_by_does_not_pretend_the_table_is_empty(self):
        self.db.select.side_effect = RuntimeError("relation does not exist")
        self.assertEqual(file_reservation.blocked_by({"id": "t1"}, "/repo", ["a.py"]), [])
        self.assertFalse(file_reservation._table_present())

    def test_the_probe_runs_once_per_process(self):
        file_reservation._table_present()
        file_reservation._table_present()
        file_reservation._table_present()
        self.assertEqual(self.db.select.call_count, 1)


class TestReserveTakesTheLock(_Base):
    def test_a_row_is_inserted_per_file(self):
        out = file_reservation.reserve({"id": "t1", "project_id": "p1"},
                                       "/repo", ["a.py", "b.py"])
        self.assertEqual(sorted(out["reserved"]), ["a.py", "b.py"])
        self.assertEqual(out["blocked"], [])
        self.assertEqual(self.db.insert.call_count, 2)
        table, row = self.db.insert.call_args[0]
        self.assertEqual(table, "file_reservations")
        self.assertEqual(row["task_id"], "t1")
        self.assertEqual(row["repo"], "/repo")

    def test_a_409_from_another_task_is_a_block_not_a_success(self):
        """db.insert returns None on 409 — the UNIQUE(repo, filepath) constraint
        firing IS the lock, and losing that race must block, never steal."""
        self.db.insert.return_value = None
        # selects, in order: table probe, expiry sweep, holder lookup
        self.db.select.side_effect = [[], [], [{"task_id": "other-task"}]]
        out = file_reservation.reserve({"id": "t1"}, "/repo", ["a.py"])
        self.assertEqual(out["reserved"], [])
        self.assertEqual(out["blocked"], [("a.py", "other-task")])

    def test_a_409_from_this_same_task_is_re_entry_not_a_block(self):
        self.db.insert.return_value = None
        self.db.select.side_effect = [[], [], [{"task_id": "t1"}]]
        out = file_reservation.reserve({"id": "t1"}, "/repo", ["a.py"])
        self.assertEqual(out["reserved"], ["a.py"])
        self.assertEqual(out["blocked"], [])

    def test_a_holder_that_vanished_is_blocked_not_silently_claimed(self):
        """Claiming here would not be atomic — only the constraint can arbitrate."""
        self.db.insert.return_value = None
        self.db.select.side_effect = [[], [], []]
        out = file_reservation.reserve({"id": "t1"}, "/repo", ["a.py"])
        self.assertEqual(out["blocked"], [("a.py", "unknown")])

    def test_shared_files_get_the_shorter_ttl(self):
        file_reservation.reserve({"id": "t1"}, "/repo", ["package.json"])
        self.assertEqual(self.db.insert.call_args[0][1]["ttl_seconds"],
                         file_reservation.SHARED_FILE_TTL)

    def test_an_insert_failure_is_surfaced_not_counted_as_reserved(self):
        self.db.insert.side_effect = RuntimeError("boom")
        out = file_reservation.reserve({"id": "t1"}, "/repo", ["a.py"])
        self.assertEqual(out["reserved"], [])
        self.assertIn("boom", out["error"])


class TestReleaseReturnsARealCount(_Base):
    def test_release_deletes_by_task_and_counts_the_rows(self):
        self.db.delete.return_value = [{"id": "1"}, {"id": "2"}, {"id": "3"}]
        n = file_reservation.release({"id": "t1"})
        self.assertEqual(n, 3)
        table, match = self.db.delete.call_args[0]
        self.assertEqual(table, "file_reservations")
        self.assertEqual(match, {"task_id": "t1"})

    def test_release_of_a_task_holding_nothing_is_zero_not_one(self):
        """The old body returned a hardcoded 1 — 'DB doesn't return count
        easily; approximate' — so callers could not tell a release from a no-op."""
        self.db.delete.return_value = []
        self.assertEqual(file_reservation.release({"id": "t1"}), 0)

    def test_release_without_a_task_id_touches_nothing(self):
        self.assertEqual(file_reservation.release({}), 0)
        self.db.delete.assert_not_called()


class TestExpirySweep(_Base):
    def _rows(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        old = (now - datetime.timedelta(seconds=9000)).isoformat()
        recent = (now - datetime.timedelta(seconds=10)).isoformat()
        return [
            {"id": "expired", "reserved_at": old, "ttl_seconds": 7200},
            {"id": "fresh", "reserved_at": recent, "ttl_seconds": 7200},
            {"id": "unreadable", "reserved_at": "not-a-timestamp", "ttl_seconds": 7200},
            {"id": "zulu", "reserved_at": old.replace("+00:00", "Z"), "ttl_seconds": 7200},
        ]

    def test_only_expired_rows_are_deleted(self):
        self.db.select.side_effect = [[], self._rows()]
        removed = file_reservation._clean_expired()
        deleted = {c[0][1]["id"] for c in self.db.delete.call_args_list}
        self.assertEqual(deleted, {"expired", "zulu"})
        self.assertEqual(removed, 2)

    def test_an_unreadable_timestamp_keeps_its_lock(self):
        """Releasing a lock because a timestamp could not be parsed is the
        dangerous direction of that mistake."""
        self.db.select.side_effect = [[], self._rows()]
        file_reservation._clean_expired()
        deleted = {c[0][1]["id"] for c in self.db.delete.call_args_list}
        self.assertNotIn("unreadable", deleted)

    def test_a_naive_timestamp_is_read_as_utc_rather_than_crashing(self):
        naive = (datetime.datetime.now(datetime.timezone.utc)
                 - datetime.timedelta(seconds=9000)).replace(tzinfo=None).isoformat()
        self.db.select.side_effect = [[], [{"id": "n", "reserved_at": naive,
                                            "ttl_seconds": 7200}]]
        self.assertEqual(file_reservation._clean_expired(), 1)


class TestKillSwitch(_Base):
    def test_disabled_reports_everything_reserved_and_touches_no_db(self):
        file_reservation.ENABLED = False
        out = file_reservation.reserve({"id": "t1"}, "/repo", ["a.py"])
        self.assertEqual(out["reserved"], ["a.py"])
        self.db.insert.assert_not_called()


if __name__ == "__main__":
    unittest.main()
