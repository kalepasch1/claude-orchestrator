#!/usr/bin/env python3
"""
test_testing_pipeline_setup.py - verify the testing pipeline repo setup is sound.

Covers:
  - CI workflow file exists and references pytest
  - All test files are importable (no broken imports at module level)
  - pipeline_contract module loads without error
  - Key test infrastructure files exist
"""
import os
import sys
import unittest
import importlib

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNNER_DIR = os.path.join(REPO_ROOT, "runner")
TESTS_DIR = os.path.join(RUNNER_DIR, "tests")

sys.path.insert(0, RUNNER_DIR)


class TestRepoSetup(unittest.TestCase):
    """Verify essential repo structure for tests to run."""

    def test_runner_directory_exists(self):
        self.assertTrue(os.path.isdir(RUNNER_DIR))

    def test_tests_directory_exists(self):
        self.assertTrue(os.path.isdir(TESTS_DIR))

    def test_ci_workflow_exists(self):
        ci_path = os.path.join(REPO_ROOT, ".github", "workflows", "ci.yml")
        self.assertTrue(os.path.isfile(ci_path), f"CI workflow not found at {ci_path}")

    def test_ci_workflow_references_pytest(self):
        ci_path = os.path.join(REPO_ROOT, ".github", "workflows", "ci.yml")
        if not os.path.isfile(ci_path):
            self.skipTest("ci.yml not found")
        with open(ci_path) as f:
            content = f.read()
        self.assertIn("pytest", content)


class TestPipelineContractImport(unittest.TestCase):
    """Verify pipeline_contract is importable and has key interfaces."""

    def test_pipeline_contract_imports(self):
        try:
            import pipeline_contract
        except Exception as e:
            self.fail(f"pipeline_contract failed to import: {e}")

    def test_pipeline_contract_has_wrap_prompt(self):
        import pipeline_contract
        self.assertTrue(hasattr(pipeline_contract, "wrap_prompt"))

    def test_pipeline_contract_has_marker(self):
        import pipeline_contract
        self.assertTrue(hasattr(pipeline_contract, "MARKER"))

    def test_pipeline_contract_has_original_request(self):
        import pipeline_contract
        self.assertTrue(hasattr(pipeline_contract, "original_request"))


class TestKeyModulesImportable(unittest.TestCase):
    """Spot-check that core runner modules import without crashing."""

    def _try_import(self, name):
        try:
            importlib.import_module(name)
        except ImportError:
            self.skipTest(f"{name} has unresolved dependencies in this env")
        except Exception as e:
            self.fail(f"{name} raised on import: {e}")

    def test_db_imports(self):
        self._try_import("db")

    def test_auto_remediate_imports(self):
        self._try_import("auto_remediate")

    def test_agentic_repair_imports(self):
        self._try_import("agentic_repair")

    def test_enqueue_task_imports(self):
        self._try_import("enqueue_task")


class TestTestFilesDiscoverable(unittest.TestCase):
    """Every test_*.py in runner/tests/ should be syntactically valid."""

    def test_all_test_files_compile(self):
        errors = []
        for fname in sorted(os.listdir(TESTS_DIR)):
            if not fname.startswith("test_") or not fname.endswith(".py"):
                continue
            fpath = os.path.join(TESTS_DIR, fname)
            try:
                with open(fpath) as f:
                    compile(f.read(), fpath, "exec")
            except SyntaxError as e:
                errors.append(f"{fname}: {e}")
        self.assertEqual(errors, [], f"Syntax errors in test files: {errors}")


if __name__ == "__main__":
    unittest.main()
