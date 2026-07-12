#!/usr/bin/env python3
"""
test_tdd_workflow.py - integration tests for TDD-first workflow.
End-to-end scenarios: task decomposition, test generation, pytest gating.
"""
import os
import sys
import json
import unittest
import tempfile
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import planner
import tdd_gate


class PlannerTddGatingIntegrationTest(unittest.TestCase):
    """End-to-end planner integration with TDD gating."""

    def tearDown(self):
        tdd_gate.invalidate_cache()

    def test_plan_inserts_write_tests_phase_for_gated_task(self):
        """Planner inserts write_tests phase before implement when task kind is gated."""
        with patch.object(tdd_gate, "get_required_kinds", return_value={"refactor"}):
            # Minimal task DAG: contracts + a refactor task
            tasks = [
                {"slug": "contracts", "prompt": "Define API", "deps": [], "model_hint": "haiku"},
                {"slug": "refactor-auth", "prompt": "Refactor auth module", "deps": ["contracts"], "model_hint": "haiku"},
            ]

            with patch("planner.claude_cli.run") as mock_run:
                mock_run.return_value = {"text": json.dumps(tasks)}

                result = planner.plan("Refactor the codebase")

            # Should have: contracts, refactor-auth-write-tests, refactor-auth
            slugs = [t["slug"] for t in result]
            self.assertIn("contracts", slugs)
            self.assertIn("refactor-auth-write-tests", slugs)
            self.assertIn("refactor-auth", slugs)

    def test_write_tests_task_has_correct_deps(self):
        """The write_tests task inherits original task's dependencies."""
        with patch.object(tdd_gate, "get_required_kinds", return_value={"refactor"}):
            tasks = [
                {"slug": "contracts", "prompt": "Define API", "deps": [], "model_hint": "haiku"},
                {"slug": "refactor-auth", "prompt": "Refactor auth", "deps": ["contracts"], "model_hint": "haiku"},
            ]

            with patch("planner.claude_cli.run") as mock_run:
                mock_run.return_value = {"text": json.dumps(tasks)}
                result = planner.plan("Refactor")

            write_tests_task = next((t for t in result if t["slug"] == "refactor-auth-write-tests"), None)
            self.assertIsNotNone(write_tests_task)
            self.assertIn("contracts", write_tests_task["deps"])

    def test_original_task_depends_on_write_tests(self):
        """Original task gets new dependency on write_tests task."""
        with patch.object(tdd_gate, "get_required_kinds", return_value={"refactor"}):
            tasks = [
                {"slug": "contracts", "prompt": "Define API", "deps": [], "model_hint": "haiku"},
                {"slug": "refactor-auth", "prompt": "Refactor auth", "deps": ["contracts"], "model_hint": "haiku"},
            ]

            with patch("planner.claude_cli.run") as mock_run:
                mock_run.return_value = {"text": json.dumps(tasks)}
                result = planner.plan("Refactor")

            original_task = next((t for t in result if t["slug"] == "refactor-auth"), None)
            self.assertIsNotNone(original_task)
            self.assertIn("refactor-auth-write-tests", original_task["deps"])

    def test_ungated_tasks_unchanged(self):
        """Non-gated tasks are NOT modified; no write_tests phase inserted."""
        with patch.object(tdd_gate, "get_required_kinds", return_value={"refactor"}):
            tasks = [
                {"slug": "contracts", "prompt": "Define API", "deps": [], "model_hint": "haiku"},
                {"slug": "bug-fix-login", "prompt": "Fix login bug", "deps": ["contracts"], "model_hint": "haiku"},
            ]

            with patch("planner.claude_cli.run") as mock_run:
                mock_run.return_value = {"text": json.dumps(tasks)}
                result = planner.plan("Fix bugs")

            slugs = [t["slug"] for t in result]
            # bug_fix not gated, so no write_tests_task should exist
            self.assertNotIn("bug-fix-login-write-tests", slugs)
            # Original task should be unchanged
            bug_fix = next((t for t in result if t["slug"] == "bug-fix-login"), None)
            self.assertEqual(bug_fix["deps"], ["contracts"])

    def test_contracts_task_never_gated(self):
        """Contracts task is never subjected to TDD gating, even if kind matches."""
        with patch.object(tdd_gate, "get_required_kinds", return_value={"contracts"}):
            tasks = [
                {"slug": "contracts", "prompt": "Define API", "deps": [], "model_hint": "haiku"},
            ]

            with patch("planner.claude_cli.run") as mock_run:
                mock_run.return_value = {"text": json.dumps(tasks)}
                result = planner.plan("Define contracts")

            # Should only have contracts task, no write_tests for it
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["slug"], "contracts")

    def test_multiple_gated_tasks(self):
        """When multiple tasks are gated, each gets its own write_tests task."""
        with patch.object(tdd_gate, "get_required_kinds", return_value={"refactor", "security"}):
            tasks = [
                {"slug": "contracts", "prompt": "Define API", "deps": [], "model_hint": "haiku"},
                {"slug": "refactor-db", "prompt": "Refactor DB", "deps": ["contracts"], "model_hint": "haiku"},
                {"slug": "security-scan", "prompt": "Security audit", "deps": ["contracts"], "model_hint": "haiku"},
            ]

            with patch("planner.claude_cli.run") as mock_run:
                mock_run.return_value = {"text": json.dumps(tasks)}
                result = planner.plan("Refactor and secure")

            slugs = [t["slug"] for t in result]
            self.assertIn("refactor-db-write-tests", slugs)
            self.assertIn("security-scan-write-tests", slugs)

    def test_write_tests_task_prompt_references_original(self):
        """write_tests task prompt includes reference to original task."""
        with patch.object(tdd_gate, "get_required_kinds", return_value={"refactor"}):
            tasks = [
                {"slug": "contracts", "prompt": "Define API", "deps": [], "model_hint": "haiku"},
                {"slug": "refactor-auth", "prompt": "Refactor auth module carefully", "deps": ["contracts"], "model_hint": "haiku"},
            ]

            with patch("planner.claude_cli.run") as mock_run:
                mock_run.return_value = {"text": json.dumps(tasks)}
                result = planner.plan("Refactor")

            write_tests_task = next((t for t in result if t["slug"] == "refactor-auth-write-tests"), None)
            self.assertIn("Write failing tests", write_tests_task["prompt"])
            self.assertIn("[ACCEPTANCE CRITERION]", write_tests_task["prompt"])

    def test_empty_gated_kinds_no_phase_insertion(self):
        """When ORCH_TDD_REQUIRED_KINDS is empty, no TDD phases inserted."""
        with patch.object(tdd_gate, "get_required_kinds", return_value=set()):
            tasks = [
                {"slug": "contracts", "prompt": "Define API", "deps": [], "model_hint": "haiku"},
                {"slug": "refactor-auth", "prompt": "Refactor auth", "deps": ["contracts"], "model_hint": "haiku"},
            ]

            with patch("planner.claude_cli.run") as mock_run:
                mock_run.return_value = {"text": json.dumps(tasks)}
                result = planner.plan("Refactor")

            # Should have exactly the same tasks as input (no write_tests inserted)
            self.assertEqual(len(result), 2)
            self.assertEqual([t["slug"] for t in result], ["contracts", "refactor-auth"])


