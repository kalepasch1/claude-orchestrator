"""The gate must not run a timing-sensitive suite into a saturated machine, or stay quiet
about it when it does.

WHAT THIS IS FOR. On 2026-09-08 a full-suite run on this repo reported 5 failures in 4,565
seconds. Re-run on a quiet box, four of the five passed, and the timings were not close:

    test_exact_match_still_passes          601.38s loaded ->  0.33s quiet   (1,800x)
    test_python39_compat                   114.11s loaded ->  1.56s quiet
    test_vendor_portfolio_inclusion        126.07s loaded ->  under 0.26s
    test_worktree_stale_registration        99.18s loaded ->  under 0.26s

Nothing in the gate's output said the machine was busy. The suite's own header had already
recorded the pattern from an earlier day -- "Every green full-suite run that day was at
load ~8; every red one at 16-26" -- and _wait_for_quiet_machine was written for it, but it
was wired into the RE-RUN only. The first run, the one that costs 76 minutes and produces
the failures an operator reads, started on whatever the box happened to be doing.

Two fixes, one test class each:

  * the cool-down now runs before the first attempt as well, so the common case is a good
    first run rather than a bad one recovered by a second full suite;
  * a load watch samples the whole run and puts what the machine was doing into the red
    verdict, because a red run spent above the quiet threshold has told you less than it
    appears to.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import production_push_guard as guard

#: Loads either side of a threshold of 4.0, used to build unambiguous sample sets.
QUIET_LOAD = 1.0
BUSY_LOAD = 20.0
TEST_THRESHOLD = 4.0
EXPECTED_NONE = 0


class TheCoolDownRunsBeforeTheFirstAttempt(unittest.TestCase):
    """Not only before the re-run, which is where it used to live."""

    def _drive(self, returncodes):
        """Run verify_tests against a scripted sequence of suite results."""
        results = []
        for code in returncodes:
            proc = MagicMock()
            proc.returncode = code
            proc.stdout = "1 passed" if code == 0 else "1 failed"
            proc.stderr = ""
            proc.seconds = 1
            results.append(proc)

        waits = []
        # proof_graph is stubbed with reusable_verification returning None ON PURPOSE: a
        # bare MagicMock returns a truthy MagicMock, verify_tests reads that as "a green
        # proof already exists", and returns before running anything at all. The first
        # draft of this test did exactly that and passed for the wrong reason.
        proof_graph = MagicMock()
        proof_graph.reusable_verification.return_value = None
        with patch.object(guard, "detect_test_cmd", return_value="npm run test"), \
             patch.object(guard, "_run_suite", side_effect=results), \
             patch.object(guard, "_wait_for_quiet_machine",
                          side_effect=lambda *a, **k: waits.append(True)), \
             patch.object(guard, "_tracked_content_still_matches", return_value=True), \
             patch.object(guard, "_tree_is_exactly", return_value=True), \
             patch.object(guard, "_session_was_killed", return_value=False), \
             patch.object(guard, "proof_graph", proof_graph):
            guard.verify_tests("/nonexistent-repo", "deadbeefcafe")
        return waits

    def test_a_green_first_run_still_paid_the_cool_down(self):
        """One wait, before the only attempt. Removing the first-run call makes this zero."""
        waits = self._drive([0])
        self.assertGreaterEqual(len(waits), 1,
                                "the cool-down did not run before the first attempt")


class TheLoadWatchDescribesTheRun(unittest.TestCase):

    def test_a_run_that_stayed_quiet_is_not_suspect(self):
        watch = guard._LoadWatch(TEST_THRESHOLD)
        watch.samples = [QUIET_LOAD, QUIET_LOAD, QUIET_LOAD, QUIET_LOAD]
        self.assertFalse(watch.suspect)
        self.assertIn("peak 1.0", watch.summary())

    def test_a_run_that_sat_above_the_threshold_is_suspect(self):
        """A quarter of the run above the threshold is enough to say so."""
        watch = guard._LoadWatch(TEST_THRESHOLD)
        watch.samples = [BUSY_LOAD, BUSY_LOAD, BUSY_LOAD, QUIET_LOAD]
        self.assertTrue(watch.suspect)
        self.assertIn("peak 20.0", watch.summary())

    def test_a_watch_that_saw_nothing_says_nothing(self):
        """os.getloadavg does not exist everywhere. A silent watch must be harmless."""
        watch = guard._LoadWatch(TEST_THRESHOLD)
        self.assertEqual(watch.summary(), "")
        self.assertFalse(watch.suspect)

    def test_the_watch_never_breaks_a_push_when_the_platform_has_no_load_average(self):
        with patch.object(guard.os, "getloadavg", side_effect=AttributeError("no such thing")):
            with guard._load_watch() as watch:
                pass
        self.assertEqual(len(watch.samples), EXPECTED_NONE)

    def test_the_watch_samples_while_something_runs(self):
        with patch.object(guard, "LOAD_SAMPLE_INTERVAL_S", 0.01), \
             patch.object(guard.os, "getloadavg", return_value=(BUSY_LOAD, BUSY_LOAD, BUSY_LOAD)):
            with guard._load_watch() as watch:
                guard.time.sleep(0.1)
        self.assertGreater(len(watch.samples), EXPECTED_NONE)
        self.assertTrue(all(sample == BUSY_LOAD for sample in watch.samples))


if __name__ == "__main__":
    unittest.main()
