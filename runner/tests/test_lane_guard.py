#!/usr/bin/env python3
"""
test_lane_guard.py - proves the zombie-lane root cause is actually fixed.

The claim that matters is NOT "a timeout fires". subprocess.run's timeout also
fired, all day, on 2026-08-02 -- and each firing left the real coder process
alive as an orphan. The load-bearing test here is
test_grandchild_dies_with_the_lane: it spawns a shell that spawns a long-lived
grandchild (exactly the `bash -lc "claude ..."` shape), times the lane out, and
then asserts the GRANDCHILD is gone. test_plain_subprocess_run_orphans_the_
grandchild pins the old behaviour so nobody "simplifies" back to it.
"""
import os
import signal
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lane_guard


def _alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True


def _reap(pid):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.kill(pid, sig)
        except Exception:
            return


class TestTimeoutFor(unittest.TestCase):
    def test_default_is_45_minutes(self):
        self.assertEqual(lane_guard.DEFAULT_LANE_TIMEOUT_S, 2700)

    def test_known_class_uses_its_budget(self):
        self.assertEqual(lane_guard.timeout_for("canary"),
                         lane_guard.CLASS_TIMEOUTS["canary"])

    def test_unknown_class_is_bounded_not_unlimited(self):
        # The dangerous default is "no limit". An unrecognised class is exactly
        # the case that must still be capped.
        self.assertEqual(lane_guard.timeout_for("some-new-class-nobody-added"),
                         lane_guard.DEFAULT_LANE_TIMEOUT_S)

    def test_none_and_empty_class_are_bounded(self):
        self.assertEqual(lane_guard.timeout_for(None), lane_guard.DEFAULT_LANE_TIMEOUT_S)
        self.assertEqual(lane_guard.timeout_for(""), lane_guard.DEFAULT_LANE_TIMEOUT_S)

    def test_class_lookup_is_case_insensitive(self):
        self.assertEqual(lane_guard.timeout_for("CANARY"), lane_guard.timeout_for("canary"))

    def test_env_override_wins(self):
        os.environ["ORCH_LANE_TIMEOUT_CANARY"] = "77"
        try:
            self.assertEqual(lane_guard.timeout_for("canary"), 77)
        finally:
            del os.environ["ORCH_LANE_TIMEOUT_CANARY"]

    def test_garbage_env_override_falls_back(self):
        os.environ["ORCH_LANE_TIMEOUT_CANARY"] = "not-a-number"
        try:
            self.assertEqual(lane_guard.timeout_for("canary"),
                             lane_guard.CLASS_TIMEOUTS["canary"])
        finally:
            del os.environ["ORCH_LANE_TIMEOUT_CANARY"]

    def test_hyphenated_class_maps_to_underscored_env(self):
        os.environ["ORCH_LANE_TIMEOUT_TOOLCHAIN_REPAIR"] = "42"
        try:
            self.assertEqual(lane_guard.timeout_for("toolchain-repair"), 42)
        finally:
            del os.environ["ORCH_LANE_TIMEOUT_TOOLCHAIN_REPAIR"]


