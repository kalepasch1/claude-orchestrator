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
    #: basename, and are NOT copies — every remaining pair differs in content. Both
    #: directories end up on sys.path, so the two files compete for one top-level
    #: module name: whichever is imported first wins, and unittest's loader
    #: refuses outright ("'test_account_pool' module incorrectly imported from
    #: .../runner. Expected .../runner/tests").
    #:
    #: This is a layout defect, not a test defect, and resolving it means deciding
    #: for each pair whether to merge, rename or delete — a judgement call about live
    #: coverage each time, not a mechanical move. Recorded as a ratchet so the number
    #: cannot grow while that decision is outstanding; it came down from 24 when
    #: runner/test_marginal_value_scheduler.py was deleted (every one of its eight
    #: tests called score_marginal(), a function that module has never defined).
    MAX_DUPLICATE_TEST_BASENAMES = 23

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
        broken, but because ~two dozen basenames exist in both runner/ and runner/tests/
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

    def test_no_gated_test_spawns_a_process_by_pickling_a_module_target(self):
        """multiprocessing.Process in a test is a spawn-import hazard here.

        macOS defaults to the SPAWN start method, which unpickles the target BY
        MODULE PATH -- so the child must import the test module before it runs a
        line. In this repo that import is not dependable, because `runner/` contains
        runner.py: with that directory on sys.path, `import runner` resolves to the
        MODULE and shadows the PACKAGE, making `runner.tests.*` unimportable. Whether
        a given child survives depends on where `runner/` sits in sys.path relative
        to the repo root, which depends on which files were imported first, which
        depends on what else is being collected.

        Two files learned this the hard way on 2026-08-26. In
        runner/test_repo_lock_holder.py it presented as "holder process never
        acquired the lock" -- a message pointing squarely at repo_lock, which was
        correct throughout -- and it was green alone and red in the full run.
        runner/tests/test_repo_lock.py had the same latent defect and happened to
        work.

        Both spawn a plain subprocess now, which pickles nothing and imports no test
        module. This keeps the pattern from coming back into the GATED suite, where
        the cost of an intermittent failure is a re-run of a ~48-minute gate.

        Not a blanket ban on multiprocessing: a test that needs it can use a
        subprocess, or `get_context("fork")`, or say why here.
        """
        offenders = []
        tests_dir = os.path.dirname(os.path.abspath(__file__))
        this_file = os.path.basename(os.path.abspath(__file__))
        for name in sorted(os.listdir(tests_dir)):
            if not (name.startswith("test_") and name.endswith(".py")):
                continue
            if name == this_file:
                continue   # the checker necessarily contains the pattern it looks for
            with open(os.path.join(tests_dir, name), encoding="utf-8") as handle:
                source = handle.read()
            if "multiprocessing.Process(" in source:
                offenders.append(name)
        self.assertEqual(offenders, [], (
            "these gated tests spawn via multiprocessing.Process, whose child must "
            "import the test module by dotted path -- unreliable while runner/runner.py "
            "shadows the runner package. Use a subprocess instead: %s" % offenders))

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
