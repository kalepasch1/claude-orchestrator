#!/usr/bin/env python3
"""Age-based starvation prevention has to actually reach aged tasks.

score_task discounts a task 5 points past three days and 10 past seven, under
the heading "Age-based starvation prevention". It never fired.

score_backlog selected `priority=eq.1000` — tasks that have never been scored.
A task is scored once, on the pass after it is queued, when its age is about
zero. From then on its priority is not 1000, it never matches the query again,
and its age discount stays frozen at the day-one value. The mechanism was
unreachable for exactly the tasks it exists to protect: the ones that sit.

These tests pin the reach (aged tasks are examined) and the safety property
that makes rescoring safe to run on a schedule (priority only ever moves toward
the front, never away from it).
"""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import priority_scorer as ps  # noqa: E402


def iso_days_ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def task(tid="t1", slug="improve-x", kind="build", priority=1000, age_days=0):
    return {
        "id": tid, "slug": slug, "kind": kind, "deps": ["blocker"],
        "created_at": iso_days_ago(age_days), "priority": priority,
    }


class FakeDB:
    """Answers the two selects score_backlog makes, and records updates."""

    def __init__(self, unscored=None, aged=None):
        self.unscored = unscored or []
        self.aged = aged or []
        self.updates = []
        self.select_params = []

    def select(self, table, params):
        self.select_params.append(params)
        if params.get("priority") == "eq.1000":
            return list(self.unscored)
        if any(k == "created_at" for k in params):
            return list(self.aged)
        return []

    def update(self, table, match, patch):
        self.updates.append((match["id"], patch["priority"]))
        return True


class ScoreBacklogTest(unittest.TestCase):
    def run_with(self, fake):
        with patch.object(ps, "db", fake):
            return ps.score_backlog()


class TestAgedTasksAreReached(ScoreBacklogTest):
    def test_the_scan_asks_for_aged_tasks_at_all(self):
        fake = FakeDB()
        self.run_with(fake)
        self.assertTrue(
            any("created_at" in p for p in fake.select_params),
            "aged tasks were never queried, so the age discount could not apply",
        )

    def test_an_aged_already_scored_task_gets_its_discount(self):
        # Scored on day 0 as a plain improve- task: base 35, ready-to-run not
        # applicable (it has a blocker). Ten days later it should be 10 lower.
        aged = [task(priority=35, age_days=10)]
        fake = FakeDB(unscored=[], aged=aged)
        result = self.run_with(fake)
        self.assertEqual(result["scored"], 1)
        self.assertEqual(fake.updates, [("t1", 25)])

    def test_a_task_younger_than_the_threshold_is_not_rescored_away(self):
        # Under three days the score is unchanged, so nothing is written.
        aged = [task(priority=35, age_days=1)]
        fake = FakeDB(unscored=[], aged=aged)
        self.run_with(fake)
        self.assertEqual(fake.updates, [])

    def test_unscored_tasks_are_still_scored(self):
        fake = FakeDB(unscored=[task(priority=1000, age_days=0)], aged=[])
        result = self.run_with(fake)
        self.assertEqual(result["scored"], 1)
        self.assertEqual(fake.updates, [("t1", 35)])

    def test_a_task_in_both_pages_is_only_scored_once(self):
        row = task(priority=1000, age_days=10)
        fake = FakeDB(unscored=[row], aged=[dict(row)])
        result = self.run_with(fake)
        self.assertEqual(result["scored"], 1)
        self.assertEqual(len(fake.updates), 1)


class TestPriorityOnlyMovesTowardTheFront(ScoreBacklogTest):
    def test_a_hand_set_urgent_priority_is_not_overwritten(self):
        # Someone escalated this to 2. Recomputing would say 35; writing that
        # would silently undo the escalation.
        fake = FakeDB(unscored=[], aged=[task(priority=2, age_days=10)])
        self.run_with(fake)
        self.assertEqual(fake.updates, [])

    def test_rescoring_is_idempotent(self):
        # Second pass over the value the first pass wrote must write nothing,
        # or the periodic job churns the table and the change stream forever.
        first = FakeDB(unscored=[], aged=[task(priority=35, age_days=10)])
        self.run_with(first)
        self.assertEqual(first.updates, [("t1", 25)])

        second = FakeDB(unscored=[], aged=[task(priority=25, age_days=10)])
        self.run_with(second)
        self.assertEqual(second.updates, [])

    def test_the_ratchet_is_checked_directly(self):
        self.assertTrue(ps._should_apply({"priority": 35}, 25))
        self.assertFalse(ps._should_apply({"priority": 25}, 25))
        self.assertFalse(ps._should_apply({"priority": 2}, 25))

    def test_a_default_score_is_never_written_back(self):
        self.assertFalse(ps._should_apply({"priority": 1000}, 1000))

    def test_an_unreadable_current_priority_does_not_block_the_write(self):
        # Better to score a row with a corrupt priority than to leave it at the
        # back of the queue forever.
        self.assertTrue(ps._should_apply({"priority": None}, 25))
        self.assertTrue(ps._should_apply({"priority": "x"}, 25))
        self.assertTrue(ps._should_apply({}, 25))


class TestFailureModes(ScoreBacklogTest):
    def test_a_failing_query_does_not_take_the_pass_down(self):
        class Boom(FakeDB):
            def select(self, table, params):
                raise RuntimeError("postgrest down")

        result = self.run_with(Boom())
        self.assertEqual(result, {"scored": 0, "updated": 0})

    def test_aged_tasks_are_requested_oldest_first(self):
        # If the cap truncates the page, the longest-waiting tasks must be the
        # ones that get their discount.
        fake = FakeDB()
        self.run_with(fake)
        aged_params = [p for p in fake.select_params if "created_at" in p]
        self.assertTrue(aged_params)
        self.assertEqual(aged_params[0].get("order"), "created_at.asc")


if __name__ == "__main__":
    unittest.main(verbosity=2)