class TestRunSupervised(unittest.TestCase):
    def test_normal_command_succeeds_and_captures_stdout(self):
        r = lane_guard.run_supervised(["echo", "hello-lane"], timeout=30)
        self.assertEqual(r["returncode"], 0)
        self.assertIn("hello-lane", r["stdout"])
        self.assertFalse(r["timed_out"])

    def test_stderr_is_captured(self):
        r = lane_guard.run_supervised(
            ["bash", "-c", "echo oops >&2; exit 3"], timeout=30)
        self.assertEqual(r["returncode"], 3)
        self.assertIn("oops", r["stderr"])

    def test_nonzero_exit_is_reported_not_swallowed(self):
        r = lane_guard.run_supervised(["bash", "-c", "exit 7"], timeout=30)
        self.assertEqual(r["returncode"], 7)

    def test_wall_clock_timeout_returns_124(self):
        r = lane_guard.run_supervised(["sleep", "30"], timeout=1)
        self.assertTrue(r["timed_out"])
        self.assertEqual(r["returncode"], 124)
        self.assertLess(r["duration_s"], 15, "timeout must not wait out the sleep")

    def test_idle_kill_returns_125_and_is_distinguishable(self):
        # Silent-but-alive: distinct from wall-clock, so the fleet can tell a
        # slow lane from a wedged one.
        r = lane_guard.run_supervised(["sleep", "30"], timeout=60, idle_timeout=1)
        self.assertTrue(r["idle_killed"])
        self.assertFalse(r["timed_out"])
        self.assertEqual(r["returncode"], 125)

    def test_chatty_lane_is_not_idle_killed(self):
        # A lane that keeps talking must survive a short idle budget -- otherwise
        # the heartbeat kills healthy long-running work.
        r = lane_guard.run_supervised(
            ["bash", "-c", "for i in 1 2 3 4 5 6; do echo tick; sleep 0.4; done"],
            timeout=60, idle_timeout=2)
        self.assertFalse(r["idle_killed"])
        self.assertEqual(r["returncode"], 0)

    def test_missing_binary_is_fail_soft(self):
        r = lane_guard.run_supervised(["definitely-not-a-real-binary-xyz"], timeout=5)
        self.assertNotEqual(r["returncode"], 0)
        self.assertIsInstance(r["stderr"], str)

    def test_result_always_has_the_documented_keys(self):
        r = lane_guard.run_supervised(["true"], timeout=5)
        for k in ("returncode", "stdout", "stderr", "timed_out", "idle_killed",
                  "duration_s", "reap", "pid"):
            self.assertIn(k, r)


class TestOrphanReaping(unittest.TestCase):
    """The actual incident: the lane died, the coder it spawned did not."""

    # `bash -lc` that backgrounds a long sleep and prints its pid -- structurally
    # identical to a lane shelling out to `claude --output-format ...`.
    SPAWNER = 'sleep 300 & echo GRANDCHILD=$!; wait'

    def test_grandchild_dies_with_the_lane(self):
        r = lane_guard.run_supervised(["bash", "-c", self.SPAWNER], timeout=2)
        self.assertTrue(r["timed_out"])
        gpid = None
        for line in r["stdout"].splitlines():
            if line.startswith("GRANDCHILD="):
                gpid = int(line.split("=", 1)[1])
        self.assertIsNotNone(gpid, "test harness failed to report the grandchild pid")
        time.sleep(1.0)  # let SIGKILL land
        try:
            self.assertFalse(
                _alive(gpid),
                f"grandchild {gpid} survived the lane reap -- this IS the zombie bug")
        finally:
            _reap(gpid)

    def test_plain_subprocess_run_orphans_the_grandchild(self):
        """Pins the OLD behaviour so the regression is visible if reverted.

        This is not testing our code -- it is testing the stdlib call the module
        replaced, to document exactly why it had to be replaced.
        """
        p = subprocess.Popen(["bash", "-c", self.SPAWNER],
                             stdout=subprocess.PIPE, text=True)
        gpid = None
        try:
            line = p.stdout.readline()
            gpid = int(line.split("=", 1)[1])
            p.kill()          # what subprocess.run(timeout=) does: child only
            p.wait(timeout=5)
            time.sleep(0.5)
            self.assertTrue(
                _alive(gpid),
                "if this fails the platform changed; the guard is still correct")
        finally:
            if gpid:
                _reap(gpid)

    def test_reap_reports_what_it_signalled(self):
        r = lane_guard.run_supervised(["bash", "-c", self.SPAWNER], timeout=2)
        self.assertTrue(r["reap"].get("termed") or r["reap"].get("killed"))


class TestKillProcessGroup(unittest.TestCase):
    def test_refuses_to_signal_own_process_group(self):
        # A guard that can kill the runner protecting the fleet is worse than
        # no guard. os.getpid() shares our group.
        out = lane_guard.kill_process_group(os.getpid())
        self.assertIn("refusing", out.get("error", ""))
        self.assertFalse(out["termed"])

    def test_missing_pid_is_fail_soft(self):
        self.assertIsInstance(lane_guard.kill_process_group(0), dict)
        out = lane_guard.kill_process_group(999999)
        self.assertIsInstance(out, dict)


if __name__ == "__main__":
    unittest.main()
