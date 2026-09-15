"""db_learning: outcome efficacy, recurrence detection, trendlines."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import db_learning as L  # noqa: E402


class FakeDb:
    def __init__(self):
        self.tables = {}
        self.updated = []
        self.inserted = []

    def select(self, table, params=None):
        rows = list(self.tables.get(table, []))
        params = params or {}
        if params.get("limit"):
            rows = rows[: int(params["limit"])]
        return [dict(r) for r in rows]

    def select_all(self, table, params=None, order=None, **kw):
        out = self.select(table, params)
        if order and order.endswith(".desc"):
            out.reverse()
        return out

    def count(self, table, params=None):
        return len(self.tables.get(table, []))

    _ids = 0

    def insert(self, table, row):
        self.inserted.append((table, dict(row)))
        rec = dict(row)
        rec.setdefault("id", "%s-%d" % (table, len(self.tables.get(table, [])) + 1))
        self.tables.setdefault(table, []).append(rec)
        return [dict(rec)]

    def update(self, table, match, patch):
        for r in self.tables.get(table, []):
            if all(r.get(k) == v for k, v in match.items()):
                r.update(patch)
                self.updated.append((table, dict(match), dict(patch)))
                return [dict(r)]
        return []


class Base(unittest.TestCase):
    def setUp(self):
        self.db = FakeDb()
        self.patches = [patch.object(L.db, "select", self.db.select),
                        patch.object(L.db, "select_all", self.db.select_all),
                        patch.object(L.db, "count", self.db.count),
                        patch.object(L.db, "insert", self.db.insert),
                        patch.object(L.db, "update", self.db.update)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()


class RecordCloseoutTest(Base):
    def test_insert_then_update_on_same_pr(self):
        self.assertTrue(L.record_closeout("proj", "me/x", 7, "fk-indexes", "open-pending", 5, 1, 4, False))
        self.assertTrue(L.record_closeout("proj", "me/x", 7, "fk-indexes", "verified-resolved", 5, 5, 0, True))
        rows = self.db.tables["db_pr_closeouts"]
        self.assertEqual(len(rows), 1, "second measurement updates in place (unique repo+pr)")
        self.assertEqual(rows[0]["state"], "verified-resolved")
        self.assertEqual(rows[0]["findings_resolved"], 5)

    def test_db_failure_is_false_not_raise(self):
        with patch.object(L.db, "select", side_effect=RuntimeError("down")):
            self.assertFalse(L.record_closeout("proj", "me/x", 7, "g", "open-pending", 1, 0, 1, False))


class EfficacyTest(Base):
    def test_rates_and_ordering(self):
        self.db.tables["db_pr_closeouts"] = [
            {"pr_group": "fk-indexes", "state": "verified-resolved", "repo": "a", "pr_number": 1},
            {"pr_group": "fk-indexes", "state": "merged-not-confirmed", "repo": "a", "pr_number": 2},
            {"pr_group": "fk-indexes", "state": "merged-not-confirmed", "repo": "a", "pr_number": 3},
            {"pr_group": "access-grants", "state": "verified-resolved", "repo": "a", "pr_number": 4},
            {"pr_group": "access-grants", "state": "verified-resolved", "repo": "a", "pr_number": 5},
            {"pr_group": "audit-columns", "state": "open-pending", "repo": "a", "pr_number": 6},
        ]
        eff = L.efficacy()
        self.assertEqual(eff["fk-indexes"]["rate"], round(1 / 3, 2))
        self.assertEqual(eff["access-grants"]["rate"], 1.0)
        self.assertIsNone(eff["audit-columns"]["rate"])
        ordered = L.efficacy_order(["audit-columns", "access-grants", "fk-indexes"])
        self.assertEqual(ordered[0], "access-grants", "proven group first")
        self.assertEqual(ordered[1], "audit-columns", "unknowns sit in the middle")
        self.assertEqual(ordered[2], "fk-indexes", "below-0.5 track record lands last")
        self.assertEqual(L.group_note("access-grants"), "this fix class resolved 2/2 merged PRs so far")
        self.assertEqual(L.group_note("nope"), "")

    def test_unknown_tables_yield_empty(self):
        self.assertEqual(L.efficacy(), {})
        self.assertEqual(L.efficacy_order(["a", "b"]), ["a", "b"])


class RecurrenceTest(Base):
    def test_open_finding_reopened_is_a_regression_line(self):
        self.db.tables["db_findings"] = [
            {"fingerprint": "x" * 40, "probe_id": "anon_or_public_grants", "severity": "medium",
             "title": "anon holds INSERT on public.gdsa_findings", "object_schema": "public",
             "object_name": "gdsa_findings", "occurrences": 3, "status": "open", "direction": "undermines",
             "last_seen_at": "t"},
        ]
        lines = L.recurrence_lines("proj")
        self.assertTrue(lines and "REGRESSED" in lines[0] and "reopen #3" in lines[0])

    def test_empty_when_nothing_reopened(self):
        self.assertEqual(L.recurrence_lines("proj"), [])


class TrendlineTest(Base):
    def test_delta_and_rates(self):
        import time as _t
        now = _t.time()
        iso = lambda ts: L._iso(ts)
        self.db.tables["db_posture_snapshots"] = [
            {"score": 30.0, "taken_at": iso(now - 3600)},
            {"score": 24.5, "taken_at": iso(now - 8 * 86400)},  # beyond 7d window
        ]
        t = L.trendline("proj")
        self.assertEqual(t["score"], 30.0)
        self.assertEqual(t["delta"], 5.5)
        lines = L.trend_lines("proj")
        self.assertTrue(lines and "+5.5 over 7d" in lines[0])

    def test_unknown_project_yields_nothing(self):
        self.assertEqual(L.trendline("nope"), {})
        self.assertEqual(L.trend_lines("nope"), [])


if __name__ == "__main__":
    unittest.main()
