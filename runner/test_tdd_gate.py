#!/usr/bin/env python3
"""
test_tdd_gate.py - comprehensive test suite for TDD-gated task execution.

Tests cover:
- Config reading (ORCH_TDD_ENABLED, ORCH_TDD_TASK_KINDS)
- Task kind matching and gating logic
- Test file path extraction from agent output
- Acceptance criteria parsing and validation
- Test running and result aggregation
"""
import os
import sys
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tdd_gate


class TestTDDGating(unittest.TestCase):
    """Test TDD-first enforcement configuration and gating logic."""

    def setUp(self):
        """Clear cache before each test."""
        tdd_gate.invalidate_cache()

    def tearDown(self):
        """Clear cache after each test."""
        tdd_gate.invalidate_cache()

    def test_is_tdd_enabled_default_false(self):
        """By default, TDD is disabled."""
        with patch.dict(os.environ, {}, clear=False):
            with patch("tdd_gate.db") as mock_db:
                mock_db.select.return_value = []
                self.assertFalse(tdd_gate.is_tdd_enabled())

    def test_is_tdd_enabled_from_env(self):
        """ORCH_TDD_ENABLED env var enables TDD."""
        with patch.dict(os.environ, {"ORCH_TDD_ENABLED": "true"}):
            tdd_gate.invalidate_cache()
            self.assertTrue(tdd_gate.is_tdd_enabled())

    def test_is_tdd_enabled_from_fleet_config(self):
        """ORCH_TDD_ENABLED from fleet_config is respected."""
        with patch("tdd_gate.db") as mock_db:
            mock_db.select.return_value = [{"key": "ORCH_TDD_ENABLED", "value": "true"}]
            tdd_gate.invalidate_cache()
            self.assertTrue(tdd_gate.is_tdd_enabled())

    def test_get_task_kinds_default(self):
        """Default task kinds are feature, new-module."""
        with patch.dict(os.environ, {"ORCH_TDD_ENABLED": "true"}, clear=False):
            with patch("tdd_gate.db") as mock_db:
                mock_db.select.return_value = []
                tdd_gate.invalidate_cache()
                kinds = tdd_gate.get_task_kinds()
                self.assertIn("feature", kinds)
                self.assertIn("new-module", kinds)

    def test_get_task_kinds_from_env(self):
        """ORCH_TDD_TASK_KINDS env var is parsed."""
        with patch.dict(os.environ, {"ORCH_TDD_TASK_KINDS": "refactor,security"}):
            tdd_gate.invalidate_cache()
            kinds = tdd_gate.get_task_kinds()
            self.assertIn("refactor", kinds)
            self.assertIn("security", kinds)

    def test_get_task_kinds_from_fleet_config(self):
        """ORCH_TDD_TASK_KINDS from fleet_config is parsed."""
        with patch("tdd_gate.db") as mock_db:
            mock_db.select.return_value = [
                {"key": "ORCH_TDD_TASK_KINDS", "value": "feature,optimization"}
            ]
            tdd_gate.invalidate_cache()
            kinds = tdd_gate.get_task_kinds()
            self.assertIn("feature", kinds)
            self.assertIn("optimization", kinds)

    def test_is_tdd_gated_requires_enabled(self):
        """Task kind gating requires TDD to be enabled."""
        with patch.dict(os.environ, {"ORCH_TDD_ENABLED": "false"}, clear=False):
            tdd_gate.invalidate_cache()
            self.assertFalse(tdd_gate.is_tdd_gated("feature"))

    def test_is_tdd_gated_matching_kind(self):
        """Matching task kinds are gated."""
        with patch.dict(os.environ, {
            "ORCH_TDD_ENABLED": "true",
            "ORCH_TDD_TASK_KINDS": "feature,new-module"
        }):
            tdd_gate.invalidate_cache()
            self.assertTrue(tdd_gate.is_tdd_gated("feature"))
            self.assertTrue(tdd_gate.is_tdd_gated("new-module"))

    def test_is_tdd_gated_non_matching_kind(self):
        """Non-matching task kinds are not gated."""
        with patch.dict(os.environ, {
            "ORCH_TDD_ENABLED": "true",
            "ORCH_TDD_TASK_KINDS": "feature,new-module"
        }):
            tdd_gate.invalidate_cache()
            self.assertFalse(tdd_gate.is_tdd_gated("bugfix"))
            self.assertFalse(tdd_gate.is_tdd_gated("refactor"))

    def test_is_tdd_gated_case_insensitive(self):
        """Task kind matching is case-insensitive."""
        with patch.dict(os.environ, {
            "ORCH_TDD_ENABLED": "true",
            "ORCH_TDD_TASK_KINDS": "Feature,NEW-MODULE"
        }):
            tdd_gate.invalidate_cache()
            self.assertTrue(tdd_gate.is_tdd_gated("feature"))
            self.assertTrue(tdd_gate.is_tdd_gated("new-module"))


