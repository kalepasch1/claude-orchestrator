"""Tests for test_result_reporter.py — pytest/unittest output parsing and reporting."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from test_result_reporter import (
    TestCaseResult,
    TestReport,
    auto_parse,
    parse_pytest,
    parse_unittest,
    write_report,
)


class TestPytestParser(unittest.TestCase):
    """Verify pytest output parsing."""

    SAMPLE_PYTEST_ALL_PASS = """\
============================= test session starts ==============================
collected 5 items
PASSED tests/test_foo.py::test_one
PASSED tests/test_foo.py::test_two
PASSED tests/test_foo.py::test_three
PASSED tests/test_bar.py::test_alpha
PASSED tests/test_bar.py::test_beta
============================== 5 passed in 1.23s ===============================
"""

    SAMPLE_PYTEST_MIXED = """\
============================= test session starts ==============================
collected 8 items
PASSED tests/test_a.py::test_ok1
PASSED tests/test_a.py::test_ok2
FAILED tests/test_a.py::test_bad - AssertionError: 1 != 2
PASSED tests/test_b.py::test_ok3
SKIPPED tests/test_b.py::test_skip1
ERROR tests/test_b.py::test_err1
PASSED tests/test_b.py::test_ok4
PASSED tests/test_b.py::test_ok5
=================== 5 passed, 1 failed, 1 error, 1 skipped in 4.56s ===================
"""

    def test_all_pass(self):
        rpt = parse_pytest(self.SAMPLE_PYTEST_ALL_PASS)
        self.assertEqual(rpt.total, 5)
        self.assertEqual(rpt.passed, 5)
        self.assertEqual(rpt.failed, 0)
        self.assertEqual(rpt.errors, 0)
        self.assertAlmostEqual(rpt.duration_s, 1.23)
        self.assertTrue(rpt.success)
        self.assertEqual(rpt.source, "pytest")
        self.assertEqual(len(rpt.cases), 5)

    def test_mixed_results(self):
        rpt = parse_pytest(self.SAMPLE_PYTEST_MIXED)
        self.assertEqual(rpt.total, 8)
        self.assertEqual(rpt.passed, 5)
        self.assertEqual(rpt.failed, 1)
        self.assertEqual(rpt.errors, 1)
        self.assertEqual(rpt.skipped, 1)
        self.assertFalse(rpt.success)
        self.assertAlmostEqual(rpt.duration_s, 4.56)

    def test_case_message_captured(self):
        rpt = parse_pytest(self.SAMPLE_PYTEST_MIXED)
        failed_cases = [c for c in rpt.cases if c.status == "failed"]
        self.assertEqual(len(failed_cases), 1)
        self.assertIn("AssertionError", failed_cases[0].message)


class TestUnittestParser(unittest.TestCase):
    """Verify unittest output parsing."""

    SAMPLE_UNITTEST_PASS = """\
test_add (test_math.TestMath) ... ok
test_sub (test_math.TestMath) ... ok
test_mul (test_math.TestMath) ... ok

----------------------------------------------------------------------
Ran 3 tests in 0.002s

OK
"""

    SAMPLE_UNITTEST_FAIL = """\
test_add (test_math.TestMath) ... ok
test_div (test_math.TestMath) ... FAIL
test_edge (test_math.TestMath) ... ERROR

----------------------------------------------------------------------
Ran 3 tests in 0.005s

FAILED (failures=1, errors=1)
"""

    def test_all_pass(self):
        rpt = parse_unittest(self.SAMPLE_UNITTEST_PASS)
        self.assertEqual(rpt.total, 3)
        self.assertEqual(rpt.passed, 3)
        self.assertEqual(rpt.failed, 0)
        self.assertTrue(rpt.success)
        self.assertEqual(rpt.source, "unittest")
        self.assertAlmostEqual(rpt.duration_s, 0.002)

    def test_failures(self):
        rpt = parse_unittest(self.SAMPLE_UNITTEST_FAIL)
        self.assertEqual(rpt.total, 3)
        self.assertEqual(rpt.passed, 1)
        self.assertEqual(rpt.failed, 1)
        self.assertEqual(rpt.errors, 1)
        self.assertFalse(rpt.success)


class TestAutoDetect(unittest.TestCase):
    """auto_parse should pick the right parser."""

    def test_detects_pytest(self):
        output = "PASSED tests/x.py::t1\n=== 1 passed in 0.5s ==="
        rpt = auto_parse(output)
        self.assertEqual(rpt.source, "pytest")
        self.assertEqual(rpt.passed, 1)

    def test_detects_unittest(self):
        output = "Ran 2 tests in 0.01s\n\nOK"
        rpt = auto_parse(output)
        self.assertEqual(rpt.source, "unittest")
        self.assertEqual(rpt.total, 2)

    def test_empty_output(self):
        rpt = auto_parse("")
        self.assertEqual(rpt.source, "unknown")
        self.assertEqual(rpt.total, 0)


class TestReportSerialization(unittest.TestCase):
    """TestReport serialization and file writing."""

    def test_to_json_roundtrip(self):
        rpt = TestReport(total=3, passed=2, failed=1, duration_s=1.5, source="pytest")
        data = json.loads(rpt.to_json())
        self.assertEqual(data["total"], 3)
        self.assertEqual(data["passed"], 2)
        self.assertEqual(data["failed"], 1)
        self.assertFalse(data["success"])

    def test_write_report_creates_file(self):
        rpt = TestReport(total=1, passed=1, source="pytest")
        with tempfile.TemporaryDirectory() as td:
            path = write_report(rpt, directory=td)
            self.assertTrue(os.path.isfile(path))
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data["total"], 1)
            self.assertTrue(data["success"])

    def test_success_flag_auto(self):
        rpt = TestReport(total=5, passed=5)
        self.assertTrue(rpt.success)
        rpt2 = TestReport(total=5, passed=4, failed=1)
        self.assertFalse(rpt2.success)


if __name__ == "__main__":
    unittest.main()
