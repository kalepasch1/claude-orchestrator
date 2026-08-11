#!/usr/bin/env python3
"""
test_single_instance.py - proves interval daemons can no longer stack.

The 2026-08-02 shape: legal_docket.py on a 30-minute interval accumulated 14
concurrent copies, the oldest 8-10h old. Each tick started unconditionally
because nothing asked whether the previous one had finished.

The critical property is cross-PROCESS, not cross-thread: the second tick is a
separate `python3 legal_docket.py`, so a module-level flag or an in-process
threading.Lock would prove nothing. Every exclusion test here therefore uses a
real second process.
"""
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import single_instance

RUNNER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


class _TmpLockDir(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.mkdtemp()
        self._old = single_instance.LOCK_DIR
        single_instance.LOCK_DIR = self._d
        os.environ["ORCH_SINGLE_INSTANCE_LOCK_DIR"] = self._d

    def tearDown(self):
        single_instance.LOCK_DIR = self._old
        os.environ.pop("ORCH_SINGLE_INSTANCE_LOCK_DIR", None)


class TestHold(_TmpLockDir):
    def test_first_holder_owns_the_lock(self):
        with single_instance.hold("job-a") as owned:
            self.assertTrue(owned)

    def test_lock_is_released_after_the_block(self):
        with single_instance.hold("job-b") as owned:
            self.assertTrue(owned)
        with single_instance.hold("job-b") as owned2:
            self.assertTrue(owned2, "a finished tick must not block the next one")

    def test_different_jobs_do_not_block_each_other(self):
        with single_instance.hold("job-c") as a:
            with single_instance.hold("job-d") as b:
                self.assertTrue(a and b)

    def test_lock_records_the_holder_pid(self):
        with single_instance.hold("job-e"):
            self.assertEqual(single_instance.holder_pid("job-e"), os.getpid())

    def test_name_with_path_separators_cannot_escape_lock_dir(self):
        # A job name is not a path. "../../etc/passwd" must stay inside LOCK_DIR.
        p = single_instance.lock_path("../../etc/passwd")
        self.assertEqual(os.path.dirname(os.path.abspath(p)),
                         os.path.abspath(single_instance.LOCK_DIR))

    def test_infrastructure_failure_runs_rather_than_skips(self):
        # Fail-soft direction matters: a broken lock must not silently disable
        # the job forever. Point LOCK_DIR at an unusable location.
        single_instance.LOCK_DIR = "/proc/nonexistent/cannot/create"
        try:
            with single_instance.hold("job-f") as owned:
                self.assertTrue(owned)
        finally:
            single_instance.LOCK_DIR = self._d


_HOLDER = textwrap.dedent("""
    import os, sys, time
    sys.path.insert(0, {runner!r})
    import single_instance
    single_instance.LOCK_DIR = {lockdir!r}
    with single_instance.hold("shared-job") as owned:
        print("OWNED" if owned else "SKIPPED", flush=True)
        time.sleep(float(sys.argv[1]))
""")


class TestCrossProcessExclusion(_TmpLockDir):
    """The property that actually prevents the 14-copy pile-up."""

    def _spawn(self, hold_s):
        src = _HOLDER.format(runner=RUNNER_DIR, lockdir=self._d)
        return subprocess.Popen([sys.executable, "-c", src, str(hold_s)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True)

    def test_second_tick_skips_while_first_is_live(self):
        first = self._spawn(4)
        try:
            self.assertEqual(first.stdout.readline().strip(), "OWNED")
            second = self._spawn(0)
            out, _ = second.communicate(timeout=30)
            self.assertIn("SKIPPED", out,
                          "a tick that finds the previous one live must skip")
        finally:
            first.kill()
            first.wait(timeout=10)

    def test_next_tick_acquires_after_the_first_exits(self):
        first = self._spawn(0.2)
        self.assertEqual(first.stdout.readline().strip(), "OWNED")
        first.wait(timeout=30)
        second = self._spawn(0)
        out, _ = second.communicate(timeout=30)
        self.assertIn("OWNED", out)

    def test_killed_holder_does_not_block_forever(self):
        # flock, not a PID file: the kernel drops the lock when the holder dies,
        # so a SIGKILLed daemon cannot lock itself out of its own restart.
        first = self._spawn(60)
        self.assertEqual(first.stdout.readline().strip(), "OWNED")
        first.kill()
        first.wait(timeout=10)
        time.sleep(0.3)
        second = self._spawn(0)
        out, _ = second.communicate(timeout=30)
        self.assertIn("OWNED", out, "a dead holder must not wedge the job permanently")

    def test_is_locked_reflects_a_live_holder(self):
        first = self._spawn(4)
        try:
            self.assertEqual(first.stdout.readline().strip(), "OWNED")
            self.assertTrue(single_instance.is_locked("shared-job"))
        finally:
            first.kill()
            first.wait(timeout=10)
        time.sleep(0.3)
        self.assertFalse(single_instance.is_locked("shared-job"))


class TestMaxRuntime(_TmpLockDir):
    def test_deadline_is_interval_times_factor(self):
        self.assertAlmostEqual(single_instance.max_runtime_for(1800), 1800 * 1.5)

    def test_explicit_factor_overrides(self):
        self.assertAlmostEqual(single_instance.max_runtime_for(100, factor=3), 300)

    def test_bad_interval_disarms_rather_than_crashes(self):
        for bad in (None, 0, -5, "abc"):
            self.assertEqual(single_instance.max_runtime_for(bad), 0.0)

    def test_watchdog_fires_after_the_deadline(self):
        fired = []
        t = single_instance.enforce_max_runtime(
            0.2, factor=1, name="t", _exit=lambda: fired.append(True))
        self.assertIsNotNone(t)
        time.sleep(0.6)
        self.assertTrue(fired, "a hung tick must self-terminate")

    def test_watchdog_can_be_cancelled_by_a_healthy_run(self):
        fired = []
        t = single_instance.enforce_max_runtime(
            1, factor=1, name="t", _exit=lambda: fired.append(True))
        t.cancel()
        time.sleep(1.4)
        self.assertFalse(fired, "a finished tick must not kill its own process")

    def test_not_armed_when_no_interval(self):
        self.assertIsNone(single_instance.enforce_max_runtime(0))


class TestGuard(_TmpLockDir):
    def test_guard_returns_owned_and_timer(self):
        owned, timer = single_instance.guard("guarded-job", interval_s=3600)
        self.assertTrue(owned)
        self.assertIsNotNone(timer)
        timer.cancel()

    def test_guard_without_interval_arms_no_timer(self):
        owned, timer = single_instance.guard("guarded-job-2")
        self.assertTrue(owned)
        self.assertIsNone(timer)

    def test_legal_docket_entrypoint_is_guarded(self):
        path = os.path.join(RUNNER_DIR, "legal_docket.py")
        with open(path) as f:
            source = f.read()
        self.assertIn('single_instance.guard("legal_docket", interval_s=1800)', source)

    def test_keepalive_rechecks_maintenance_lock_inside_restart_loop(self):
        path = os.path.join(RUNNER_DIR, "keepalive.sh")
        with open(path) as f:
            source = f.read()
        loop = source[source.index("while true; do"):]
        maintenance_check = loop.index('[[ -e "$MAINTENANCE_LOCK" ]]')
        runner_start = loop.index("python3 runner.py")
        self.assertLess(maintenance_check, runner_start)

if __name__ == "__main__":
    unittest.main()