class TestTestFilePathExtraction(unittest.TestCase):
    """Test extraction of test file paths from agent output."""

    def test_extract_test_file_path_direct_pattern(self):
        """Direct test path pattern is extracted."""
        output = "Write tests to tests/test_feature_foo.py"
        path = tdd_gate.extract_test_file_path(output)
        self.assertEqual(path, "tests/test_feature_foo.py")

    def test_extract_test_file_path_saved_to(self):
        """'saved to' pattern is extracted."""
        output = "Successfully saved to tests/test_bar.py"
        path = tdd_gate.extract_test_file_path(output)
        self.assertIn("tests/test_bar.py", path)

    def test_extract_test_file_path_write_to(self):
        """'write to' pattern is extracted."""
        output = "Write test file to: tests/test_baz.py"
        path = tdd_gate.extract_test_file_path(output)
        self.assertIn("tests/test_baz.py", path)

    def test_extract_test_file_path_not_found(self):
        """None returned when no pattern matches."""
        output = "No test file mentioned here"
        path = tdd_gate.extract_test_file_path(output)
        self.assertIsNone(path)

    def test_extract_test_file_path_empty_output(self):
        """None returned for empty output."""
        path = tdd_gate.extract_test_file_path("")
        self.assertIsNone(path)

    def test_extract_test_file_path_none_input(self):
        """None returned for None input."""
        path = tdd_gate.extract_test_file_path(None)
        self.assertIsNone(path)


class TestAcceptanceCriteriaParsing(unittest.TestCase):
    """Test parsing of acceptance criteria from test code."""

    def test_parse_acceptance_criteria_basic(self):
        """Basic test docstring parsing."""
        code = '''
def test_main():
    """[ACCEPTANCE CRITERION]: Must handle primary case."""
    assert True
'''
        criteria = tdd_gate.parse_acceptance_criteria(code)
        self.assertEqual(len(criteria), 1)
        self.assertEqual(criteria[0]["test_name"], "test_main")
        self.assertIn("primary case", criteria[0]["criterion"])

    def test_parse_acceptance_criteria_multiple(self):
        """Multiple tests are parsed."""
        code = '''
def test_main():
    """[ACCEPTANCE CRITERION]: Main functionality."""
    assert True

def test_edge_cases():
    """[ACCEPTANCE CRITERION]: Edge cases handled."""
    assert True
'''
        criteria = tdd_gate.parse_acceptance_criteria(code)
        self.assertEqual(len(criteria), 2)
        test_names = {c["test_name"] for c in criteria}
        self.assertEqual(test_names, {"test_main", "test_edge_cases"})

    def test_parse_acceptance_criteria_no_marker(self):
        """Docstring without marker is still captured."""
        code = '''
def test_simple():
    """Just a simple test."""
    assert True
'''
        criteria = tdd_gate.parse_acceptance_criteria(code)
        self.assertEqual(len(criteria), 1)
        self.assertEqual(criteria[0]["criterion"], "Just a simple test.")

    def test_parse_acceptance_criteria_no_tests(self):
        """No tests returns empty list."""
        code = "# Just comments, no tests"
        criteria = tdd_gate.parse_acceptance_criteria(code)
        self.assertEqual(criteria, [])

    def test_parse_acceptance_criteria_empty_code(self):
        """Empty code returns empty list."""
        criteria = tdd_gate.parse_acceptance_criteria("")
        self.assertEqual(criteria, [])


