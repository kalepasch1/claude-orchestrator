#!/usr/bin/env python3
"""The scheduler heartbeat: give check_scheduler_snapshot_staleness() a real producer.

The monitor had fired 2,695 times over ~34 days because scheduler_status_snapshots held a
single ad-hoc `batch:*` row from 2026-07-22 and nothing in the tree ever wrote to it. These
tests pin the producer, and in particular pin that it can never take down the tick it rides.
"""
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scheduler_snapshot as snap  # noqa: E402


def _db(counts=None, upsert_ok=True, count_raises=False):
    module = types.ModuleType("db")
    module.inserted = []
    module.updated = []

    def count(table, params=None):
        if count_raises:
            raise RuntimeError("count query failed")
        state = str((params or {}).get("state", "")).replace("eq.", "")
        return (counts or {}).get(state, 0)

    def insert(table, row, upsert=False):
        if not upsert_ok and upsert:
            raise RuntimeError("no upsert support")
        module.inserted.append((table, row, upsert))

    module.count = count
    module.insert = insert
    module.update = lambda table, match, patch: module.updated.append((table, match, patch))
    return module


class PayloadTests(unittest.TestCase):
    def test_the_payload_carries_the_states_an_operator_would_ask_for(self):
        payload = snap.build_payload(_db({"QUEUED": 2227, "RUNNING": 0}))
        self.assertEqual(payload["states"]["QUEUED"], 2227)
        self.assertEqual(payload["states"]["RUNNING"], 0)
        self.assertIn("emitted_at", payload)
        self.assertTrue(payload["counts_complete"])

    def test_counts_use_count_not_a_truncated_page(self):
        """PostgREST caps a response at 1,000 rows, so len(select(...)) would report 1000
        for the 2,227-deep queue this heartbeat exists to make visible."""
        db = _db({"QUEUED": 2227})
        self.assertEqual(snap.build_payload(db)["states"]["QUEUED"], 2227)

    def test_a_failed_count_is_marked_incomplete_rather_than_reported_as_zero(self):
        payload = snap.build_payload(_db(count_raises=True))
        self.assertFalse(payload["counts_complete"])
        self.assertEqual(payload["states"]["QUEUED"], -1)

    def test_an_empty_queue_is_distinguishable_from_a_broken_count(self):
        payload = snap.build_payload(_db({"QUEUED": 0}))
        self.assertTrue(payload["counts_complete"])
        self.assertEqual(payload["states"]["QUEUED"], 0)


class PublishTests(unittest.TestCase):
    def test_it_writes_the_namespaced_heartbeat_key(self):
        db = _db({"QUEUED": 5})
        self.assertTrue(snap.publish(db))
        table, row, _ = db.inserted[0]
        self.assertEqual(table, "scheduler_status_snapshots")
        self.assertEqual(row["snapshot_key"], snap.SNAPSHOT_KEY)
        self.assertTrue(snap.SNAPSHOT_KEY.startswith("scheduler:"),
                        "must not collide with the ad-hoc batch:* rows")
        self.assertEqual(row["updated_at"], "now()")

    def test_it_falls_back_when_db_insert_has_no_upsert_kwarg(self):
        module = _db({"QUEUED": 1})

        def insert_without_upsert(table, row):
            module.inserted.append((table, row, False))

        module.insert = insert_without_upsert
        self.assertTrue(snap.publish(module))
        self.assertTrue(module.updated or module.inserted)

    def test_a_total_db_failure_returns_false_instead_of_raising(self):
        module = types.ModuleType("db")
        module.count = lambda *a, **k: 0

        def boom(*a, **k):
            raise RuntimeError("supabase down")

        module.insert = boom
        module.update = boom
        self.assertFalse(snap.publish(module))

    def test_a_missing_db_module_is_survivable(self):
        with mock.patch.dict(sys.modules, {"db": None}):
            self.assertFalse(snap.publish())


class WiringTests(unittest.TestCase):
    def test_the_cadence_stays_under_the_monitor_threshold(self):
        """A heartbeat slower than the staleness threshold IS the alert."""
        import re

        runner_path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "runner.py")
        with open(runner_path, encoding="utf-8") as fh:
            source = fh.read()
        match = re.search(r'"schedsnapshot",\s*"interval",\s*(\d+)', source)
        self.assertIsNotNone(match, "schedsnapshot is not on the periodic schedule")
        self.assertLess(int(match.group(1)), snap.STALE_SECONDS)

    def test_the_job_is_registered_in_the_periodic_dispatch_table(self):
        periodic_path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "periodic.py")
        with open(periodic_path, encoding="utf-8") as fh:
            source = fh.read()
        self.assertIn('"schedsnapshot": run_schedsnapshot', source)


if __name__ == "__main__":
    unittest.main()
