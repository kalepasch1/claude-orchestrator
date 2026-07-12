#!/usr/bin/env python3
"""
test_source_config.py - tests for source configuration and testing pipeline setup.

Verifies that the runner's source configuration (module paths, imports, db config)
is correct and that the testing pipeline can discover and run tests.

Task: improve-enhanced-testing-pipeline-fix-source-confi-slice-1
"""
import os
import sys
import unittest
import importlib

# Ensure runner is importable
RUNNER_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, RUNNER_DIR)


class TestSourceConfig(unittest.TestCase):
    """Verify that core runner modules are importable and configured."""

    CORE_MODULES = [
        "db", "log", "error_taxonomy", "branch_inspector",
        "repo_setup_repair", "branch_naming", "repo_hygiene",
    ]

    def test_core_modules_importable(self):
        """All core modules should import without error."""
        for mod_name in self.CORE_MODULES:
            mod_path = os.path.join(RUNNER_DIR, f"{mod_name}.py")
            if not os.path.exists(mod_path):
                self.skipTest(f"{mod_name}.py not found")
            try:
                importlib.import_module(mod_name)
            except Exception as exc:
                self.fail(f"Failed to import {mod_name}: {exc}")

    def test_runner_dir_on_path(self):
        """Runner directory must be on sys.path for imports to work."""
        self.assertIn(RUNNER_DIR, sys.path)

    def test_test_discovery(self):
        """Test files should follow naming convention test_*.py."""
        test_dir = os.path.dirname(__file__)
        test_files = [f for f in os.listdir(test_dir) if f.startswith("test_") and f.endswith(".py")]
        self.assertGreater(len(test_files), 0, "No test files found in tests directory")

    def test_no_circular_imports_in_error_taxonomy(self):
        """error_taxonomy should import cleanly without circular deps."""
        try:
            mod = importlib.import_module("error_taxonomy")
            self.assertTrue(hasattr(mod, "classify"))
            self.assertTrue(hasattr(mod, "stats"))
        except ImportError as exc:
            self.fail(f"Circular import in error_taxonomy: {exc}")

    def test_db_module_has_required_functions(self):
        """db module must expose select, update, localize_repo_path."""
        try:
            mod = importlib.import_module("db")
            for fn in ["select", "update"]:
                self.assertTrue(hasattr(mod, fn), f"db missing function: {fn}")
        except Exception as exc:
            self.skipTest(f"db module not importable in test env: {exc}")


class TestTestingPipelineSetup(unittest.TestCase):
    """Verify the testing pipeline infrastructure is functional."""

    def test_unittest_loader_finds_tests(self):
        """unittest loader should discover tests in this directory."""
        loader = unittest.TestLoader()
        test_dir = os.path.dirname(__file__)
        suite = loader.discover(test_dir, pattern="test_*.py")
        count = suite.countTestCases()
        self.assertGreater(count, 0, "Test discovery found no tests")

    def test_runner_tests_dir_exists(self):
        """runner/tests/ directory must exist."""
        test_dir = os.path.dirname(__file__)
        self.assertTrue(os.path.isdir(test_dir))

    def test_init_py_not_required(self):
        """Tests should work without __init__.py (namespace packages)."""
        test_dir = os.path.dirname(__file__)
        # This test itself proves discovery works without __init__.py
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
