"""fleet_stuck_alarm must not report a frozen fleet as healthy because one lane is busy.

Regression for the 2026-08-24 provider outage: the global controls row was paused for
22 hours with 438 tasks queued and zero merges, and the alarm printed "healthy" on
every pass, because exactly one straggler task was still RUNNING and the condition
was `queued > 0 and running == 0`.

DB and local state file are fully mocked; no network, no writes outside tmp.
"""
import datetime
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fleet_stuck_alarm as alarm


def _iso(hours_ago):
    when = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours_ago)
    return when.isoformat()


class TestPauseAgeCondition(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Isolate the on-disk alarm state so a real ~/.claude-orchestrator file
        # cannot make this test order-dependent.
        p = patch.object(alarm, "STATE_FILE", os.path.join(self.tmp.name, "state.json"))
        p.start()
        self.addCleanup(p.stop)

    def _controls(self, paused, hours_ago):
        def select(table, params=None):
            if table == "controls":
                return [{"scope": "global", "paused": paused, "updated_at": _iso(hours_ago)}]
            return []
        return select

    def test_pause_age_is_read_from_the_latest_global_row(self):
        with patch.object(alarm.db, "select", self._controls(True, 22)):
            age = alarm._global_pause_age_s()
        self.assertIsNotNone(age)
        self.assertGreater(age, 21 * 3600)

    def test_unpaused_global_row_reports_no_pause_age(self):
        with patch.object(alarm.db, "select", self._controls(False, 22)):
            self.assertIsNone(alarm._global_pause_age_s())

    def test_db_failure_is_fail_soft(self):
        def boom(*a, **k):
            raise RuntimeError("supabase down")
        with patch.object(alarm.db, "select", boom):
            self.assertIsNone(alarm._global_pause_age_s())

    def _run_with(self, queued, running, pause_hours_ago, paused=True):
        """Run the alarm once against fixed counts and a fixed pause age."""
        recorded = {}

        def insert(table, row, upsert=False):
            recorded.setdefault(table, []).append(row)
            return [row]

        with patch.object(alarm, "_counts", lambda: (queued, running)), \
             patch.object(alarm.db, "select", self._controls(paused, pause_hours_ago)), \
             patch.object(alarm.db, "insert", insert), \
             patch.dict(sys.modules, {}, clear=False):
            # Force the sustained-condition branch: pretend it has been stuck a long time.
            # 1.0, not 0 -- run() reads `state.get("first_seen") or time.time()`, so a
            # falsy 0 would be discarded and the run would take the sub-threshold branch.
            alarm._save_state({"first_seen": 1.0})
            result = alarm.run()
        return result, recorded

    def test_long_held_pause_trips_even_though_a_lane_is_running(self):
        """The exact 2026-08-24 shape: queued>0, running==1, pause held 22h."""
        result, recorded = self._run_with(queued=438, running=1, pause_hours_ago=22)
        self.assertTrue(result.get("stuck"), "22h pause with 438 queued must trip the alarm")
        self.assertTrue(result.get("pause_stuck"))
        # And the human-facing card must name the real cause, not just the lane count.
        titles = [r.get("title", "") for r in recorded.get("approvals", [])]
        self.assertTrue(any("global pause held" in t for t in titles),
                        f"approval card should name the pause; got {titles}")

    def test_short_pause_with_a_running_lane_is_still_healthy(self):
        """A routine pause (rollout, billing recheck) must not page anyone."""
        result, _ = self._run_with(queued=438, running=1, pause_hours_ago=0.1)
        self.assertFalse(result.get("stuck"))

    def test_zero_running_still_trips_without_any_pause(self):
        """The original condition is preserved."""
        result, _ = self._run_with(queued=5, running=0, pause_hours_ago=0.1, paused=False)
        self.assertTrue(result.get("stuck"))


if __name__ == "__main__":
    unittest.main()
