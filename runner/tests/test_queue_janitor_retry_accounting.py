#!/usr/bin/env python3
"""One janitor repair must cost exactly one transient_retries attempt.

THE REGRESSION THIS PINS: _repair_task once PRESERVED transient_retries
(`= int(... or 0)`), so the three below-cap call sites compensated by handing it a
pre-incremented copy, `{**t, "transient_retries": attempts + 1}`. When _repair_task was
later fixed to advance the counter, the compensation was left in place. Both fixes are
individually correct and together they double-counted: a task at retries=1 was written
back as 3.

transient_retries is the fleet's cap counter (REQUEUE_CAP), so the effect was not
cosmetic — orphaned work burned through the cap in half the attempts and was pushed onto
the at-cap path, which routes differently (prefer_non_claude, "hit the janitor cap"),
long before it had actually been retried that many times.
"""
import datetime
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agentic_repair  # noqa: E402
import queue_janitor  # noqa: E402


def _iso(seconds_ago):
    ts = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=seconds_ago)
    return ts.isoformat()


def _task(retries=0, state="RUNNING", note="", seconds_ago=None, **extra):
    if seconds_ago is None:
        seconds_ago = 6 * 3600
    row = {
        "id": "t1", "slug": "some-slug", "project_id": "p1", "state": state,
        "transient_retries": retries, "attempt": 1, "note": note,
        "prompt": "Implement some-slug.", "model": None, "force_coder": None,
        "kind": "build", "account": "runner-1", "updated_at": _iso(seconds_ago),
    }
    row.update(extra)
    return row


class _Capture:
    """Fake db that records the patch each janitor path writes."""

    def __init__(self, rows):
        self.rows = rows
        self.patches = []

    def select(self, table, params=None):
        return list(self.rows) if table == "tasks" else []

    def update(self, table, match, patch):
        self.patches.append(patch)

    def insert(self, table, row):
        return row

    def count(self, table, params=None):
        return len(self.rows)


class OneRepairIsOneAttemptTest(unittest.TestCase):
    """Every janitor path that re-queues a task advances the counter by exactly 1."""

    def _run(self, fn, rows):
        cap = _Capture(rows)
        with patch.object(queue_janitor, "db", cap), \
             patch.object(agentic_repair, "choose_coder", return_value="ollama"):
            fn()
        return cap.patches

    def test_release_orphaned_running_increments_by_one(self):
        patches = self._run(queue_janitor.release_orphaned_running,
                            [_task(retries=1, seconds_ago=25 * 60)])
        self.assertEqual(len(patches), 1)
        self.assertEqual(patches[0]["transient_retries"], 2)

    def test_requeue_stuck_running_increments_by_one(self):
        patches = self._run(queue_janitor.requeue_stuck_running,
                            [_task(retries=1, seconds_ago=int(queue_janitor.STUCK_RUNNING_H * 3600) + 600)])
        self.assertEqual(len(patches), 1)
        self.assertEqual(patches[0]["transient_retries"], 2)

    def test_requeue_empty_runs_increments_by_one(self):
        row = _task(retries=1, state="BLOCKED",
                    note="agent produced an empty diff, no changes to commit")
        patches = self._run(queue_janitor.requeue_empty_runs, [row])
        if not patches:
            self.skipTest("note did not match EMPTY_RUN_MARKERS on this revision")
        self.assertEqual(patches[0]["transient_retries"], 2)

    def test_requeue_empty_runs_advances_attempt_by_one_too(self):
        """`attempt` has exactly one writer: agentic_repair.repair_patch.

        requeue_empty_runs also pre-incremented `attempt`, and repair_patch sets
        `patch["attempt"] = attempts + 1` unconditionally, so an empty-run requeue cost
        two attempts against the BLIND/GLOBAL repair ceilings as well.
        """
        row = _task(retries=1, state="BLOCKED", attempt=4,
                    note="agent produced an empty diff, no changes to commit")
        patches = self._run(queue_janitor.requeue_empty_runs, [row])
        if not patches:
            self.skipTest("note did not match EMPTY_RUN_MARKERS on this revision")
        self.assertEqual(patches[0].get("attempt"), 5)

    def test_a_task_starting_at_zero_reaches_the_cap_in_cap_repairs(self):
        """The cap must mean what it says: N repairs, not N/2.

        Feeds each written-back counter into the next repair, the way successive janitor
        cycles do, and asserts the number of repairs needed to reach REQUEUE_CAP.
        """
        cap = queue_janitor.REQUEUE_CAP
        retries = 0
        repairs = 0
        while retries < cap and repairs < cap * 4:  # bounded so a regression cannot hang
            patches = self._run(queue_janitor.release_orphaned_running,
                                [_task(retries=retries, seconds_ago=25 * 60)])
            retries = patches[0]["transient_retries"]
            repairs += 1
        self.assertEqual(repairs, cap,
                         f"reaching REQUEUE_CAP={cap} took {repairs} repairs; "
                         f"the counter is not advancing one-per-repair")


class RepairTaskOwnsTheCounterTest(unittest.TestCase):
    def test_repair_task_advances_a_task_passed_through_unmodified(self):
        cap = _Capture([])
        with patch.object(queue_janitor, "db", cap), \
             patch.object(agentic_repair, "choose_coder", return_value="ollama"):
            queue_janitor._repair_task(_task(retries=2), "orphaned-running", "detail")
        self.assertEqual(cap.patches[0]["transient_retries"], 3)

    def test_a_task_without_the_column_is_left_alone(self):
        row = _task(retries=0)
        row.pop("transient_retries")
        cap = _Capture([])
        with patch.object(queue_janitor, "db", cap), \
             patch.object(agentic_repair, "choose_coder", return_value="ollama"):
            queue_janitor._repair_task(row, "orphaned-running", "detail")
        self.assertNotIn("transient_retries", cap.patches[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
