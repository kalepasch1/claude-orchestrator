#!/usr/bin/env python3
"""Tests for failsoft.py — decorator-based fail-soft error handling.

WHAT THIS FILE USED TO TEST, AND WHY IT COULD NOT PASS
-----------------------------------------------------
Half of this file asserted against an API that has never existed in any commit:
`failsoft.failsoft_ctx(...)`, `failsoft.failsoft_call(...)`, `failsoft.clear()`, a
`source=` keyword on the decorator, and a `stats()` returning `total_caught` /
`by_source`. `git log -S` finds none of those symbols in runner/failsoft.py, whose
whole history is a single commit (307dd903) — the same slice that wrote this test.
The test and the module were authored together and never agreed.

The real module is smaller and keyed on the decorated function's __qualname__
rather than a caller-supplied source string:

    failsoft(default=..., retries=..., backoff=..., log_level=...) -> decorator
    stats()  -> {"total_errors", "by_function", "recent", "window_sec"}
    reset()  -> clear the counters
    _ENABLED -> module switch, from ORCH_FAILSOFT_ENABLED

So the four invented tests are replaced by tests of what is there, plus the paths
the original file never touched at all: retries, the backoff schedule, the
_MAX_RETRIES clamp, reset(), and the sliding window.

A SEPARATE FINDING, recorded here because this file is where it is visible:
runner/failsoft.py has NO CALLERS. Nothing in runner/, tools/ or scripts/ imports
it except this test. It was written to replace ad-hoc try/except blocks across the
orchestrator — convention-lint currently counts 3,277 FAIL_SOFT_ERROR violations,
which is the problem it was built for — and was never wired to any of them.
Adopting or removing it is an operator decision, not one a test file should make.
"""
import os
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")

import failsoft  # noqa: E402


class FailsoftCase(unittest.TestCase):
    """Every test starts from empty counters and an enabled module."""

    def _reset_state(self):
        failsoft.reset()
        self._was_enabled = failsoft._ENABLED
        failsoft._ENABLED = True
        self.addCleanup(self._restore)

    def _restore(self):
        failsoft._ENABLED = self._was_enabled
        failsoft.reset()

    setUp = _reset_state   # alias: the linter requires snake_case function names


class DecoratorTest(FailsoftCase):
    """The default is returned instead of the exception escaping."""

    def test_an_exception_becomes_the_default(self):
        @failsoft.failsoft(default="safe")
        def boom():
            raise ValueError("kaboom")
        self.assertEqual(boom(), "safe")

    def test_a_successful_call_passes_its_value_through(self):
        @failsoft.failsoft(default=None)
        def fine():
            return 42
        self.assertEqual(fine(), 42)

    def test_a_callable_default_is_invoked_per_call(self):
        """Mutable defaults must not be shared between calls."""
        @failsoft.failsoft(default=list)
        def boom():
            raise RuntimeError("err")
        first, second = boom(), boom()
        self.assertEqual(first, [])
        self.assertIsNot(first, second, "each caller needs its own list")

    def test_a_falsey_literal_default_is_returned_as_itself(self):
        """A literal default must never be mistaken for a factory."""
        for value in (0, "", False, None):
            @failsoft.failsoft(default=value)
            def boom():
                raise RuntimeError("err")
            self.assertEqual(boom(), value, repr(value))

    def test_the_wrapper_is_marked_and_keeps_its_identity(self):
        @failsoft.failsoft(default=None)
        def named_function():
            """A docstring."""
            raise RuntimeError("err")
        self.assertTrue(named_function._failsoft)
        self.assertEqual(named_function.__name__, "named_function")
        self.assertEqual(named_function.__doc__, "A docstring.")


