#!/usr/bin/env python3
"""
Recency gating for crash_loop_detector.

The detector decides a job "has not crashed recently" from `os.path.getmtime(<job>.err)`.
But .err is not a traceback-only stream — jobs write progress lines and `[db] TRUNCATED
SCAN` warnings to stderr as well, so any job that logs at all keeps its .err mtime fresh
forever and every historical traceback still in the 4MB tail reads as current. `classify()`
then divides by the traceback count, so `share` is share-of-failures, never a failure rate.

Live measurement on this repo's .runtime/logs before the gate: 13 findings, all ghosts.
`NameError: name 'run_editorial' is not defined` was reported against seven jobs
(credresolver "critical x134 99.3%", prewarm x331, unstick x221, decisionbriefs x134,
worktreegc x134, backlogcompact x68, dedup x68) even though `periodic.run_editorial` is
defined at periodic.py:1114 and imports cleanly. In credresolver.err the last such
NameError sat 474KB from EOF in a 591KB file, followed only by successful
"[cred-resolver] auto-resolved ..." lines. Those ghost findings are what refill the backlog
with tasks to fix bugs that were fixed days earlier.

The gate must cut ghosts WITHOUT hiding a live loop, so all three regimes are pinned here.
"""
from __future__ import annotations

import os
import sys
import unittest

RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RUNNER_DIR not in sys.path:
    sys.path.insert(0, RUNNER_DIR)

import crash_loop_detector as detector  # noqa: E402  — path set up above

CRASH = ("Traceback (most recent call last):\n"
         '  File "/repo/runner/periodic.py", line 293, in dispatch\n'
         "    return JOBS[job]()\n"
         "NameError: name 'run_editorial' is not defined\n")
SUCCESS = "12:00:00 [cred-resolver] auto-resolved 1/2 credential requests\n"
WARNING = ("[db] TRUNCATED SCAN resource_governor.py:326 -> resource_events returned "
           "exactly its limit (20) ordered by created_at.desc.\n")


def _tracebacks(text):
    return detector.parse_tracebacks(detector.live_tail(text))


class DeadModuleTest(unittest.TestCase):
    """A module that never succeeds must keep every traceback — the original use case."""

    def test_all_tracebacks_survive_when_there_is_no_success_output(self):
        self.assertEqual(len(_tracebacks(CRASH * 30)), 30)

    def test_survives_when_the_log_is_only_crashes_and_blank_lines(self):
        self.assertEqual(len(_tracebacks(("\n" + CRASH) * 12)), 12)


class GhostFindingTest(unittest.TestCase):
    """Crashes followed by successful invocations are history, not a live loop."""

    def test_success_output_after_the_crashes_clears_them(self):
        self.assertEqual(_tracebacks(CRASH * 30 + SUCCESS * 500), [])

    def test_warning_output_also_counts_as_the_job_having_run(self):
        """`[db] TRUNCATED SCAN` is a warning from a job that ran to completion."""
        self.assertEqual(_tracebacks(CRASH * 30 + WARNING * 500), [])

    def test_the_credresolver_shape_produces_no_finding(self):
        """The exact shape measured in credresolver.err: crashes early, successes after."""
        body = SUCCESS * 50 + CRASH * 134 + SUCCESS * 4000
        self.assertEqual(_tracebacks(body), [])


class LiveLoopTest(unittest.TestCase):
    """The gate must never hide a job that is failing right now."""

    def test_crash_at_end_of_log_survives_earlier_success(self):
        found = _tracebacks(SUCCESS * 500 + CRASH * 5)
        self.assertEqual(len(found), 5)

    def test_single_crash_at_eof_survives(self):
        self.assertEqual(len(_tracebacks(SUCCESS * 900 + CRASH)), 1)

    def test_indented_dump_frames_do_not_count_as_success(self):
        """faulthandler dumps are indented; treating them as output would hide the crash."""
        dump = ('  File "/repo/runner/merge_train.py", line 2122 in _train_run_unleased\n'
                '  File "/repo/runner/merge_train.py", line 2256 in <module>\n')
        self.assertEqual(len(_tracebacks(SUCCESS * 100 + CRASH + dump)), 1)


class WindowingTest(unittest.TestCase):
    """The byte window narrows the 4MB tail without splitting a traceback."""

    def test_window_never_starts_mid_traceback(self):
        body = CRASH * 4000
        out = detector.live_tail(body, recent_bytes=2000)
        self.assertTrue(out.startswith("Traceback (most recent call last):"))

    def test_zero_disables_narrowing(self):
        body = CRASH * 3
        self.assertEqual(detector.live_tail(body, recent_bytes=0), body)

    def test_short_logs_are_returned_unchanged(self):
        self.assertEqual(detector.live_tail(CRASH, recent_bytes=10 ** 6), CRASH)

    def test_never_raises_on_junk(self):
        for junk in (None, "", "no tracebacks here", "\n\n\n"):
            with self.subTest(junk=junk):
                self.assertIsInstance(detector.live_tail(junk), str)


class ScanIntegrationTest(unittest.TestCase):
    """scan() applies the gate, and honours the kill switch."""

    def setUp(self):
        import tempfile
        self.dir = tempfile.mkdtemp()
        with open(os.path.join(self.dir, "ghostjob.err"), "w") as handle:
            handle.write(CRASH * 60 + SUCCESS * 400)
        with open(os.path.join(self.dir, "deadjob.err"), "w") as handle:
            handle.write(CRASH * 60)

    def test_ghost_job_produces_no_finding_and_dead_job_does(self):
        jobs = detector.scan(self.dir, window_hours=0)
        self.assertNotIn("ghostjob", jobs)
        self.assertIn("deadjob", jobs)

    def test_kill_switch_restores_previous_behaviour(self):
        saved = detector.RECENCY_GATE
        try:
            detector.RECENCY_GATE = False
            jobs = detector.scan(self.dir, window_hours=0)
            self.assertIn("ghostjob", jobs)
        finally:
            detector.RECENCY_GATE = saved


if __name__ == "__main__":
    unittest.main()
