#!/usr/bin/env python3
"""Tests for canary.process_response — the validate -> exit-code seam.

Loaded by PATH under a unique module name. `import canary` is ambiguous in this repo:
runner/ is on sys.path for several sibling test modules and also contains a canary.py,
so a plain import would hand back whichever one sys.modules cached first and the test
would silently assert against the wrong file.
"""
import importlib.util
import os
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("root_canary", os.path.join(_ROOT, "canary.py"))
root_canary = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(root_canary)


class ProcessResponseTests(unittest.TestCase):
    def test_marker_present_returns_success_exit_code(self):
        self.assertEqual(root_canary.process_response("a canary marker"), 0)

    def test_marker_absent_returns_failure_exit_code(self):
        self.assertEqual(root_canary.process_response("nothing here"), 1)

    def test_exit_code_is_inverted_relative_to_the_boolean_verdict(self):
        """The whole reason the seam exists: 0 == pass == True."""
        for text in ("canary", "no marker", "CANARY build", ""):
            verdict = root_canary.validate_canary(text)
            self.assertEqual(root_canary.process_response(text), 0 if verdict else 1, text)

    def test_non_string_input_is_a_failed_hop_not_a_crash(self):
        for bad in (None, 42, [], {}, object()):
            self.assertEqual(root_canary.process_response(bad), 1)

    def test_logs_info_on_pass_and_error_on_fail(self):
        with self.assertLogs(root_canary.logger, level="INFO") as captured:
            root_canary.process_response("canary")
        self.assertTrue(any("validation passed" in line for line in captured.output))
        with self.assertLogs(root_canary.logger, level="ERROR") as captured:
            root_canary.process_response("nope")
        self.assertTrue(any("validation failed" in line for line in captured.output))


class MainRoutesThroughProcessResponseTests(unittest.TestCase):
    def test_main_returns_zero_when_the_marker_is_present(self):
        self.assertEqual(root_canary.main(["a", "canary", "build"]), 0)

    def test_main_returns_one_when_the_marker_is_absent(self):
        self.assertEqual(root_canary.main(["nothing", "to", "see"]), 1)

    def test_main_joins_argv_before_validating(self):
        """'can' + 'ary' must NOT become a marker; the join is space-separated."""
        self.assertEqual(root_canary.main(["can", "ary"]), 1)

    def test_no_arguments_is_a_failure_not_a_crash(self):
        self.assertEqual(root_canary.main([]), 1)


if __name__ == "__main__":
    unittest.main()