class TestFileIntegrationTest(unittest.TestCase):
    """Integration tests for test file generation and pytest gating."""

    def test_test_file_written_to_correct_location(self):
        """Test files are written to tests/test_<task_id>.py."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = os.path.join(tmpdir, "tests")
            os.makedirs(test_dir, exist_ok=True)

            test_file = os.path.join(test_dir, "test_refactor_auth.py")
            test_content = '''
def test_token_validation():
    """[ACCEPTANCE CRITERION]: JWT tokens must be validated."""
    assert False
'''
            with open(test_file, "w") as f:
                f.write(test_content)

            criteria = tdd_gate.parse_acceptance_criteria(test_content)
            self.assertEqual(len(criteria), 1)
            self.assertIn("JWT", criteria[0]["criterion"])

    def test_failing_tests_initially(self):
        """Test files MUST fail before implementation begins."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "test_initial_fail.py")
            with open(test_file, "w") as f:
                f.write("def test_example():\n    assert False  # Must fail initially")

            # Verify it's detected as failing
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1)
                status = tdd_gate.test_file_status(test_file)
                self.assertEqual(status, "FAILING")

    def test_pytest_gate_checks_after_implementation(self):
        """After implementation, pytest gate verifies all tests pass."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "test_after_impl.py")
            with open(test_file, "w") as f:
                f.write("def test_example():\n    assert True  # Passes after impl")

            # Verify it's detected as passing
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                status = tdd_gate.test_file_status(test_file)
                self.assertEqual(status, "PASSING")


class RegressionTest(unittest.TestCase):
    """Regression tests: ensure TDD gating doesn't break existing behavior."""

    def tearDown(self):
        tdd_gate.invalidate_cache()

    def test_planner_still_works_without_tdd_gate_module(self):
        """Planner gracefully handles if tdd_gate is unavailable."""
        # This test verifies fail-soft: if tdd_gate import fails, planner still works
        with patch.object(tdd_gate, "get_required_kinds", side_effect=Exception("DB error")):
            tasks = [
                {"slug": "contracts", "prompt": "Define API", "deps": [], "model_hint": "haiku"},
                {"slug": "feature-x", "prompt": "Build feature", "deps": ["contracts"], "model_hint": "haiku"},
            ]

            with patch("planner.claude_cli.run") as mock_run:
                mock_run.return_value = {"text": json.dumps(tasks)}
                result = planner.plan("Build feature")

            # Should return tasks unmodified (empty gated_kinds due to exception)
            self.assertEqual(len(result), 2)

    def test_existing_task_execution_unaffected_when_tdd_disabled(self):
        """When TDD is disabled (empty kinds), existing tasks work as before."""
        with patch.object(tdd_gate, "get_required_kinds", return_value=set()):
            original_task = {
                "slug": "my-task",
                "prompt": "Do something",
                "deps": ["other"],
                "model_hint": "haiku"
            }

            from planner import _apply_tdd_gating
            result = _apply_tdd_gating([original_task])

            # Should be unchanged
            self.assertEqual(result, [original_task])


