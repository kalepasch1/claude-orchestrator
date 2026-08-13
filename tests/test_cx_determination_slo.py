#!/usr/bin/env python3
"""Tests for runner/cx_determination_slo.py — determination latency SLO.

db is stubbed, so no network and no live tables are touched.
"""
import datetime
import os
import sys
import unittest

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
sys.path.insert(0, RUNNER)

import cx_determination_slo as slo  # noqa: E402

NOW = datetime.datetime(2026, 8, 12, 12, 0, 0, tzinfo=datetime.timezone.utc)


def iso(hours_before_now):
    return (NOW - datetime.timedelta(hours=hours_before_now)).isoformat()


class FakeDB:
    def __init__(self, tables=None, fail_tables=()):
        self.tables = tables or {}
        self.fail_tables = set(fail_tables)
        self.inserted = []

    def select(self, table, params=None):
        if table in self.fail_tables:
            raise RuntimeError(f"{table} unavailable")
        return list(self.tables.get(table, []))

    def insert(self, table, row):
        if table in self.fail_tables:
            raise RuntimeError(f"{table} unavailable")
        self.inserted.append((table, row))
        return row


class TimeHelperTests(unittest.TestCase):
    def test_parse_handles_z_suffix_and_naive(self):
        self.assertIsNotNone(slo._parse_ts("2026-08-12T00:00:00Z"))
        self.assertIsNotNone(slo._parse_ts("2026-08-12T00:00:00"))

    def test_parse_is_fail_soft_on_garbage(self):
        for bad in (None, "", "not-a-date", 12345):
            self.assertIsNone(slo._parse_ts(bad) if not isinstance(bad, int) else slo._parse_ts(str(bad)))

    def test_hours_between(self):
        self.assertEqual(slo._hours_between(iso(5), iso(2)), 3.0)

    def test_inverted_pair_returns_none(self):
        self.assertIsNone(slo._hours_between(iso(2), iso(5)))

    def test_missing_endpoint_returns_none(self):
        self.assertIsNone(slo._hours_between(None, iso(1)))


class PercentileTests(unittest.TestCase):
    def test_empty(self):
        self.assertIsNone(slo.percentile([], 95))

    def test_single_value(self):
        self.assertEqual(slo.percentile([4.0], 95), 4.0)

    def test_p50_and_p95(self):
        vals = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        self.assertEqual(slo.percentile(vals, 50), 6)
        self.assertEqual(slo.percentile(vals, 95), 10)

    def test_ignores_none(self):
        self.assertEqual(slo.percentile([None, 2.0, None], 50), 2.0)


def det(did, subject_id, hours_ago, subject_type="approval", title="t"):
    return {"id": did, "subject_type": subject_type, "subject_id": subject_id,
            "title": title, "created_at": iso(hours_ago)}


class MeasureTests(unittest.TestCase):
    def test_latency_and_slo_flag(self):
        dets = [det("d1", "s1", 0), det("d2", "s2", 0)]
        arrivals = {"s1": iso(2), "s2": iso(100)}
        recs = slo.measure(dets, arrivals, slo_hours=24)
        by_id = {r["determination_id"]: r for r in recs}
        self.assertTrue(by_id["d1"]["met_slo"])
        self.assertFalse(by_id["d2"]["met_slo"])

    def test_unresolvable_arrival_is_dropped_not_guessed(self):
        recs = slo.measure([det("d1", "s1", 0)], {}, slo_hours=24)
        self.assertEqual(recs, [])


class SummarizeTests(unittest.TestCase):
    def _records(self):
        dets = [det("d1", "s1", 0), det("d2", "s2", 0), det("d3", "s3", 0, subject_type="task")]
        arrivals = {"s1": iso(1), "s2": iso(2), "s3": iso(90)}
        return slo.measure(dets, arrivals, slo_hours=24)

    def test_compliance_and_percentiles(self):
        r = slo.summarize(self._records(), slo_hours=24)
        self.assertEqual(r["sample"], 3)
        self.assertEqual(r["met"], 2)
        self.assertEqual(r["breached"], 1)
        self.assertAlmostEqual(r["compliance"], 0.667, places=2)
        self.assertIsNotNone(r["p95_hours"])

    def test_breakdown_by_subject_type(self):
        r = slo.summarize(self._records(), slo_hours=24)
        self.assertEqual(r["by_subject_type"]["approval"]["compliance"], 1.0)
        self.assertEqual(r["by_subject_type"]["task"]["compliance"], 0.0)

    def test_worst_is_sorted_slowest_first(self):
        r = slo.summarize(self._records(), slo_hours=24)
        self.assertEqual(r["worst"][0]["subject_id"], "s3")

    def test_empty_records(self):
        r = slo.summarize([], slo_hours=24)
        self.assertEqual(r["sample"], 0)
        self.assertIsNone(r["compliance"])


