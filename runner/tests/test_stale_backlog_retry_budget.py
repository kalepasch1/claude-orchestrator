#!/usr/bin/env python3
"""Retry-budget and backoff gating in stale_backlog_recovery.run_recovery_pipeline.

Before this, the pipeline requeued every stale task on every pass regardless of
how many times it had already failed, and calculate_backoff_delay was dead code.
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import stale_backlog_recovery as sbr  # noqa: E402


def _stale(task_id, attempt=1, last_attempt_at=None, age=99999):
    task = {
        "id": task_id,
        "slug": f"slug-{task_id}",
        "state": "RUNNING",
        "started_at": time.time() - age,
        "attempt": attempt,
    }
    if last_attempt_at is not None:
        task["last_attempt_at"] = last_attempt_at
    return task


class AttemptOfTests(unittest.TestCase):
    def test_defaults_to_one(self):
        self.assertEqual(sbr._attempt_of({}), 1)
        self.assertEqual(sbr._attempt_of(None), 1)

    def test_reads_attempt(self):
        self.assertEqual(sbr._attempt_of({"attempt": 4}), 4)

    def test_bad_value_is_fail_soft(self):
        self.assertEqual(sbr._attempt_of({"attempt": "nope"}), 1)
        self.assertEqual(sbr._attempt_of({"attempt": 0}), 1)
        self.assertEqual(sbr._attempt_of({"attempt": -7}), 1)


class RetryBudgetTests(unittest.TestCase):
    def test_fresh_task_has_budget(self):
        self.assertFalse(sbr.retry_budget_exhausted({"attempt": 1}))

    def test_at_cap_is_exhausted(self):
        self.assertTrue(
            sbr.retry_budget_exhausted({"attempt": sbr.MAX_RECOVERY_ATTEMPTS})
        )

    def test_over_cap_is_exhausted(self):
        self.assertTrue(
            sbr.retry_budget_exhausted({"attempt": sbr.MAX_RECOVERY_ATTEMPTS + 3})
        )

    def test_zero_cap_disables_the_check(self):
        original = sbr.MAX_RECOVERY_ATTEMPTS
        sbr.MAX_RECOVERY_ATTEMPTS = 0
        try:
            self.assertFalse(sbr.retry_budget_exhausted({"attempt": 999}))
        finally:
            sbr.MAX_RECOVERY_ATTEMPTS = original

    def test_none_and_garbage_never_raise(self):
        self.assertFalse(sbr.retry_budget_exhausted(None))
        self.assertFalse(sbr.retry_budget_exhausted("not-a-dict"))


class BackoffRemainingTests(unittest.TestCase):
    def test_just_attempted_is_not_due(self):
        now = time.time()
        owed = sbr.backoff_remaining({"attempt": 1, "last_attempt_at": now}, now)
        self.assertGreater(owed, 0)
        self.assertLessEqual(owed, sbr.calculate_backoff_delay(1))

    def test_long_ago_attempt_is_due(self):
        now = time.time()
        task = {"attempt": 1, "last_attempt_at": now - sbr.MAX_BACKOFF - 1}
        self.assertEqual(sbr.backoff_remaining(task, now), 0.0)

    def test_higher_attempt_waits_longer(self):
        now = time.time()
        one = sbr.backoff_remaining({"attempt": 1, "last_attempt_at": now}, now)
        two = sbr.backoff_remaining({"attempt": 2, "last_attempt_at": now}, now)
        self.assertGreater(two, one)

    def test_missing_timestamp_is_due(self):
        self.assertEqual(sbr.backoff_remaining({"attempt": 3}), 0.0)

    def test_falls_back_to_started_at(self):
        now = time.time()
        task = {"attempt": 1, "started_at": now}
        self.assertGreater(sbr.backoff_remaining(task, now), 0)

    def test_future_timestamp_is_due_not_negative(self):
        now = time.time()
        task = {"attempt": 1, "last_attempt_at": now + 10_000}
        self.assertEqual(sbr.backoff_remaining(task, now), 0.0)

    def test_garbage_never_raises(self):
        self.assertEqual(sbr.backoff_remaining(None), 0.0)
        self.assertEqual(sbr.backoff_remaining("nope"), 0.0)
        self.assertEqual(sbr.backoff_remaining({"last_attempt_at": "x"}), 0.0)


class PipelineGatingTests(unittest.TestCase):
    def test_fresh_stale_task_is_requeued(self):
        out = sbr.run_recovery_pipeline([_stale("a")], threshold_sec=1)
        self.assertEqual(out["detected_stale"], 1)
        self.assertEqual([x["action"] for x in out["actions"]], ["requeue"])
        self.assertEqual(out["deferred_backoff"], 0)
        self.assertEqual(out["exhausted"], 0)

    def test_exhausted_task_is_marked_stale_not_requeued(self):
        task = _stale("b", attempt=sbr.MAX_RECOVERY_ATTEMPTS)
        out = sbr.run_recovery_pipeline([task], threshold_sec=1)
        self.assertEqual(out["exhausted"], 1)
        self.assertEqual([x["action"] for x in out["actions"]], ["mark_stale"])
        self.assertIn("retry_budget_exhausted", out["actions"][0]["reason"])
        self.assertEqual(out["actions"][0]["target_state"], "STALE")

    def test_task_inside_backoff_window_is_deferred(self):
        task = _stale("c", attempt=2, last_attempt_at=time.time())
        out = sbr.run_recovery_pipeline([task], threshold_sec=1)
        self.assertEqual(out["deferred_backoff"], 1)
        self.assertEqual(out["actions"], [])
        self.assertEqual(out["actions_queued"], 0)

    def test_task_past_backoff_window_is_requeued(self):
        task = _stale("d", attempt=2, last_attempt_at=time.time() - sbr.MAX_BACKOFF - 1)
        out = sbr.run_recovery_pipeline([task], threshold_sec=1)
        self.assertEqual(out["deferred_backoff"], 0)
        self.assertEqual([x["action"] for x in out["actions"]], ["requeue"])

    def test_exhausted_beats_backoff(self):
        # An exhausted task must escalate immediately, not sit in backoff.
        task = _stale("e", attempt=sbr.MAX_RECOVERY_ATTEMPTS,
                      last_attempt_at=time.time())
        out = sbr.run_recovery_pipeline([task], threshold_sec=1)
        self.assertEqual(out["exhausted"], 1)
        self.assertEqual(out["deferred_backoff"], 0)
        self.assertEqual([x["action"] for x in out["actions"]], ["mark_stale"])

    def test_duplicate_cancel_still_wins_over_gating(self):
        base = time.time() - 99999
        dupes = [
            {"id": "f1", "slug": "dup", "state": "RUNNING", "started_at": base,
             "attempt": 1},
            {"id": "f2", "slug": "dup", "state": "RUNNING", "started_at": base + 5,
             "attempt": sbr.MAX_RECOVERY_ATTEMPTS},
        ]
        out = sbr.run_recovery_pipeline(dupes, threshold_sec=1)
        kinds = sorted(x["action"] for x in out["actions"])
        self.assertIn("cancel", kinds)
        # The younger duplicate is cancelled, so it is not also marked stale.
        self.assertEqual(len([x for x in out["actions"] if x["action"] == "cancel"]), 1)

    def test_pipeline_is_idempotent_on_same_snapshot(self):
        tasks = [_stale("g"), _stale("h", attempt=sbr.MAX_RECOVERY_ATTEMPTS)]
        first = sbr.run_recovery_pipeline(tasks, threshold_sec=1)
        second = sbr.run_recovery_pipeline(tasks, threshold_sec=1)
        self.assertEqual(
            [(x["slug"], x["action"]) for x in first["actions"]],
            [(x["slug"], x["action"]) for x in second["actions"]],
        )

    def test_empty_and_garbage_input_never_raise(self):
        for bad in (None, [], [None], ["x"], [{}]):
            out = sbr.run_recovery_pipeline(bad, threshold_sec=1)
            self.assertEqual(out["actions_queued"], 0)


if __name__ == "__main__":
    unittest.main()