class TestAcceptanceCriteriaValidation(unittest.TestCase):
    """Test validation of acceptance criteria format."""

    def test_validate_acceptance_criteria_valid(self):
        """Valid criteria passes validation."""
        task_spec = {
            "acceptance_criteria": {
                "metrics": {"latency_ms": "<100"},
                "edge_cases": ["case1", "case2"],
                "must_pass_tests": ["test_main"]
            }
        }
        valid, error = tdd_gate.validate_acceptance_criteria(task_spec)
        self.assertTrue(valid)
        self.assertIsNone(error)

    def test_validate_acceptance_criteria_not_dict(self):
        """Non-dict spec fails validation."""
        valid, error = tdd_gate.validate_acceptance_criteria("not a dict")
        self.assertFalse(valid)
        self.assertIsNotNone(error)

    def test_validate_acceptance_criteria_missing_criteria(self):
        """Missing acceptance_criteria is treated as empty dict."""
        task_spec = {"other_field": "value"}
        valid, error = tdd_gate.validate_acceptance_criteria(task_spec)
        self.assertFalse(valid)

    def test_validate_acceptance_criteria_invalid_metrics(self):
        """Invalid metrics type fails."""
        task_spec = {
            "acceptance_criteria": {
                "metrics": "not a dict",
                "edge_cases": [],
                "must_pass_tests": ["test_main"]
            }
        }
        valid, error = tdd_gate.validate_acceptance_criteria(task_spec)
        self.assertFalse(valid)

    def test_validate_acceptance_criteria_invalid_edge_cases(self):
        """Invalid edge_cases type fails."""
        task_spec = {
            "acceptance_criteria": {
                "metrics": {},
                "edge_cases": "not a list",
                "must_pass_tests": ["test_main"]
            }
        }
        valid, error = tdd_gate.validate_acceptance_criteria(task_spec)
        self.assertFalse(valid)

    def test_validate_acceptance_criteria_empty_must_pass(self):
        """Empty must_pass_tests fails."""
        task_spec = {
            "acceptance_criteria": {
                "metrics": {},
                "edge_cases": [],
                "must_pass_tests": []
            }
        }
        valid, error = tdd_gate.validate_acceptance_criteria(task_spec)
        self.assertFalse(valid)

    def test_validate_acceptance_criteria_invalid_must_pass(self):
        """Invalid must_pass_tests type fails."""
        task_spec = {
            "acceptance_criteria": {
                "metrics": {},
                "edge_cases": [],
                "must_pass_tests": "not a list"
            }
        }
        valid, error = tdd_gate.validate_acceptance_criteria(task_spec)
        self.assertFalse(valid)


class TestTestFileStatus(unittest.TestCase):
    """Test checking test file status."""

    def test_test_file_status_not_found(self):
        """Missing file returns NOT_FOUND."""
        status = tdd_gate.test_file_status("/nonexistent/path/test.py")
        self.assertEqual(status, "NOT_FOUND")

    def test_test_file_status_none_path(self):
        """None path returns NOT_FOUND."""
        status = tdd_gate.test_file_status(None)
        self.assertEqual(status, "NOT_FOUND")

    def test_test_file_status_empty_path(self):
        """Empty path returns NOT_FOUND."""
        status = tdd_gate.test_file_status("")
        self.assertEqual(status, "NOT_FOUND")

    def test_test_file_status_with_temp_file(self):
        """Real test file status is checked."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write('def test_pass():\n    assert True\n')
            f.flush()
            temp_path = f.name
        try:
            status = tdd_gate.test_file_status(temp_path)
            self.assertIn(status, ["PASSING", "FAILING", "NOT_FOUND"])
        finally:
            os.unlink(temp_path)


class TestRunMustPassTests(unittest.TestCase):
    """Test running must-pass tests via pytest."""

    def test_run_must_pass_tests_not_found(self):
        """Non-existent file returns not_found."""
        result = tdd_gate.run_must_pass_tests("/nonexistent.py", ["test_foo"])
        self.assertEqual(result["exit_code"], 1)
        self.assertIn("test_foo", result["not_found"])

    def test_run_must_pass_tests_empty_list(self):
        """Empty test list returns empty result."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write('def test_pass():\n    assert True\n')
            temp_path = f.name
        try:
            result = tdd_gate.run_must_pass_tests(temp_path, [])
            self.assertEqual(result["passed"], [])
            self.assertEqual(result["failed"], [])
            self.assertEqual(result["not_found"], [])
        finally:
            os.unlink(temp_path)

    def test_run_must_pass_tests_result_structure(self):
        """Result dict has required keys."""
        result = tdd_gate.run_must_pass_tests(None, ["test_foo"])
        self.assertIn("passed", result)
        self.assertIn("failed", result)
        self.assertIn("not_found", result)
        self.assertIn("exit_code", result)
        self.assertIn("stdout", result)
        self.assertIn("stderr", result)

    def test_run_must_pass_tests_with_temp_file(self):
        """Can run tests from a temp file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write('def test_pass():\n    assert True\n')
            f.write('def test_fail():\n    assert False\n')
            temp_path = f.name
        try:
            result = tdd_gate.run_must_pass_tests(
                temp_path,
                ["test_pass", "test_fail"]
            )
            self.assertIsInstance(result["exit_code"], int)
            self.assertIsInstance(result["passed"], list)
            self.assertIsInstance(result["failed"], list)
        finally:
            os.unlink(temp_path)


class TestCacheInvalidation(unittest.TestCase):
    """Test cache invalidation."""

    def test_invalidate_cache(self):
        """Cache can be invalidated."""
        with patch.dict(os.environ, {"ORCH_TDD_ENABLED": "true"}):
            tdd_gate.invalidate_cache()
            tdd_gate.is_tdd_enabled()
            self.assertIsNotNone(tdd_gate._TDD_CACHE["enabled"])
            tdd_gate.invalidate_cache()
            self.assertIsNone(tdd_gate._TDD_CACHE["enabled"])


if __name__ == "__main__":
    unittest.main()
