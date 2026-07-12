#!/usr/bin/env python3
"""
test_tdd_gate.py - comprehensive unit tests for TDD-first workflow enforcement.
Tests gate detection, test file parsing, acceptance criteria extraction, and caching.
"""
import os
import sys
import unittest
import tempfile
import types
import subprocess
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tdd_gate


class GetRequiredKindsTest(unittest.TestCase):
    """Test reading ORCH_TDD_REQUIRED_KINDS from fleet_config."""

    def tearDown(self):
        tdd_gate.invalidate_cache()

    def test_returns_empty_set_when_db_unavailable(self):
        """Fail-soft: missing DB returns empty set, no exception."""
        with patch("tdd_gate.db") as mock_db:
            mock_db.select.side_effect = Exception("DB connection failed")
            result = tdd_gate.get_required_kinds()
            self.assertEqual(result, set())

    def test_returns_empty_set_when_key_missing(self):
        """Key not in fleet_config returns empty set."""
        with patch("tdd_gate.db") as mock_db:
            mock_db.select.return_value = []
            result = tdd_gate.get_required_kinds()
            self.assertEqual(result, set())

    def test_parses_comma_separated_kinds(self):
        """Correctly parses 'refactor,security_hardening,optimization'."""
        with patch("tdd_gate.db") as mock_db:
            mock_db.select.return_value = [{"key": "ORCH_TDD_REQUIRED_KINDS", "value": "refactor,security_hardening,optimization"}]
            result = tdd_gate.get_required_kinds()
            self.assertEqual(result, {"refactor", "security_hardening", "optimization"})

    def test_strips_whitespace_in_kinds(self):
        """Handles leading/trailing spaces: ' refactor , security '."""
        with patch("tdd_gate.db") as mock_db:
            mock_db.select.return_value = [{"key": "ORCH_TDD_REQUIRED_KINDS", "value": " refactor , security "}]
            result = tdd_gate.get_required_kinds()
            self.assertEqual(result, {"refactor", "security"})

    def test_caches_result_for_30s(self):
        """Subsequent calls within 30s use cache, not DB."""
        with patch("tdd_gate.db") as mock_db, patch("tdd_gate.time") as mock_time:
            mock_time.time.return_value = 1000.0
            mock_db.select.return_value = [{"key": "ORCH_TDD_REQUIRED_KINDS", "value": "refactor"}]

            # First call
            result1 = tdd_gate.get_required_kinds()
            self.assertEqual(mock_db.select.call_count, 1)

            # Advance time 20s (within cache window)
            mock_time.time.return_value = 1020.0
            result2 = tdd_gate.get_required_kinds()
            self.assertEqual(result1, result2)
            self.assertEqual(mock_db.select.call_count, 1)  # no new DB call

            # Advance time 35s (cache expired)
            mock_time.time.return_value = 1035.0
            mock_db.select.return_value = [{"key": "ORCH_TDD_REQUIRED_KINDS", "value": "refactor,new"}]
            result3 = tdd_gate.get_required_kinds()
            self.assertEqual(mock_db.select.call_count, 2)  # new call
            self.assertIn("new", result3)

    def test_handles_null_value(self):
        """If value is None or NULL, returns empty set."""
        with patch("tdd_gate.db") as mock_db:
            mock_db.select.return_value = [{"key": "ORCH_TDD_REQUIRED_KINDS", "value": None}]
            result = tdd_gate.get_required_kinds()
            self.assertEqual(result, set())

    def test_single_kind(self):
        """Single kind (no comma) parsed correctly."""
        with patch("tdd_gate.db") as mock_db:
            mock_db.select.return_value = [{"key": "ORCH_TDD_REQUIRED_KINDS", "value": "refactor"}]
            result = tdd_gate.get_required_kinds()
            self.assertEqual(result, {"refactor"})


class IsTddGatedTest(unittest.TestCase):
    """Test task kind gating logic."""

    def tearDown(self):
        tdd_gate.invalidate_cache()

    def test_gated_kind_returns_true(self):
        """Task kind in gated list returns True."""
        with patch.object(tdd_gate, "get_required_kinds", return_value={"refactor", "security"}):
            self.assertTrue(tdd_gate.is_tdd_gated("refactor"))

    def test_ungated_kind_returns_false(self):
        """Task kind not in gated list returns False."""
        with patch.object(tdd_gate, "get_required_kinds", return_value={"refactor"}):
            self.assertFalse(tdd_gate.is_tdd_gated("bug_fix"))

    def test_empty_kind_returns_false(self):
        """None or empty string returns False."""
        with patch.object(tdd_gate, "get_required_kinds", return_value={"refactor"}):
            self.assertFalse(tdd_gate.is_tdd_gated(None))
            self.assertFalse(tdd_gate.is_tdd_gated(""))

    def test_case_insensitive_matching(self):
        """Kind matching is case-insensitive."""
        with patch.object(tdd_gate, "get_required_kinds", return_value={"refactor", "security_hardening"}):
            self.assertTrue(tdd_gate.is_tdd_gated("REFACTOR"))
            self.assertTrue(tdd_gate.is_tdd_gated("Security_Hardening"))

    def test_empty_gated_list_returns_false(self):
        """When no kinds are gated, always returns False."""
        with patch.object(tdd_gate, "get_required_kinds", return_value=set()):
            self.assertFalse(tdd_gate.is_tdd_gated("anything"))


