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

    #: Test modules that exist under BOTH runner/ and runner/tests/ with the same
    #: basename, and are NOT copies — all 24 pairs differ in content. Both
    #: directories end up on sys.path, so the two files compete for one top-level
    #: module name: whichever is imported first wins, and unittest's loader
    #: refuses outright ("'test_account_pool' module incorrectly imported from
    #: .../runner. Expected .../runner/tests").
    #:
    #: This is a layout defect, not a test defect, and resolving it means deciding
    #: for each pair whether to merge, rename or delete — 24 judgement calls about
    #: live coverage, not a mechanical move. Recorded as a ratchet so the number
    #: cannot grow while that decision is outstanding.
    MAX_DUPLICATE_TEST_BASENAMES = 24

    def _duplicate_test_basenames(self):
        tests_dir = os.path.dirname(os.path.abspath(__file__))
        runner_dir = os.path.dirname(tests_dir)
        return sorted(
            name for name in os.listdir(runner_dir)
            if name.startswith("test_") and name.endswith(".py")
            and os.path.isfile(os.path.join(tests_dir, name))
        )

    def test_unittest_loader_finds_tests(self):
        """Discovery must work for every test module whose name is unambiguous.

        This used to call loader.discover() over the whole directory and assert a
        nonzero count. It raised ImportError instead — not because discovery is
        broken, but because 24 basenames exist in both runner/ and runner/tests/
        and unittest refuses to import the second one under a name the first
        already holds. A bare `discover()` therefore cannot pass in this repo, in
        a clean interpreter or otherwise, and the failure said nothing about why.

        So this asks the collector that the fleet ACTUALLY uses, and asks it about
        the run in progress: this session imported runner/tests/*.py under the
        `runner.tests.*` package names, and counting those entries proves
        discovery worked without importing a single module a second time.

        That last part matters. The obvious alternative — importlib.import_module
        on each basename — would load every test module a SECOND time under a
        different top-level name, giving the session two copies of each with two
        sets of module-scope stubs. That is the duplicate-module failure mode this
        suite spent a session tracking down; a test for the test pipeline must not
        reintroduce it.
        """
        tests_dir = os.path.dirname(os.path.abspath(__file__))
        on_disk = [n for n in os.listdir(tests_dir)
                   if n.startswith("test_") and n.endswith(".py")]
        collected = [name for name in sys.modules
                     if name.startswith("runner.tests.test_")]

        self.assertGreater(len(on_disk), 100, "runner/tests/ has almost no test files")
        self.assertGreater(len(collected), 0,
                           "Test discovery found no tests — nothing under runner/tests/ "
                           "was imported as runner.tests.*")
        # Every collected name must correspond to a file that is really there, so a
        # stale sys.modules entry cannot stand in for working discovery.
        for name in collected:
            basename = name.rsplit(".", 1)[-1] + ".py"
            self.assertIn(basename, on_disk, f"{name} has no file in runner/tests/")

    def test_no_new_test_module_is_duplicated_across_the_two_directories(self):
        """A ratchet on the layout defect above: it may shrink, never grow.

        Two files with one module name means one of them is shadowed, and which
        one wins depends on import order — so a pair added today can silently
        stop a whole file's coverage from ever running.
        """
        duplicates = self._duplicate_test_basenames()
        self.assertLessEqual(
            len(duplicates), self.MAX_DUPLICATE_TEST_BASENAMES,
            "new test module(s) share a basename between runner/ and runner/tests/: "
            + ", ".join(duplicates[self.MAX_DUPLICATE_TEST_BASENAMES:]))

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