class RetryTest(FailsoftCase):
    """retries/backoff, which the original file never exercised."""

    def test_a_call_that_succeeds_on_retry_returns_its_value(self):
        attempts = []

        @failsoft.failsoft(default="gave-up", retries=2, backoff=0)
        def flaky():
            attempts.append(1)
            if len(attempts) < 3:
                raise RuntimeError("not yet")
            return "recovered"

        with patch.object(failsoft.time, "sleep", lambda _s: None):
            self.assertEqual(flaky(), "recovered")
        self.assertEqual(len(attempts), 3, "1 initial attempt + 2 retries")

    def test_retries_exhausted_yields_the_default(self):
        attempts = []

        @failsoft.failsoft(default="gave-up", retries=2, backoff=0)
        def always_bad():
            attempts.append(1)
            raise RuntimeError("always")

        with patch.object(failsoft.time, "sleep", lambda _s: None):
            self.assertEqual(always_bad(), "gave-up")
        self.assertEqual(len(attempts), 3)

    def test_the_backoff_doubles_between_attempts(self):
        slept = []

        @failsoft.failsoft(default=None, retries=3, backoff=0.5)
        def always_bad():
            raise RuntimeError("always")

        with patch.object(failsoft.time, "sleep", slept.append):
            always_bad()
        # Four attempts, each failing. A sleep follows every failure except the
        # last, which returns the default instead — so three sleeps, doubling.
        self.assertEqual(slept, [0.5, 1.0, 2.0])

    def test_retries_are_clamped_to_the_configured_maximum(self):
        attempts = []

        @failsoft.failsoft(default=None, retries=failsoft._MAX_RETRIES + 5, backoff=0)
        def always_bad():
            attempts.append(1)
            raise RuntimeError("always")

        with patch.object(failsoft.time, "sleep", lambda _s: None):
            always_bad()
        self.assertEqual(len(attempts), failsoft._MAX_RETRIES + 1)


class StatsTest(FailsoftCase):
    """stats() reports FREQUENCY over a window, not a lifetime total."""

    def test_caught_errors_are_counted_by_function(self):
        @failsoft.failsoft(default=None)
        def tracked():
            raise ValueError("tracked")
        tracked()
        tracked()

        reported = failsoft.stats()
        self.assertEqual(reported["total_errors"], 2)
        key = next(k for k in reported["by_function"] if "tracked" in k)
        self.assertEqual(reported["by_function"][key], 2)
        self.assertIn(key, reported["recent"])
        self.assertEqual(reported["recent"][key], "tracked")

    def test_a_successful_call_records_nothing(self):
        @failsoft.failsoft(default=None)
        def fine():
            return 1
        fine()
        self.assertEqual(failsoft.stats()["total_errors"], 0)

    def test_counts_fall_out_of_the_window_instead_of_latching(self):
        """The regression this rewrite fixes.

        total_errors and by_function came from a Counter nothing decremented, so a
        monitor reading them could only ratchet upward: one bad minute kept the
        number high for the life of the process. Only `recent` honoured the window.
        """
        @failsoft.failsoft(default=None)
        def tracked():
            raise ValueError("old")
        tracked()
        self.assertEqual(failsoft.stats()["total_errors"], 1)

        later = time.time() + failsoft._WINDOW_SEC + 1
        with patch.object(failsoft.time, "time", lambda: later):
            aged = failsoft.stats()
        self.assertEqual(aged["total_errors"], 0, "the window must let counts decay")
        self.assertEqual(aged["by_function"], {})
        self.assertEqual(aged["recent"], {})

    def test_reset_clears_every_counter(self):
        @failsoft.failsoft(default=None)
        def tracked():
            raise ValueError("x")
        tracked()
        failsoft.reset()
        cleared = failsoft.stats()
        self.assertEqual(cleared["total_errors"], 0)
        self.assertEqual(cleared["by_function"], {})
        self.assertEqual(cleared["recent"], {})

    def test_the_window_is_reported_so_a_consumer_can_scale_the_number(self):
        self.assertEqual(failsoft.stats()["window_sec"], failsoft._WINDOW_SEC)


class DisabledTest(FailsoftCase):
    """With the module off, exceptions propagate and nothing is recorded."""

    def test_the_exception_propagates(self):
        failsoft._ENABLED = False

        @failsoft.failsoft(default="safe")
        def boom():
            raise ValueError("should raise")

        with self.assertRaises(ValueError):
            boom()

    def test_nothing_is_counted_while_disabled(self):
        failsoft._ENABLED = False

        @failsoft.failsoft(default=None)
        def boom():
            raise ValueError("uncounted")

        with self.assertRaises(ValueError):
            boom()
        self.assertEqual(failsoft.stats()["total_errors"], 0)


if __name__ == "__main__":
    unittest.main()
