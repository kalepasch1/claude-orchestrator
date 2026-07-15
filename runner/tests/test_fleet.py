"""
test_fleet.py - correctness for fleet.status()/capacity().

2026-07-11 production bug: status() fetched runner_heartbeats with no order/limit. The table
accumulates one row-family per runner restart (runner_id is PID-based, so heartbeat() upserts
never collapse across restarts) and is never pruned, so it grows without bound over days/weeks.
An unordered, unbounded select() could return an arbitrary slice dominated by long-dead rows,
making _live() find almost nothing even when dozens of lanes were genuinely live -- fleet.capacity()
reported in_use=2/free=28 while the real fleet was at 23/40 active lanes. Fixed by ordering
last_seen DESC with a bounded limit so the freshest rows are always the ones fetched regardless of
table history. These tests cover: (1) the select() call requests desc order + a limit, (2) many
live lanes across multiple hosts are all counted, (3) stale rows are correctly excluded from
liveness even when returned, (4) capacity() derives correctly from status().
"""
import datetime
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fleet


def _hb(host, runner_id, active, age_s=0):
    ts = (datetime.datetime.now(datetime.timezone.utc)
          - datetime.timedelta(seconds=age_s)).isoformat()
    return {"runner_id": runner_id, "hostname": host, "active_tasks": active, "last_seen": ts}


class StatusQueryShapeTest(unittest.TestCase):
    def test_select_requests_desc_order_and_a_limit(self):
        """Root-cause regression: without explicit order+limit, a large/unbounded historical
        table can silently hide currently-live rows behind a default/arbitrary page."""
        fake_db = MagicMock()
        fake_db.select.return_value = []
        with patch.object(fleet, "db", fake_db):
            fleet.status()
        args, kwargs = fake_db.select.call_args
        self.assertEqual(args[0], "runner_heartbeats")
        params = args[1] if len(args) > 1 else kwargs.get("params")
        self.assertEqual(params.get("order"), "last_seen.desc")
        self.assertTrue(int(params.get("limit", "0")) > 0)


class LivenessAggregationTest(unittest.TestCase):
    def test_logical_lanes_collapse_to_physical_hosts(self):
        """The exact shape of the production bug: dozens of genuinely live lanes across two
        machines must all be visible, not just a couple that happened to survive an arbitrary
        unordered fetch."""
        rows = []
        for i in range(1, 25):
            rows.append(_hb(f"Mac.lan lane {i}" if i > 1 else "Mac.lan",
                             f"Mac.lan-1000-lane-{i}", active=19 if i == 1 else (1 if i <= 19 else 0)))
        for i in range(1, 17):
            rows.append(_hb(f"Mandys-MacBook-Pro.local lane {i}" if i > 1 else
                             "Mandys-MacBook-Pro.local",
                             f"Mandys-1000-lane-{i}", active=4 if i == 1 else (1 if i <= 4 else 0)))
        fake_db = MagicMock()
        fake_db.select.return_value = rows
        with patch.object(fleet, "db", fake_db):
            s = fleet.status()
        self.assertEqual(s["machines_live"], 2)
        self.assertEqual(s["in_use"], 23)
        self.assertEqual(s["fleet_ceiling"], 2 * fleet.PER_MACHINE_MAX)

    def test_stale_rows_are_excluded_from_liveness(self):
        rows = [
            _hb("Mac.lan", "Mac.lan-1", active=2, age_s=10),           # fresh
            _hb("Mac.lan", "Mac.lan-old-pid", active=3, age_s=999999),  # long-dead restart ghost
        ]
        fake_db = MagicMock()
        fake_db.select.return_value = rows
        with patch.object(fleet, "db", fake_db):
            s = fleet.status()
        # both share hostname "Mac.lan" -- freshest-per-hostname collapse should keep only the
        # live one once dedup runs, and the stale one must not count even if it were kept
        self.assertEqual(s["machines_live"], 1)
        self.assertEqual(s["in_use"], 2)

    def test_scheduler_record_beats_fresher_restart_row(self):
        rows = [
            _hb("Mac.lan", "Mac.lan-100-scheduler", active=11, age_s=8),
            _hb("Mac.lan", "Mac.lan-101", active=2, age_s=1),
        ]
        fake_db = MagicMock()
        fake_db.select.return_value = rows
        with patch.object(fleet, "db", fake_db):
            s = fleet.status()
        self.assertEqual(s["machines_live"], 1)
        self.assertEqual(s["in_use"], 11)

    def test_capacity_derives_from_status(self):
        rows = [_hb("Mac.lan", "Mac.lan-1", active=3, age_s=5)]
        fake_db = MagicMock()
        fake_db.select.return_value = rows
        with patch.object(fleet, "db", fake_db):
            c = fleet.capacity()
        self.assertEqual(c["in_use"], 3)
        self.assertEqual(c["ceiling"], fleet.PER_MACHINE_MAX)
        self.assertEqual(c["free"], fleet.PER_MACHINE_MAX - 3)
        self.assertEqual(c["machines"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
