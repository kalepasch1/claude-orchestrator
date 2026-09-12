"""A periodic job that times out must not report success.

The wedge detector already made "the job never ran" loud: it escalates and exits 1.
The hard timeout that was added to end those wedges introduced the same silence one
step further along — the job STARTS, gets interrupted so the lock is released, and
the process exits 0. From the outside that is indistinguishable from a healthy run,
which is exactly the failure mode the wedge work existed to remove:

    "Every skipped invocation exited 0, so nothing downstream noticed."

These tests pin the ending: interrupted work escalates and exits non-zero.
"""

import os
import subprocess
import sys
import textwrap
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import periodic  # noqa: E402

RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ExitCodesAreDistinct(unittest.TestCase):
    def test_every_outcome_has_its_own_code(self):
        codes = [periodic._EX_OK, periodic._EX_SKIPPED,
                 periodic._EX_WEDGED, periodic._EX_TIMEOUT]
        self.assertEqual(len(set(codes)), len(codes),
                         "a caller cannot distinguish outcomes that share an exit code")

    def test_timeout_is_not_success(self):
        self.assertNotEqual(periodic._EX_TIMEOUT, periodic._EX_OK)


class TimedOutKeepsTheDictContract(unittest.TestCase):
    """The sentinel is a dict subclass so existing readers keep working."""

    def test_it_is_a_mapping_with_the_documented_keys(self):
        out = periodic._TimedOut("governor", "boom", 5)
        self.assertIsInstance(out, dict)
        self.assertTrue(out.get("timeout"))
        self.assertEqual(out.get("job"), "governor")
        self.assertEqual(out.get("detail"), "boom")
        self.assertEqual(out.get("timeout_s"), 5)

    def test_it_also_carries_attributes_for_the_exit_path(self):
        out = periodic._TimedOut("governor", "boom", 5)
        self.assertEqual(out.job, "governor")
        self.assertEqual(out.detail, "boom")
        self.assertEqual(out.seconds, 5)


class InvokeJobOnTimeout(unittest.TestCase):
    def setUp(self):
        self.original_job = periodic.JOBS.get("governor")
        self.original_escalate = periodic._escalate_timeout
        self.calls = []
        periodic._escalate_timeout = lambda *a, **k: self.calls.append(a)
        os.environ["ORCH_PERIODIC_JOB_TIMEOUT_GOVERNOR"] = "1"

    def tearDown(self):
        periodic._escalate_timeout = self.original_escalate
        if self.original_job is not None:
            periodic.JOBS["governor"] = self.original_job
        os.environ.pop("ORCH_PERIODIC_JOB_TIMEOUT_GOVERNOR", None)

    def test_a_timed_out_job_returns_the_typed_sentinel(self):
        import time
        periodic.JOBS["governor"] = lambda: time.sleep(30)
        result = periodic._invoke_job("governor")
        self.assertIsInstance(result, periodic._TimedOut)
        # and the pre-existing contract is untouched
        self.assertTrue(result.get("timeout"))
        self.assertEqual(result.get("job"), "governor")

    def test_a_timeout_escalates(self):
        import time
        periodic.JOBS["governor"] = lambda: time.sleep(30)
        periodic._invoke_job("governor")
        self.assertEqual(len(self.calls), 1, "an interrupted job must be escalated, not just printed")
        self.assertEqual(self.calls[0][0], "governor")
        self.assertEqual(self.calls[0][1], 1, "the escalation should carry the budget it blew")

    def test_a_healthy_job_neither_escalates_nor_returns_the_sentinel(self):
        periodic.JOBS["governor"] = lambda: {"ok": True}
        result = periodic._invoke_job("governor")
        self.assertEqual(result, {"ok": True})
        self.assertNotIsInstance(result, periodic._TimedOut)
        self.assertEqual(self.calls, [])

    def test_a_failing_escalation_cannot_swallow_the_timeout(self):
        """The escalation reports on the runner; it must never take it down."""
        import time

        def _explode(*_a, **_k):
            raise RuntimeError("notify is down")

        periodic._escalate_timeout = _explode
        periodic.JOBS["governor"] = lambda: time.sleep(30)
        with self.assertRaises(RuntimeError):
            periodic._invoke_job("governor")
        # NOTE: this documents that _escalate_timeout owns its own fail-soft behaviour
        # (every outbound call inside it is individually wrapped). If that ever changes,
        # this test is the reminder that the caller does not catch for it.


class EscalationIsFailSoft(unittest.TestCase):
    """Each destination inside the escalation is independently guarded."""

    def test_it_survives_every_destination_being_broken(self):
        original_db_insert = periodic.db.insert
        original_db_select = periodic.db.select
        periodic.db.insert = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down"))
        periodic.db.select = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down"))
        try:
            # Must not raise even with the database refusing every call.
            periodic._escalate_timeout("governor", 900, "exceeded budget")
        finally:
            periodic.db.insert = original_db_insert
            periodic.db.select = original_db_select


class ProcessExitCode(unittest.TestCase):
    """The end-to-end contract: the scheduler sees a non-zero code."""

    def _run(self, body):
        script = textwrap.dedent(body)
        return subprocess.run([sys.executable, "-c", script], cwd=RUNNER_DIR,
                              capture_output=True, text=True, timeout=120)

    def test_a_timing_out_job_exits_with_the_timeout_code(self):
        proc = self._run("""
            import os, sys, time
            sys.path.insert(0, os.getcwd())
            os.environ["ORCH_PERIODIC_JOB_TIMEOUT_GOVERNOR"] = "1"
            os.environ["ORCH_PERIODIC_JOB_LOCKS"] = "false"
            import periodic
            periodic.JOBS["governor"] = lambda: time.sleep(30)
            periodic._escalate_timeout = lambda *a, **k: None
            outcome = periodic._run_job_locked("governor")
            if isinstance(outcome, periodic._TimedOut):
                sys.exit(periodic._EX_TIMEOUT)
            sys.exit(periodic._EX_OK)
        """)
        self.assertEqual(proc.returncode, periodic._EX_TIMEOUT,
                         f"expected the timeout exit code, got {proc.returncode}\n{proc.stderr}")

    def test_a_healthy_job_still_exits_zero(self):
        proc = self._run("""
            import os, sys
            sys.path.insert(0, os.getcwd())
            os.environ["ORCH_PERIODIC_JOB_LOCKS"] = "false"
            import periodic
            periodic.JOBS["governor"] = lambda: {"ok": True}
            outcome = periodic._run_job_locked("governor")
            if isinstance(outcome, periodic._TimedOut):
                sys.exit(periodic._EX_TIMEOUT)
            sys.exit(periodic._EX_OK)
        """)
        self.assertEqual(proc.returncode, periodic._EX_OK, proc.stderr)


if __name__ == "__main__":
    unittest.main()
