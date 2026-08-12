#!/usr/bin/env python3
"""Regression pins for the crash-free-until-used defect class in runner/canary.py.

`validate_canary` was duplicated verbatim by a merge and both copies referenced `_log`,
which the module never bound (`logging` was not imported). Python resolves globals at
CALL time, so `import canary` succeeded and every call raised NameError — the failure
only surfaced in production, at deploy-gate time.

`static_sanity.audit()` had been reporting the six findings the whole time. The gate
stayed quiet because `assert_critical()` only looks at `CRITICAL_MODULES`, and neither
`canary.py` nor `periodic.py` was on it.

So there are two things to pin, and pinning only the first lets the class recur:
  1. the binding itself — `validate_canary` must actually run;
  2. the gate coverage — the dispatcher modules must be watched, so the *next* dropped
     definition refuses to start instead of silently no-opping.

Test 3 is the one that matters. It reads the source rather than the imported module
because a duplicate `def` is invisible after import: the second binding simply wins.
"""
import ast
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER = os.path.join(REPO, "runner")
sys.path.insert(0, RUNNER)

import canary  # noqa: E402
import static_sanity  # noqa: E402


class TestValidateCanaryIsCallable(unittest.TestCase):
    """1) The `_log` binding exists, so calling the function does not NameError."""

    def test_marker_present_returns_true(self):
        self.assertTrue(canary.validate_canary("deploy CANARY ok"))

    def test_marker_absent_returns_false(self):
        self.assertFalse(canary.validate_canary("nothing to see here"))

    def test_non_string_input_is_fail_soft(self):
        # Fail-soft per CLAUDE.md: bad input returns a sensible default, never raises.
        for bad in (None, 42, [], {}, object()):
            with self.subTest(bad=type(bad).__name__):
                self.assertFalse(canary.validate_canary(bad))

    def test_log_is_bound_to_a_logger(self):
        self.assertTrue(hasattr(canary, "_log"), "canary._log is unbound again")
        for level in ("info", "warning"):
            self.assertTrue(callable(getattr(canary._log, level, None)))


class TestNoDuplicateDefinitions(unittest.TestCase):
    """2) The verbatim duplicate is gone.

    Import cannot see this — the later `def` overwrites the earlier one and the module
    looks fine — so assert on the AST of the source file.
    """

    def test_canary_defines_each_top_level_function_once(self):
        with open(os.path.join(RUNNER, "canary.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        names = [n.name for n in tree.body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        dupes = sorted({n for n in names if names.count(n) > 1})
        self.assertEqual([], dupes, f"duplicate top-level defs in canary.py: {dupes}")


class TestGateCoversDispatcherModules(unittest.TestCase):
    """3) The gate now watches the modules whose failures crash-loop whole job sets."""

    def test_dispatchers_are_in_critical_modules(self):
        for mod in ("canary.py", "periodic.py"):
            with self.subTest(mod=mod):
                self.assertIn(mod, static_sanity.CRITICAL_MODULES)

    def test_every_critical_module_exists_on_disk(self):
        # A name that no longer resolves to a file is silently dropped by check(),
        # which turns the gate off for that module without anyone noticing.
        missing = [m for m in static_sanity.CRITICAL_MODULES
                   if not os.path.exists(os.path.join(RUNNER, m))]
        self.assertEqual([], missing, f"CRITICAL_MODULES names with no file: {missing}")

    def test_canary_has_no_undefined_names(self):
        findings = static_sanity.check([os.path.join(RUNNER, "canary.py")])
        if findings is None:
            self.skipTest("pyflakes unavailable — gate is fail-soft by design")
        self.assertEqual([], findings, f"undefined names back in canary.py: {findings}")


if __name__ == "__main__":
    unittest.main()
