#!/usr/bin/env python3
"""Behavioural guard on runner task logging.

`emit_task_log` was once called from `run_task` without being defined, so every task that
produced output died on `NameError: name 'emit_task_log' is not defined` — the runner's own
repair-ceiling detector still carries that string as a known failure signature
(runner/test_repair_ceiling.py).

The function exists again, and runner/tests/test_emit_task_log.py guards it. But that suite is
almost entirely SOURCE-TEXT assertions — `assertIn("def emit_task_log(", src)`, and
`assertIn('"run_logs"', body)`. Those cannot catch this bug class: a NameError is a runtime
resolution failure, and grepping the file for a `def` never resolves anything. A typo'd call
site, a definition moved below its caller inside a conditional, or a mis-scoped import would
all pass a source grep and still take down every task.

So this file EXECUTES the path instead of reading it: a stub task goes through
`_run_task_safe`, and we assert no NameError escapes and a log line carrying the stub's slug
is produced.
"""
import os
import sys
import types
import unittest
from unittest.mock import patch

RUNNER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
if RUNNER_DIR not in sys.path:
    sys.path.insert(0, RUNNER_DIR)

# Load runner/runner.py by explicit path rather than `import runner`. The repo has BOTH a
# `runner/` package (with __init__.py) and a `runner/runner.py` module, so the bare name
# resolves to whichever won the race — under a whole-suite run another test module puts the
# package in sys.modules first and `runner._log_mod` then does not exist. Addressing the file
# directly removes the ambiguity, and the module is registered under a private name so this
# never becomes the thing that shadows it for someone else.
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "_runner_module_under_test", os.path.join(RUNNER_DIR, "runner.py"))
runner = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("_runner_module_under_test", runner)
_spec.loader.exec_module(runner)


class _CapturingLogger:
    """Stands in for the pino-style logger; records (level, rendered message)."""

    def __init__(self):
        self.lines = []

    def _rec(self, level):
        def _fn(fmt, *args):
            try:
                self.lines.append((level, fmt % args if args else str(fmt)))
            except Exception:
                self.lines.append((level, str(fmt)))
        return _fn

    def __getattr__(self, name):
        if name in ("debug", "info", "warning", "error", "critical"):
            return self._rec(name)
        raise AttributeError(name)


class TestEmitTaskLogExecutes(unittest.TestCase):
    """Direct execution — the assertions the source-grep suite structurally cannot make."""

    def setUp(self):
        self.logger = _CapturingLogger()
        p = patch.object(runner._log_mod, "get", return_value=self.logger)
        p.start()
        self.addCleanup(p.stop)
        # emit_task_log records to run_logs; a DB outage must not be what fails this test.
        d = patch.object(runner.db, "insert", return_value=None)
        d.start()
        self.addCleanup(d.stop)

    def test_emit_task_log_is_callable_and_resolves(self):
        runner.emit_task_log("stub-slug", "info", "hello world")
        self.assertTrue(self.logger.lines, "emit_task_log produced no log line")
        level, msg = self.logger.lines[-1]
        self.assertEqual(level, "info")
        self.assertIn("stub-slug", msg)
        self.assertIn("hello world", msg)

    def test_unknown_level_degrades_to_info_rather_than_raising(self):
        runner.emit_task_log("stub-slug", "not-a-level", "msg")
        self.assertEqual(self.logger.lines[-1][0], "info")

    def test_error_level_is_honoured(self):
        runner.emit_task_log("stub-slug", "error", "boom")
        self.assertEqual(self.logger.lines[-1][0], "error")

    def test_db_failure_does_not_propagate(self):
        """Logging a task must never be what kills the task."""
        with patch.object(runner.db, "insert", side_effect=RuntimeError("db down")):
            runner.emit_task_log("stub-slug", "info", "still fine")
        self.assertIn("stub-slug", self.logger.lines[-1][1])

    def test_long_message_is_truncated_for_the_db(self):
        captured = {}
        with patch.object(runner.db, "insert",
                          side_effect=lambda t, row: captured.update(row)):
            runner.emit_task_log("stub-slug", "info", "x" * 5000)
        self.assertLessEqual(len(captured.get("message", "")), 2000)


class TestStubTaskThroughRunTaskSafe(unittest.TestCase):
    """The acceptance criterion: a stub task through _run_task_safe raises no NameError.

    _run_task_safe swallows exceptions by design, so asserting "it did not raise" would pass
    even if run_task were exploding on every call. We therefore capture what it swallowed and
    assert specifically that a NameError was NOT among it.
    """

    def _run_stub(self, run_task_impl):
        swallowed = []
        with patch.object(runner, "run_task", side_effect=run_task_impl), \
             patch.object(runner, "_touch_progress", return_value=None), \
             patch.object(runner, "set_state",
                          side_effect=lambda *a, **k: swallowed.append(k.get("log_tail", ""))), \
             patch.object(runner, "_block_or_retry", return_value=None):
            runner._run_task_safe({"id": "stub-id", "slug": "stub-slug"})
        return swallowed

    def test_stub_task_produces_no_name_error(self):
        logger = _CapturingLogger()
        with patch.object(runner._log_mod, "get", return_value=logger), \
             patch.object(runner.db, "insert", return_value=None):
            def _impl(t):
                # Stands in for run_task's real logging step (runner.py ~1746).
                runner.emit_task_log(t["slug"], "info", "stub task output")
            swallowed = self._run_stub(_impl)

        joined = "\n".join(swallowed)
        self.assertNotIn("NameError", joined,
                         f"_run_task_safe swallowed a NameError:\n{joined[-1500:]}")
        self.assertTrue(any("stub-slug" in msg for _, msg in logger.lines),
                        "no log line carrying the stub slug was produced")

    def test_a_real_name_error_would_be_caught_by_this_test(self):
        """Negative control. Without this, the test above could pass vacuously."""
        def _impl(t):
            undefined_symbol_for_this_test()  # noqa: F821
        swallowed = self._run_stub(_impl)
        self.assertIn("NameError", "\n".join(swallowed),
                      "the harness cannot observe a NameError, so the guard is vacuous")


class TestCallSiteIsResolvable(unittest.TestCase):
    """The definition must precede its use at module scope, unconditionally."""

    def test_emit_task_log_is_a_module_level_function(self):
        self.assertIsInstance(runner.emit_task_log, types.FunctionType)

    def test_definition_precedes_every_call_site(self):
        src = open(os.path.join(RUNNER_DIR, "runner.py"), encoding="utf-8").read()
        definition = src.index("def emit_task_log(")
        call = src.index("emit_task_log(slug,")
        self.assertLess(definition, call,
                        "emit_task_log is called before it is defined")


if __name__ == "__main__":
    unittest.main()
