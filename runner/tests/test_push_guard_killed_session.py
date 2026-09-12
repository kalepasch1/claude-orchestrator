"""A session pytest-timeout killed must not be reported as a red suite.

On 2026-09-06 a production promotion was blocked and production_push_guard's entire
output was "suite red -- re-running once", then a second full clock, then nothing.
No test had failed. Two tests were merely slower than pytest.ini's 60s bound, and
because pytest.ini sets `timeout_method = thread`, pytest-timeout cannot interrupt a
test -- it dumps every thread's stack and calls os._exit(1). That exits 1 with no
summary and no FAILED line, so at the returncode it is indistinguishable from a red
suite, and the guard spent a second full suite re-running into the identical exit.

The id of the responsible test was in output the guard had already captured. These
tests pin that it is read out, and pin the one distinction that is easy to get wrong:
under `timeout_method = signal` pytest-timeout prints the SAME banner and the SAME
stack sections whenever more than one thread is alive, and then the session survives
and reports normally. Banner presence is NOT the signal; banner plus the absence of a
session summary is.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import production_push_guard as guard


#: A thread-method kill, in the exact shape pytest-timeout 2.4.0 emits: banner, one
#: `Stack of` section per live thread, no summary line anywhere. MainThread is
#: deliberately NOT first -- dump_stacks iterates sys._current_frames(), whose order
#: is arbitrary, and a parser that takes the first section names a worker's helper.
KILLED = """\
........
+++++++++++++++++++++++++++++++++++ Timeout ++++++++++++++++++++++++++++++++++++
~~~~~~~~~~~~~~~~~~~~~~~ Stack of worker-0 (6163197952) ~~~~~~~~~~~~~~~~~~~~~~~~~
  File "/usr/lib/python3.9/threading.py", line 930, in _bootstrap
    self._bootstrap_inner()
~~~~~~~~~~~~~~~~~~~~~~~ Stack of MainThread (8452218496) ~~~~~~~~~~~~~~~~~~~~~~~
  File "/repo/runner/tests/test_branch_manager.py", line 30, in test_branch_health_report_structure
    report = branch_health_report(repo)
  File "/repo/runner/branch_manager.py", line 63, in find_stale_branches
    subprocess.check_output(
+++++++++++++++++++++++++++++++++++ Timeout ++++++++++++++++++++++++++++++++++++
"""

#: The signal method, which prints the same two markers and then FINISHES.
SURVIVED = """\
+++++++++++++++++++++++++++++++++++ Timeout ++++++++++++++++++++++++++++++++++++
~~~~~~~~~~~~~~~~~~~~~~~ Stack of MainThread (8452218496) ~~~~~~~~~~~~~~~~~~~~~~~
  File "/repo/runner/tests/test_threads.py", line 5, in test_with_worker_threads
    time.sleep(30)
+++++++++++++++++++++++++++++++++++ Timeout ++++++++++++++++++++++++++++++++++++
FAILED test_threads.py::test_with_worker_threads - Failed: Timeout (>3.0s)
1 failed in 3.04s
"""

ORDINARY_RED = """\
F
FAILED runner/tests/test_thing.py::test_thing - assert 1 == 2
1 failed in 0.02s
"""

GREEN = "....\n4 passed in 8.06s\n"


class TestKilledSessionDetection(unittest.TestCase):

    def test_a_killed_session_is_detected(self):
        self.assertTrue(guard._session_was_killed(KILLED))

    def test_a_survived_signal_timeout_is_not_a_kill(self):
        """The regression that matters: same banner, same stacks, session reported."""
        self.assertFalse(guard._session_was_killed(SURVIVED))

    def test_an_ordinary_red_run_is_not_a_kill(self):
        self.assertFalse(guard._session_was_killed(ORDINARY_RED))

    def test_a_green_run_is_not_a_kill(self):
        self.assertFalse(guard._session_was_killed(GREEN))

    def test_empty_output_is_not_a_kill(self):
        self.assertFalse(guard._session_was_killed(""))
        self.assertFalse(guard._session_was_killed(None))


class TestKilledSessionNamesTheTest(unittest.TestCase):

    def test_the_responsible_test_is_named(self):
        self.assertEqual(
            guard._killed_session_test(KILLED),
            "/repo/runner/tests/test_branch_manager.py::test_branch_health_report_structure")

    def test_mainthread_is_found_by_name_not_by_position(self):
        """worker-0 is printed FIRST in KILLED; its frame must not be the answer."""
        self.assertNotIn("threading.py", guard._killed_session_test(KILLED))

    def test_a_dump_without_mainthread_is_survivable(self):
        no_main = KILLED.replace("Stack of MainThread (8452218496)",
                                 "Stack of worker-9 (8452218496)")
        self.assertEqual(guard._killed_session_test(no_main), "")


class TestKilledSessionVerdict(unittest.TestCase):

    def test_the_verdict_says_no_test_failed(self):
        verdict = guard._killed_session_verdict("npm run test", KILLED)
        self.assertIn("NO TEST FAILED", verdict)

    def test_the_verdict_names_the_test_and_how_to_rerun_it(self):
        verdict = guard._killed_session_verdict("npm run test", KILLED)
        self.assertIn("test_branch_health_report_structure", verdict)
        self.assertIn("--timeout=300", verdict)

    def test_the_verdict_still_blocks_the_push(self):
        """An unverified suite is not a green one, however sympathetic the cause."""
        self.assertIn("Blocking the push",
                      guard._killed_session_verdict("npm run test", KILLED))

    def test_the_verdict_survives_an_unnameable_dump(self):
        no_main = KILLED.replace("Stack of MainThread (8452218496)",
                                 "Stack of worker-9 (8452218496)")
        verdict = guard._killed_session_verdict("npm run test", no_main)
        self.assertIn("NO TEST FAILED", verdict)
        self.assertIn("<file>", verdict)


if __name__ == "__main__":
    unittest.main()
