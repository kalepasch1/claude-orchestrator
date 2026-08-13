#!/usr/bin/env python3
"""worktree_gc must terminate on its own, so the 'worktreegc' job cannot wedge again.

The wedge: run() loops over every project, and gc_repo/gc_integration_worktrees loop over
every worktree and slot, each issuing several git/du/lsof calls. GIT_TIMEOUT bounded ONE
call at 90s; nothing bounded the job. It held its singleton lock for 1074s, periodic.py
skipped three consecutive invocations, and every skip exited 0 so nothing noticed.

These tests pin the wall-clock budget: the job stops at the deadline, every subprocess
timeout is clamped to what is left, and the budget is always released — including when a
sweep raises, since a leaked deadline would make later in-process calls think time was up.
"""
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import worktree_gc as wgc


class DeadlineArithmeticTest(unittest.TestCase):
    def tearDown(self):
        wgc._clear_deadline(None)

    def test_no_budget_means_unbounded(self):
        wgc._clear_deadline(None)
        self.assertIsNone(wgc._time_left())
        self.assertFalse(wgc._expired())
        self.assertEqual(wgc._bounded_timeout(), wgc.GIT_TIMEOUT)

    def test_a_budget_of_zero_disables_the_deadline(self):
        wgc._start_deadline(0)
        self.assertIsNone(wgc._time_left())
        self.assertFalse(wgc._expired())

    def test_an_active_budget_counts_down(self):
        wgc._start_deadline(60)
        left = wgc._time_left()
        self.assertIsNotNone(left)
        self.assertTrue(0 < left <= 60)
        self.assertFalse(wgc._expired())

    def test_an_elapsed_budget_reports_expired(self):
        wgc._start_deadline(-1)
        self.assertTrue(wgc._expired())

    def test_subprocess_timeout_is_clamped_to_what_remains(self):
        wgc._start_deadline(5)
        self.assertLessEqual(wgc._bounded_timeout(), 5)
        self.assertGreaterEqual(wgc._bounded_timeout(), 1)

    def test_the_clamp_never_returns_zero_or_negative(self):
        wgc._start_deadline(-100)
        self.assertGreaterEqual(wgc._bounded_timeout(), 1)

    def test_the_clamp_never_exceeds_the_per_call_timeout(self):
        wgc._start_deadline(10_000)
        self.assertEqual(wgc._bounded_timeout(), wgc.GIT_TIMEOUT)

    def test_start_deadline_returns_the_previous_one_for_restoration(self):
        wgc._start_deadline(60)
        first = wgc._deadline
        previous = wgc._start_deadline(60)
        self.assertEqual(previous, first)
        wgc._clear_deadline(previous)
        self.assertEqual(wgc._deadline, first)


class RunGitRespectsTheDeadlineTest(unittest.TestCase):
    def tearDown(self):
        wgc._clear_deadline(None)

    def test_a_git_call_past_the_deadline_short_circuits(self):
        wgc._start_deadline(-1)
        with mock.patch.object(wgc.subprocess, "run") as run:
            result = wgc._run_git(["git", "status"], "/tmp")
        run.assert_not_called()
        self.assertEqual(result.returncode, 124)
        self.assertIn("deadline", result.stderr)

    def test_a_git_call_inside_the_budget_gets_a_clamped_timeout(self):
        wgc._start_deadline(5)
        with mock.patch.object(wgc.subprocess, "run") as run:
            wgc._run_git(["git", "status"], "/tmp")
        self.assertLessEqual(run.call_args.kwargs["timeout"], 5)

    def test_without_a_budget_the_full_timeout_is_used(self):
        wgc._clear_deadline(None)
        with mock.patch.object(wgc.subprocess, "run") as run:
            wgc._run_git(["git", "status"], "/tmp")
        self.assertEqual(run.call_args.kwargs["timeout"], wgc.GIT_TIMEOUT)


class RunStopsAtTheDeadlineTest(unittest.TestCase):
    """The whole point: run() returns instead of holding the lock forever."""

    def setUp(self):
        self.projects = [{"name": f"p{i}", "repo_path": f"/tmp/repo{i}"} for i in range(25)]
        self.swept = []

    def tearDown(self):
        wgc._clear_deadline(None)

    def _patched(self, per_repo_seconds=0.0):
        def fake_gc_repo(repo):
            self.swept.append(repo)
            if per_repo_seconds:
                time.sleep(per_repo_seconds)
            return 0

        return (mock.patch.object(wgc.db, "select", return_value=self.projects),
                mock.patch.object(wgc, "gc_repo", side_effect=fake_gc_repo),
                mock.patch.object(wgc, "gc_integration_worktrees", return_value=(0, 0, 0)))

    def test_an_already_elapsed_budget_sweeps_nothing_and_returns(self):
        a, b, c = self._patched()
        with a, b, c:
            self.assertEqual(wgc.run(max_seconds=-1), 0)
        self.assertEqual(self.swept, [])

    def test_a_slow_sweep_stops_early_rather_than_running_forever(self):
        a, b, c = self._patched(per_repo_seconds=0.02)
        started = time.time()
        with a, b, c:
            wgc.run(max_seconds=0.05)
        elapsed = time.time() - started
        self.assertLess(len(self.swept), len(self.projects))
        self.assertLess(elapsed, 2.0)

    def test_disabling_the_budget_sweeps_everything(self):
        a, b, c = self._patched()
        with a, b, c:
            wgc.run(max_seconds=0)
        self.assertEqual(len(self.swept), len(self.projects))

    def test_the_budget_is_released_even_when_a_sweep_raises(self):
        with mock.patch.object(wgc.db, "select", side_effect=RuntimeError("db down")):
            with self.assertRaises(RuntimeError):
                wgc.run(max_seconds=60)
        self.assertIsNone(wgc._deadline)
        self.assertIsNone(wgc._time_left())

    def test_the_budget_is_released_on_a_normal_return(self):
        a, b, c = self._patched()
        with a, b, c:
            wgc.run(max_seconds=60)
        self.assertIsNone(wgc._deadline)

    def test_the_default_budget_is_finite_and_sane(self):
        self.assertGreater(wgc.MAX_SECONDS, 0)
        self.assertLessEqual(wgc.MAX_SECONDS, 3600)
        self.assertGreater(wgc.MAX_SECONDS, wgc.GIT_TIMEOUT)


if __name__ == "__main__":
    unittest.main()