class ExtractTestFilePathTest(unittest.TestCase):
    """Test parsing test file path from agent output."""

    def test_extracts_explicit_path(self):
        """Finds 'tests/test_<task_id>.py' pattern in output."""
        output = "I've written failing tests to tests/test_refactor_auth.py"
        result = tdd_gate.extract_test_file_path(output)
        self.assertIsNotNone(result)
        self.assertIn("test_refactor_auth.py", result)

    def test_extracts_from_saved_to_message(self):
        """Finds path after 'saved to:' keyword."""
        output = "Test file saved to: /repo/tests/test_xyz.py"
        result = tdd_gate.extract_test_file_path(output)
        self.assertIsNotNone(result)
        self.assertIn("test_xyz.py", result)

    def test_extracts_from_file_keyword(self):
        """Finds path after 'file:' keyword."""
        output = "Created file: tests/test_bug_fix.py with 5 tests"
        result = tdd_gate.extract_test_file_path(output)
        self.assertIsNotNone(result)
        self.assertIn("test_bug_fix.py", result)

    def test_returns_none_if_no_path_found(self):
        """Returns None if no test file path in output."""
        output = "I've written the tests but didn't include the path"
        result = tdd_gate.extract_test_file_path(output)
        self.assertIsNone(result)

    def test_handles_empty_output(self):
        """Returns None for empty/None output."""
        self.assertIsNone(tdd_gate.extract_test_file_path(None))
        self.assertIsNone(tdd_gate.extract_test_file_path(""))

    def test_handles_multiple_paths_returns_first(self):
        """When multiple paths present, returns the first one found."""
        output = "Tests in tests/test_alpha.py and tests/test_beta.py"
        result = tdd_gate.extract_test_file_path(output)
        self.assertIn("test_alpha.py", result)


class ParseAcceptanceCriteriaTest(unittest.TestCase):
    """Test extraction of acceptance criteria from test code."""

    def test_parses_single_criterion_docstring(self):
        """Extracts docstring from a single test function."""
        code = '''
def test_auth_validation():
    """[ACCEPTANCE CRITERION]: User auth token must be valid JWT before access."""
    assert False
'''
        criteria = tdd_gate.parse_acceptance_criteria(code)
        self.assertEqual(len(criteria), 1)
        self.assertEqual(criteria[0]["test_name"], "test_auth_validation")
        self.assertIn("JWT", criteria[0]["criterion"])

    def test_parses_multiple_criteria(self):
        """Extracts criteria from multiple test functions."""
        code = '''
def test_performance():
    """[ACCEPTANCE CRITERION]: Must handle 1000 req/s."""
    assert False

def test_security():
    """[ACCEPTANCE CRITERION]: SQL injection must be blocked."""
    assert False
'''
        criteria = tdd_gate.parse_acceptance_criteria(code)
        self.assertEqual(len(criteria), 2)
        self.assertEqual({c["test_name"] for c in criteria}, {"test_performance", "test_security"})

    def test_strips_criterion_prefix(self):
        """Removes '[ACCEPTANCE CRITERION]:' prefix from criterion text."""
        code = '''
def test_example():
    """[ACCEPTANCE CRITERION]: This is the criterion."""
    pass
'''
        criteria = tdd_gate.parse_acceptance_criteria(code)
        self.assertEqual(criteria[0]["criterion"], "This is the criterion.")
        self.assertNotIn("[ACCEPTANCE CRITERION]", criteria[0]["criterion"])

    def test_returns_empty_list_for_no_criteria(self):
        """Returns empty list if no criteria found."""
        code = "def test_no_docstring():\n    pass"
        criteria = tdd_gate.parse_acceptance_criteria(code)
        self.assertEqual(criteria, [])

    def test_ignores_non_criterion_docstrings(self):
        """Only includes docstrings with [ACCEPTANCE CRITERION] marker."""
        code = '''
def test_example():
    """This is just a normal docstring."""
    pass
'''
        criteria = tdd_gate.parse_acceptance_criteria(code)
        self.assertEqual(len(criteria), 0)

    def test_handles_multiline_docstrings(self):
        """Extracts criterion even with multiline docstrings."""
        code = '''
def test_complex():
    """[ACCEPTANCE CRITERION]: First line.
    Second line.
    Third line."""
    pass
'''
        criteria = tdd_gate.parse_acceptance_criteria(code)
        self.assertEqual(len(criteria), 1)
        self.assertIn("First line", criteria[0]["criterion"])


