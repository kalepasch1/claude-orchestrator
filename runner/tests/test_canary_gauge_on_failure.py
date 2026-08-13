#!/usr/bin/env python3
"""`canary_last_success` must be 0 after ANY non-success, including a crash.

The gauge exists so an alert can ask `time() - canary_last_success > threshold`. That
question is only meaningful if every failure clears it — a gauge left holding the last
successful timestamp reports health it has no evidence for, which is worse than no gauge,
because it actively suppresses the alert.

The rollback verdict already cleared it. An EXCEPTION out of `evaluate()` did not: it
propagated through `main()` and neither branch ran, so a canary crashing on every single
run looked green to every staleness alert. These pin both routes shut.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import canary


class GaugeTestCase(unittest.TestCase):
    def setUp(self):
        canary.record_success(12345.0)
        self.assertEqual(canary.canary_last_success.get(), 12345.0,
                         "fixture must start from a NON-zero gauge, or the assertions "
                         "below pass without the code doing anything")
        self._print = patch("builtins.print")
        self._print.start()
        self.addCleanup(self._print.stop)


class TestVerdictFailure(GaugeTestCase):
    def test_rollback_verdict_zeroes_the_gauge(self):
        with patch.object(canary, "evaluate",
                          return_value={"verdict": "rollback", "reason": "p95 breached"}):
            self.assertEqual(canary.main([]), 1)
        self.assertEqual(canary.canary_last_success.get(), 0)

    def test_promote_verdict_sets_a_real_timestamp(self):
        with patch.object(canary, "evaluate",
                          return_value={"verdict": "promote", "reason": "ok"}):
            self.assertEqual(canary.main([]), 0)
        self.assertGreater(canary.canary_last_success.get(), 12345.0)

    def test_an_unknown_verdict_counts_as_failure(self):
        # Fail closed: anything that is not an explicit promote must not leave a
        # success timestamp standing.
        with patch.object(canary, "evaluate", return_value={"verdict": "???"}):
            self.assertEqual(canary.main([]), 1)
        self.assertEqual(canary.canary_last_success.get(), 0)

    def test_a_missing_verdict_counts_as_failure(self):
        with patch.object(canary, "evaluate", return_value={}):
            self.assertEqual(canary.main([]), 1)
        self.assertEqual(canary.canary_last_success.get(), 0)


class TestCrashAlsoZeroesTheGauge(GaugeTestCase):
    def test_an_exception_out_of_evaluate_zeroes_the_gauge(self):
        """The route that was open.

        Without this, a canary raising on every run keeps reporting the timestamp of the
        last run that worked — the staleness alert never fires and the crash is invisible.
        """
        with patch.object(canary, "evaluate", side_effect=RuntimeError("metrics malformed")):
            self.assertEqual(canary.main([]), 1)
        self.assertEqual(canary.canary_last_success.get(), 0)

    def test_a_crash_reports_a_rollback_verdict_naming_the_error(self):
        printed = []
        self._print.stop()
        with patch("builtins.print", side_effect=lambda *a, **k: printed.append(a[0])), \
             patch.object(canary, "evaluate", side_effect=ValueError("bad threshold")):
            canary.main([])
        self._print.start()
        self.assertTrue(printed)
        self.assertIn("rollback", printed[0])
        self.assertIn("ValueError", printed[0])
        self.assertIn("bad threshold", printed[0])

    def test_a_crash_does_not_propagate_out_of_main(self):
        # main() is a CLI entrypoint; a traceback instead of an exit code breaks every
        # shell caller that gates a deploy on the return value.
        with patch.object(canary, "evaluate", side_effect=RuntimeError("boom")):
            try:
                result = canary.main([])
            except RuntimeError:
                self.fail("main() must not leak the exception to its shell caller")
        self.assertEqual(result, 1)
        self.assertEqual(canary.canary_last_success.get(), 0)

    def test_an_operator_interrupt_is_NOT_swallowed(self):
        """Ctrl-C is not a canary failure and must not be reported as a rollback.

        `except Exception` deliberately does not catch BaseException, so KeyboardInterrupt
        and SystemExit still propagate. Catching them would make a deliberate interrupt
        indistinguishable from a real deploy regression, and would make the process
        awkward to kill.
        """
        for interrupt in (KeyboardInterrupt, SystemExit):
            with self.subTest(interrupt=interrupt.__name__):
                with patch.object(canary, "evaluate", side_effect=interrupt):
                    with self.assertRaises(interrupt):
                        canary.main([])

    def test_every_exception_type_clears_the_gauge(self):
        for exc in (RuntimeError("x"), ValueError("y"), OSError("z"), TypeError("t")):
            with self.subTest(exc=type(exc).__name__):
                canary.record_success(999.0)
                with patch.object(canary, "evaluate", side_effect=exc):
                    self.assertEqual(canary.main([]), 1)
                self.assertEqual(canary.canary_last_success.get(), 0)


class TestGaugeIsObservable(GaugeTestCase):
    def test_the_zero_reaches_the_metrics_endpoint(self):
        # A gauge that is correct in memory but not rendered helps nobody.
        with patch.object(canary, "evaluate", side_effect=RuntimeError("boom")):
            canary.main([])
        body = canary.render_metrics().decode()
        self.assertIn("canary_last_success 0", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
