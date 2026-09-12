#!/usr/bin/env python3
"""canary.process_response — validation folded into a process exit code.

Covers the acceptance for the canary-gemini-25 exit-code slice: process_response
returns 0 for text carrying the canary marker, 1 for text without it, logs a final
summary either way, and is the single source of the CLI's exit code so `main()`
cannot drift away from it.
"""
import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import canary  # noqa: E402


class TestProcessResponseExitCodes(unittest.TestCase):
    def test_marker_present_returns_zero(self):
        self.assertEqual(canary.process_response("The canary sings"), 0)

    def test_marker_absent_returns_one(self):
        self.assertEqual(canary.process_response("no bird"), 1)

    def test_match_is_case_insensitive(self):
        self.assertEqual(canary.process_response("CANARY"), 0)

    def test_substring_is_not_a_match(self):
        # word-boundary contract, mirrored from runner/canary_validation.py
        self.assertEqual(canary.process_response("canaries are birds"), 1)

    def test_non_string_input_is_a_failure_not_a_crash(self):
        for bad in (None, 42, [], {}, object()):
            with self.subTest(bad=bad):
                self.assertEqual(canary.process_response(bad), 1)

    def test_empty_string_returns_one(self):
        self.assertEqual(canary.process_response(""), 1)

    def test_return_type_is_int(self):
        self.assertIsInstance(canary.process_response("canary"), int)
        self.assertIsInstance(canary.process_response("nope"), int)


class TestProcessResponseLogging(unittest.TestCase):
    def test_success_logs_the_summary_at_info(self):
        with self.assertLogs(canary.logger, level=logging.INFO) as cm:
            canary.process_response("a canary here")
        self.assertIn("Validation result: success", "\n".join(cm.output))

    def test_failure_logs_the_summary_at_error(self):
        with self.assertLogs(canary.logger, level=logging.ERROR) as cm:
            canary.process_response("nothing here")
        self.assertIn("Validation result: failure", "\n".join(cm.output))


class TestCliDelegatesToProcessResponse(unittest.TestCase):
    def test_main_matches_process_response_for_present_marker(self):
        self.assertEqual(canary.main(["The", "canary", "sings"]), 0)

    def test_main_matches_process_response_for_absent_marker(self):
        self.assertEqual(canary.main(["no", "bird"]), 1)

    def test_main_with_no_args_is_a_failure(self):
        self.assertEqual(canary.main([]), 1)

    def test_request_only_flag_is_still_routed_away(self):
        # --request-only must not fall through to the validation exit code.
        self.assertNotEqual(canary.main(["--request-only", "/nonexistent/path.json"]), 1)


if __name__ == "__main__":
    unittest.main()