class AlertGateTests(unittest.TestCase):
    def test_no_alert_below_min_sample(self):
        self.assertFalse(slo.should_alert({"sample": 2, "compliance": 0.0}, floor=0.8, min_sample=5))

    def test_alert_when_compliance_under_floor(self):
        self.assertTrue(slo.should_alert({"sample": 10, "compliance": 0.5}, floor=0.8, min_sample=5))

    def test_no_alert_when_compliant(self):
        self.assertFalse(slo.should_alert({"sample": 10, "compliance": 0.95}, floor=0.8, min_sample=5))

    def test_no_alert_on_empty_report(self):
        self.assertFalse(slo.should_alert(None))
        self.assertFalse(slo.should_alert({"sample": 10, "compliance": None}))


class RunTests(unittest.TestCase):
    def setUp(self):
        self._real_db = slo.db

    def tearDown(self):
        slo.db = self._real_db

    def test_run_alerts_on_breach(self):
        dets = [det(f"d{i}", f"s{i}", 0) for i in range(6)]
        approvals = [{"id": f"s{i}", "created_at": iso(200)} for i in range(6)]
        slo.db = FakeDB({"determinations": dets, "approvals": approvals})
        report = slo.run(days=7, slo_hours=24, floor=0.8)
        self.assertEqual(report["compliance"], 0.0)
        self.assertTrue(report["alerted"])
        self.assertEqual(slo.db.inserted[0][1]["kind"], "determination_slo")

    def test_run_stays_quiet_when_healthy(self):
        dets = [det(f"d{i}", f"s{i}", 0) for i in range(6)]
        approvals = [{"id": f"s{i}", "created_at": iso(1)} for i in range(6)]
        slo.db = FakeDB({"determinations": dets, "approvals": approvals})
        report = slo.run(days=7, slo_hours=24, floor=0.8)
        self.assertEqual(report["compliance"], 1.0)
        self.assertFalse(report["alerted"])
        self.assertEqual(slo.db.inserted, [])

    def test_no_alert_flag_suppresses_write(self):
        dets = [det(f"d{i}", f"s{i}", 0) for i in range(6)]
        approvals = [{"id": f"s{i}", "created_at": iso(200)} for i in range(6)]
        slo.db = FakeDB({"determinations": dets, "approvals": approvals})
        report = slo.run(days=7, slo_hours=24, floor=0.8, alert=False)
        self.assertFalse(report["alerted"])
        self.assertEqual(slo.db.inserted, [])

    def test_run_is_fail_soft_when_determinations_unavailable(self):
        slo.db = FakeDB(fail_tables={"determinations"})
        report = slo.run(days=7)
        self.assertEqual(report["sample"], 0)
        self.assertFalse(report["alerted"])

    def test_run_is_fail_soft_when_subject_table_unavailable(self):
        slo.db = FakeDB({"determinations": [det("d1", "s1", 0)]}, fail_tables={"approvals"})
        report = slo.run(days=7)
        self.assertEqual(report["sample"], 0)

    def test_alert_insert_failure_does_not_raise(self):
        dets = [det(f"d{i}", f"s{i}", 0) for i in range(6)]
        approvals = [{"id": f"s{i}", "created_at": iso(200)} for i in range(6)]
        slo.db = FakeDB({"determinations": dets, "approvals": approvals}, fail_tables={"inbox"})
        report = slo.run(days=7, slo_hours=24, floor=0.8)
        self.assertFalse(report["alerted"])


class CliTests(unittest.TestCase):
    def setUp(self):
        self._real_db = slo.db
        slo.db = FakeDB()

    def tearDown(self):
        slo.db = self._real_db

    def test_main_exits_zero_with_no_data(self):
        self.assertEqual(slo.main(["--days", "1", "--no-alert", "--json"]), 0)


if __name__ == "__main__":
    unittest.main()
