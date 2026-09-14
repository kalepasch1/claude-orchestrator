#!/usr/bin/env python3
"""The weekly owner report carries ONE Database Steering line, computed by
db_memo.owner_report_line() from control-plane tables only, and the report is unchanged
when that line is empty or its computation fails."""
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))  # the shared FakeDb lives in test_db_memo
import db_memo  # noqa: E402
import owner_report  # noqa: E402
from test_db_memo import AC, DP, RI, FakeDb, NOW  # noqa: E402

LINE_RE = (r"^Data steering: (\d+) projects reviewed · posture (\S+) · memo arguments supported (\d+) / "
           r"contested (\d+) / undermined (\d+) · (\d+) open critical/high gaps$")


def _args(*strengths):
    return [{"key": f"k{i}", "claim": "c", "strength": s} for i, s in enumerate(strengths)]


class Base(unittest.TestCase):
    def setUp(self):
        self.db = FakeDb()
        for fn in ("select", "insert", "upsert", "update", "count", "_req"):
            self.enterContext(mock.patch.object(db_memo.db, fn, getattr(self.db, fn)))
        self.enterContext(mock.patch.dict(sys.modules, {
            "decision_rank": types.SimpleNamespace(rank=lambda n: [{"title": "Approve X", "app": "proj"}])}))

    def populate(self):
        self.db.tables["legal_memo_drafts"] = [
            {"id": "m1", "project": "proj", "memo_kind": AC, "arguments": _args("undermined", "supported", "unassessed")},
            {"id": "m2", "project": "proj", "memo_kind": DP, "arguments": _args("contested")},
            {"id": "m3", "project": "other", "memo_kind": RI, "arguments": '[{"key":"k","strength":"supported"}]'},
        ]
        self.db.tables["db_posture_snapshots"] = [
            {"id": "s1", "project": "proj", "score": 40.0, "taken_at": "2026-09-10T00:00:00+00:00"},
            {"id": "s2", "project": "proj", "score": 61.5, "taken_at": "2026-09-11T00:00:00+00:00"},  # latest
            {"id": "s3", "project": "other", "score": 88, "taken_at": "2026-09-09T00:00:00+00:00"},
            {"id": "s4", "project": "third", "score": None, "taken_at": "2026-09-11T00:00:00+00:00"},
        ]
        self.db.tables["db_findings"] = [
            {"id": "f1", "project": "proj", "status": "open", "severity": "critical", "direction": "undermines"},
            {"id": "f2", "project": "proj", "status": "acknowledged", "severity": "high", "direction": "undermines"},
            {"id": "f3", "project": "proj", "status": "resolved", "severity": "critical", "direction": "undermines"},
            {"id": "f4", "project": "proj", "status": "open", "severity": "medium", "direction": "undermines"},
            {"id": "f5", "project": "proj", "status": "open", "severity": "high", "direction": "supports"},
        ]


class TestOwnerReportLine(Base):
    def test_exact_format(self):
        self.populate()
        line = db_memo.owner_report_line()
        self.assertEqual(line, "Data steering: 3 projects reviewed · posture 61.5-88 · memo arguments "
                               "supported 2 / contested 1 / undermined 1 · 2 open critical/high gaps")
        self.assertRegex(line, LINE_RE)
        # the gap count is a server-side count, never a downloaded scan
        counts = self.db.calls("count", "db_findings")
        self.assertEqual(len(counts), 1)
        self.assertEqual(counts[0][2], {"status": "in.(open,acknowledged)", "severity": "in.(critical,high)",
                                        "direction": "eq.undermines"})
        snap_reads = self.db.calls("select", "db_posture_snapshots")
        self.assertEqual(len(snap_reads), 1)
        self.assertEqual(snap_reads[0][2]["order"], "taken_at.desc")
        self.assertIn("limit", snap_reads[0][2])

    def test_empty_tables_yield_empty_line(self):
        self.assertEqual(db_memo.owner_report_line(), "")

    def test_absent_tables_yield_empty_line(self):
        with mock.patch.object(db_memo.db, "select", side_effect=RuntimeError("relation does not exist")):
            self.assertEqual(db_memo.owner_report_line(), "")
        self.populate()
        with mock.patch.object(db_memo.db, "count", side_effect=RuntimeError("down")):
            self.assertEqual(db_memo.owner_report_line(), "")

    def test_no_scores_yet_reads_na(self):
        self.populate()
        self.db.tables["db_posture_snapshots"] = []
        line = db_memo.owner_report_line()
        self.assertIn("2 projects reviewed · posture n/a ·", line)

    def test_week_delta_segment_names_the_movers(self):
        self.populate()
        import datetime as _dt
        old = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=8)).isoformat()
        new = _dt.datetime.now(_dt.timezone.utc).isoformat()
        self.db.tables["db_posture_snapshots"] = [
            {"project": "proj", "score": 55.0, "taken_at": new},
            {"project": "proj", "score": 40.0, "taken_at": old},
            {"project": "other", "score": 70.0, "taken_at": new},
            {"project": "other", "score": 82.0, "taken_at": old},
        ]
        line = db_memo.owner_report_line()
        self.assertIn("Δ7d:", line)
        self.assertIn("proj +15", line) and self.assertIn("other -12", line)

    def test_no_delta_when_no_week_old_snapshots(self):
        self.populate()
        import datetime as _dt
        new = _dt.datetime.now(_dt.timezone.utc).isoformat()
        self.db.tables["db_posture_snapshots"] = [
            {"project": "proj", "score": 61.5, "taken_at": new},
            {"project": "other", "score": 88, "taken_at": new},
        ]
        self.assertNotIn("Δ7d", db_memo.owner_report_line())


class TestOwnerReportWiring(Base):
    def _body(self):
        owner_report.run()
        notes = self.db.tables.get("notifications", [])
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["channel"], "email")
        return notes[0]["body"]

    def test_line_sits_after_top_decisions(self):
        self.populate()
        lines = self._body().splitlines()
        i = next(i for i, l in enumerate(lines) if l.startswith("Top decisions waiting:"))
        self.assertIn("Approve X (proj)", lines[i])
        self.assertRegex(lines[i + 1], LINE_RE)
        self.assertEqual(lines[i + 2], "Open the cockpit Portfolio tab to steer next week.")
        self.assertEqual(lines[0], "WEEK IN REVIEW")

    def test_report_unchanged_when_line_is_empty_or_fails(self):
        base = self._body()
        self.assertNotIn("Data steering:", base)
        self.db.tables["notifications"] = []
        with mock.patch.object(db_memo, "owner_report_line", side_effect=RuntimeError("boom")):
            self.assertEqual(self._body(), base)
        self.db.tables["notifications"] = []
        with mock.patch.dict(sys.modules, {"db_memo": None}):
            self.assertEqual(self._body(), base)


if __name__ == "__main__":
    unittest.main()