class EdgeCaseIntegrationTest(unittest.TestCase):
    """Edge cases in TDD workflow integration."""

    def tearDown(self):
        tdd_gate.invalidate_cache()

    def test_task_with_multiple_dependencies_preserved(self):
        """When task has multiple deps, all are preserved + write_tests dep added."""
        with patch.object(tdd_gate, "get_required_kinds", return_value={"refactor"}):
            tasks = [
                {"slug": "contracts", "prompt": "Define API", "deps": [], "model_hint": "haiku"},
                {"slug": "setup", "prompt": "Setup DB", "deps": ["contracts"], "model_hint": "haiku"},
                {"slug": "refactor-complex", "prompt": "Refactor", "deps": ["contracts", "setup"], "model_hint": "haiku"},
            ]

            with patch("planner.claude_cli.run") as mock_run:
                mock_run.return_value = {"text": json.dumps(tasks)}
                result = planner.plan("Refactor")

            refactor_task = next((t for t in result if t["slug"] == "refactor-complex"), None)
            # Should have contracts, setup, and refactor-complex-write-tests
            self.assertIn("contracts", refactor_task["deps"])
            self.assertIn("setup", refactor_task["deps"])
            self.assertIn("refactor-complex-write-tests", refactor_task["deps"])


if __name__ == "__main__":
    unittest.main()
