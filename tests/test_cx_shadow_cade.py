#!/usr/bin/env python3
"""Tests for runner/cx_shadow_cade.py — the shadow-mode CADE ground-truth collector.

No DB and no model calls: db.select/insert and committees.review are stubbed so the tests
exercise the stance mapping, divergence detection, CSV trail, and fail-soft behaviour.
"""
import csv
import os
import sys
import types
import unittest

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
sys.path.insert(0, RUNNER)

import cx_shadow_cade as scade  # noqa: E402


class FakeDB:
    def __init__(self, approvals=None, shadow_rows=None, fail=False):
        self.approvals = approvals or []
        self.shadow_rows = shadow_rows or []
        self.fail = fail
        self.inserted = []

    def select(self, table, params=None):
        if self.fail:
            raise RuntimeError("db down")
        if table == "approvals":
            return list(self.approvals)
        if table == "determination_outcomes":
            return list(self.shadow_rows)
        return []

    def insert(self, table, row):
        if self.fail:
            raise RuntimeError("db down")
        self.inserted.append((table, row))
        return row


def approval(aid, status, title="t", why="w", project="beethoven"):
    return {"id": aid, "status": status, "title": title, "why": why, "project": project}


class StanceMappingTests(unittest.TestCase):
    def test_go_maps_to_approved(self):
        self.assertEqual(scade._cade_stance("GO (ship it)"), "approved")

    def test_hold_and_nogo_map_to_denied(self):
        for rec in ("HOLD (legal veto)", "NO-GO", "BLOCK this", "STOP"):
            self.assertEqual(scade._cade_stance(rec), "denied", rec)

    def test_escalate_and_unknown_abstain(self):
        for rec in ("ESCALATE (north-star drift)", "", None, "maybe"):
            self.assertIsNone(scade._cade_stance(rec))

    def test_human_stance_normalises_status(self):
        self.assertEqual(scade._human_stance("Approved"), "approved")
        self.assertEqual(scade._human_stance("denied"), "denied")
        self.assertEqual(scade._human_stance("rejected"), "denied")
        self.assertIsNone(scade._human_stance("pending"))
        self.assertIsNone(scade._human_stance(None))


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()
        self._real_db = scade.db
        scade.db = self.db

    def tearDown(self):
        scade.db = self._real_db

    def test_divergence_when_human_and_cade_disagree(self):
        rec = scade._record(approval("a1", "approved"), {"recommendation": "HOLD (risk)"})
        self.assertTrue(rec["diverged"])
        self.assertEqual(rec["source"], "shadow")
        table, row = self.db.inserted[0]
        self.assertEqual(table, "determination_outcomes")
        self.assertEqual(row["source"], "shadow")
        self.assertEqual(row["labeled_outcome"], -1.0)

    def test_agreement_is_positive_label(self):
        rec = scade._record(approval("a2", "approved"), {"recommendation": "GO"})
        self.assertFalse(rec["diverged"])
        self.assertEqual(self.db.inserted[0][1]["labeled_outcome"], 1.0)

    def test_abstain_is_neutral_and_not_a_divergence(self):
        rec = scade._record(approval("a3", "denied"), {"recommendation": "ESCALATE (drift)"})
        self.assertFalse(rec["diverged"])
        self.assertEqual(rec["cade_stance"], "abstain")
        self.assertEqual(self.db.inserted[0][1]["labeled_outcome"], 0.0)

    def test_dry_run_writes_nothing(self):
        scade._record(approval("a4", "approved"), {"recommendation": "GO"}, dry_run=True)
        self.assertEqual(self.db.inserted, [])


class CsvTests(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "_tmp_determination_outcomes.csv")
        if os.path.exists(self.path):
            os.remove(self.path)

    def tearDown(self):
        if os.path.exists(self.path):
            os.remove(self.path)

    def _rows(self):
        with open(self.path, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    def test_writes_header_then_appends(self):
        scade.write_csv([{"ts": "t", "source": "shadow", "approval_id": "a1"}], self.path)
        scade.write_csv([{"ts": "t", "source": "shadow", "approval_id": "a2"}], self.path)
        rows = self._rows()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["source"] == "shadow" for r in rows))

    def test_empty_records_is_a_noop(self):
        scade.write_csv([], self.path)
        self.assertFalse(os.path.exists(self.path))

    def test_bad_path_is_fail_soft(self):
        # must not raise even when the directory does not exist
        scade.write_csv([{"ts": "t", "source": "shadow"}], "/nonexistent-dir-xyz/out.csv")


class RunTests(unittest.TestCase):
    def setUp(self):
        self._real_db = scade.db
        self.path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp_run.csv")
        self._stub_committees()

    def tearDown(self):
        scade.db = self._real_db
        sys.modules.pop("committees", None)
        if os.path.exists(self.path):
            os.remove(self.path)

    def _stub_committees(self, recommendation="HOLD (risk)"):
        mod = types.ModuleType("committees")
        mod.review = lambda *a, **k: {"recommendation": recommendation, "consensus_pct": 0.8}
        sys.modules["committees"] = mod

    def test_run_shadows_and_writes_csv_and_digest(self):
        scade.db = FakeDB(approvals=[approval("a1", "approved"), approval("a2", "denied")])
        records = scade.run(limit=2, csv_path=self.path)
        self.assertEqual(len(records), 2)
        self.assertTrue(os.path.isfile(self.path))
        self.assertTrue(all(r["source"] == "shadow" for r in records))
        kinds = [row["kind"] for t, row in scade.db.inserted if t == "inbox"]
        self.assertIn("shadow_cade_divergence", kinds)

    def test_run_respects_limit(self):
        scade.db = FakeDB(approvals=[approval(f"a{i}", "approved") for i in range(10)])
        self.assertEqual(len(scade.run(limit=3, csv_path=self.path)), 3)

    def test_run_skips_already_shadowed(self):
        scade.db = FakeDB(approvals=[approval("a1", "approved")],
                          shadow_rows=[{"subject_id": "a1"}])
        self.assertEqual(scade.run(limit=5, csv_path=self.path), [])

    def test_run_skips_undecided_approvals(self):
        scade.db = FakeDB(approvals=[approval("a1", "pending")])
        self.assertEqual(scade.run(limit=5, csv_path=self.path), [])

    def test_run_is_fail_soft_when_db_is_down(self):
        scade.db = FakeDB(fail=True)
        self.assertEqual(scade.run(limit=5, csv_path=self.path), [])

    def test_no_digest_when_cade_agrees(self):
        self._stub_committees(recommendation="GO")
        scade.db = FakeDB(approvals=[approval("a1", "approved")])
        records = scade.run(limit=1, csv_path=self.path)
        self.assertFalse(records[0]["diverged"])
        self.assertNotIn("inbox", [t for t, _ in scade.db.inserted])


if __name__ == "__main__":
    unittest.main()
