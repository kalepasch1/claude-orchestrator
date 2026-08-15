"""Contract: an external watchdog cannot restart this runner into uselessness.

THE BUG THIS PINS (2026-08-04). fleet_control's storm guard only superseded restarts that
were pending SIMULTANEOUSLY. A watchdog inserting ONE restart per hour had every row
honored, because each was the newest when it arrived — observed at 20:28, 21:27, 22:28,
23:28 and 00:28, all acted on by this host.

It is self-reinforcing, which is what makes it fatal rather than merely wasteful: agentic
tasks take minutes, the runner exits mid-flight, in-flight tasks orphan back to QUEUED, the
completion counters the watchdog reads stay at zero, and it requests another restart. The
fleet spends its life restarting and reloading config — thousands of tasks "claimed",
almost nothing shipped.

Second invariant: a control action that can never succeed must stop retrying. Real rows
were found at 975, 304 and 247 attempts, all failing on conditions no retry could clear.
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fleet_control as fc  # noqa: E402


class RestartCooldown(unittest.TestCase):
    def setUp(self):
        self._stamp = fc._RESTART_STAMP
        self._had = os.path.exists(self._stamp)
        if self._had:
            self._mtime = os.path.getmtime(self._stamp)

    def tearDown(self):
        if self._had:
            with open(self._stamp, "a"):
                pass
            os.utime(self._stamp, (self._mtime, self._mtime))
        elif os.path.exists(self._stamp):
            os.remove(self._stamp)

    def test_no_cooldown_when_never_restarted(self):
        if os.path.exists(self._stamp):
            os.remove(self._stamp)
        active, _ = fc._restart_cooldown()
        self.assertFalse(active, "a first restart must be allowed")

    def test_cooldown_active_immediately_after_restart(self):
        fc._stamp_restart()
        active, mins = fc._restart_cooldown()
        self.assertTrue(active, "a second restart inside the window must be suppressed")
        self.assertGreater(mins, 0)

    def test_cooldown_expires(self):
        fc._stamp_restart()
        # backdate the stamp beyond the window
        old = time.time() - (fc.RESTART_COOLDOWN_MIN * 60) - 60
        os.utime(self._stamp, (old, old))
        active, _ = fc._restart_cooldown()
        self.assertFalse(active, "cooldown must expire so real restarts still work")

    def test_window_is_longer_than_a_typical_watchdog_interval(self):
        # The observed storm was hourly. A cooldown at or under 60 min would not stop it.
        self.assertGreaterEqual(
            fc.RESTART_COOLDOWN_MIN, 61,
            "cooldown must exceed the hourly watchdog cadence that caused the storm")

    def test_cooldown_can_be_disabled_explicitly(self):
        saved = fc.RESTART_COOLDOWN_MIN
        try:
            fc.RESTART_COOLDOWN_MIN = 0
            fc._stamp_restart()
            active, _ = fc._restart_cooldown()
            self.assertFalse(active, "0 must disable the cooldown entirely")
        finally:
            fc.RESTART_COOLDOWN_MIN = saved


class ActionAttemptCap(unittest.TestCase):
    def test_cap_is_set_and_small(self):
        self.assertGreater(fc.MAX_ACTION_ATTEMPTS, 0)
        self.assertLessEqual(fc.MAX_ACTION_ATTEMPTS, 20,
                             "rows were found at 975 attempts; the cap must be small")

    def test_handler_parks_exhausted_rows(self):
        import inspect
        src = inspect.getsource(fc.process_controls)
        self.assertIn("MAX_ACTION_ATTEMPTS", src)
        self.assertIn("GAVE UP", src, "exhausted rows must be parked with a visible reason")


if __name__ == "__main__":
    unittest.main()
