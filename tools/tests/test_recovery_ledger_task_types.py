"""The recovery ledger's task_type spellings, and who reads across them.

Run: python3 -m pytest tools/tests/test_recovery_ledger_task_types.py

The ledger is split across six task_type values written by different tools.
Each publisher's idempotency check read only its OWN spelling, so publishing a
fingerprint through both publishers wrote every item twice and neither noticed
-- and any query for an item's provenance under-reported unless the caller knew
all six names.

These tests pin the read side. Nothing is renamed: writers keep their historical
type, because a rename creates a seventh population and breaks every existing
consumer.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import recovery_ledger_task_types as t  # noqa: E402
import publish_recovery_ledger as publish  # noqa: E402
import recovery_ledger_publish as ledger_publish  # noqa: E402


class TestTaskTypeRegistry(unittest.TestCase):
    def test_both_publisher_types_are_registered(self):
        self.assertIn(t.PUBLISH_TASK_TYPE, t.ALL_LEDGER_TASK_TYPES)
        self.assertIn(t.LEDGER_TASK_TYPE, t.ALL_LEDGER_TASK_TYPES)

    def test_the_two_publishers_write_different_types(self):
        # This is the defect being worked around, stated as a fact so nobody
        # "fixes" it by quietly changing one and breaking its 100k+ rows.
        self.assertNotEqual(t.PUBLISH_TASK_TYPE, t.LEDGER_TASK_TYPE)

    def test_historical_spellings_are_covered(self):
        for spelling in ("recovery-ledger", "codex_recovery_ledger",
                         "reconcile-ledger"):
            self.assertIn(spelling, t.ALL_LEDGER_TASK_TYPES)

    def test_registry_has_no_duplicates(self):
        self.assertEqual(len(t.ALL_LEDGER_TASK_TYPES),
                         len(set(t.ALL_LEDGER_TASK_TYPES)))


class TestDedupeFilter(unittest.TestCase):
    def test_filter_is_a_postgrest_in_clause(self):
        f = t.dedupe_filter()
        self.assertTrue(f.startswith("in.("))
        self.assertTrue(f.endswith(")"))

    def test_filter_names_every_registered_type(self):
        f = t.dedupe_filter()
        for spelling in t.ALL_LEDGER_TASK_TYPES:
            self.assertIn(spelling, f)

    def test_filter_is_not_an_eq_on_one_type(self):
        # An eq. filter is the bug: it can only ever see one tool's rows.
        self.assertNotIn("eq.", t.dedupe_filter())


class FakeDb:
    """Records the params a dedupe read was issued with."""

    def __init__(self, rows=None):
        self.rows = rows or []
        self.params = None

    def select_all(self, table, params=None):
        self.params = params
        return self.rows


class TestPublisherReadsAcrossSpellings(unittest.TestCase):
    FP = "f7b45f3f90ad76ca289734148ee6e1e1d3c194fd"

    def test_publisher_writes_its_historical_type(self):
        self.assertEqual(publish.TASK_TYPE, t.PUBLISH_TASK_TYPE)
        self.assertEqual(ledger_publish.TASK_TYPE, t.LEDGER_TASK_TYPE)

    def test_dedupe_query_spans_every_type(self):
        db = FakeDb()
        publish.already_published(self.FP, db)
        self.assertEqual(db.params["task_type"], t.dedupe_filter())
        for spelling in t.ALL_LEDGER_TASK_TYPES:
            self.assertIn(spelling, db.params["task_type"])

    def test_dedupe_still_filters_on_the_fingerprint(self):
        # An unfiltered scan hits the 1000-row page cap and silently misses the
        # far end of the table.
        db = FakeDb()
        publish.already_published(self.FP, db)
        self.assertIn(self.FP, db.params["payload"])

    def test_a_row_written_by_the_sibling_publisher_is_now_seen(self):
        import json
        sibling_row = {"payload": json.dumps({
            "audit_fingerprint": self.FP,
            "source": "refs/orch-rescue/20260803T000716-sweep",
        })}
        db = FakeDb(rows=[sibling_row])
        seen = publish.already_published(self.FP, db)
        self.assertIn("refs/orch-rescue/20260803T000716-sweep", seen)

    def test_a_row_for_another_fingerprint_is_ignored(self):
        import json
        other = {"payload": json.dumps({
            "audit_fingerprint": "0000000000000000",
            "source": "refs/orch-rescue/other",
        })}
        db = FakeDb(rows=[other])
        self.assertEqual(publish.already_published(self.FP, db), set())

    def test_lookup_failure_is_fail_soft(self):
        class Boom:
            def select_all(self, *a, **k):
                raise RuntimeError("network down")

        # An unpublished item is worse than a duplicate one, so a failed dedupe
        # read must not stop the ledger landing.
        self.assertEqual(publish.already_published(self.FP, Boom()), set())


if __name__ == "__main__":
    unittest.main()