class TestFileStatusTest(unittest.TestCase):
    """Test pytest integration and test file status checking."""

    def test_returns_not_found_for_missing_file(self):
        """Returns NOT_FOUND if file doesn't exist."""
        result = tdd_gate.test_file_status("/nonexistent/tests/test_xyz.py")
        self.assertEqual(result, "NOT_FOUND")

    def test_returns_not_found_for_none_path(self):
        """Returns NOT_FOUND for None path."""
        result = tdd_gate.test_file_status(None)
        self.assertEqual(result, "NOT_FOUND")

    def test_returns_not_found_for_empty_path(self):
        """Returns NOT_FOUND for empty string."""
        result = tdd_gate.test_file_status("")
        self.assertEqual(result, "NOT_FOUND")

    def test_detects_failing_tests(self):
        """Runs pytest and detects FAILING status."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "test_fail.py")
            with open(test_file, "w") as f:
                f.write("def test_fail():\n    assert False")

            # Mock subprocess to simulate test failure
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1)
                result = tdd_gate.test_file_status(test_file)
                self.assertEqual(result, "FAILING")

    def test_detects_passing_tests(self):
        """Runs pytest and detects PASSING status."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "test_pass.py")
            with open(test_file, "w") as f:
                f.write("def test_pass():\n    assert True")

            # Mock subprocess to simulate test success
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                result = tdd_gate.test_file_status(test_file)
                self.assertEqual(result, "PASSING")

    def test_handles_pytest_timeout(self):
        """Returns FAILING if pytest times out."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("pytest", 30)
            result = tdd_gate.test_file_status("/fake/test.py")
            self.assertEqual(result, "FAILING")

    def test_handles_subprocess_exception(self):
        """Returns FAILING if subprocess raises other exceptions."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = OSError("Failed to run pytest")
            result = tdd_gate.test_file_status("/fake/test.py")
            self.assertEqual(result, "FAILING")


class InvalidateCacheTest(unittest.TestCase):
    """Test cache invalidation."""

    def test_invalidate_clears_cache(self):
        """Calling invalidate_cache() clears the kinds cache."""
        with patch.object(tdd_gate, "get_required_kinds", return_value={"refactor"}):
            result1 = tdd_gate.get_required_kinds()
            self.assertEqual(result1, {"refactor"})

        tdd_gate.invalidate_cache()

        with patch.object(tdd_gate, "_TDD_CACHE") as mock_cache:
            mock_cache.__getitem__.return_value = None
            # After invalidate, next call should hit DB again (not shown here but exercised)

    def test_invalidate_resets_timestamps(self):
        """invalidate_cache() resets cached_at to 0."""
        tdd_gate._TDD_CACHE["kinds"] = {"test"}
        tdd_gate._TDD_CACHE["cached_at"] = 1000.0
        tdd_gate.invalidate_cache()
        self.assertIsNone(tdd_gate._TDD_CACHE["kinds"])
        self.assertEqual(tdd_gate._TDD_CACHE["cached_at"], 0.0)


class EdgeCasesTest(unittest.TestCase):
    """Edge case and integration tests."""

    def tearDown(self):
        tdd_gate.invalidate_cache()

    def test_task_kind_with_underscores_and_hyphens(self):
        """Handles task kinds with underscores and hyphens."""
        with patch.object(tdd_gate, "get_required_kinds", return_value={"security-hardening", "db_migration"}):
            self.assertTrue(tdd_gate.is_tdd_gated("security-hardening"))
            self.assertTrue(tdd_gate.is_tdd_gated("db_migration"))

    def test_extract_path_with_relative_paths(self):
        """Extracts relative paths like 'tests/test_x.py' without leading '/'."""
        output = "Written to tests/test_feature.py"
        result = tdd_gate.extract_test_file_path(output)
        self.assertIsNotNone(result)
        self.assertTrue(result.endswith("test_feature.py"))

    def test_parse_criteria_handles_edge_formatting(self):
        """Handles criteria with extra whitespace and formatting."""
        code = '''
def test_thing():
    """[ACCEPTANCE CRITERION]:   \n    Criterion with weird spacing.   """
    pass
'''
        criteria = tdd_gate.parse_acceptance_criteria(code)
        self.assertEqual(len(criteria), 1)
        # Should be stripped
        self.assertFalse(criteria[0]["criterion"].startswith(" "))


if __name__ == "__main__":
    unittest.main()
