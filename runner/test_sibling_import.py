"""Tests for runner/sibling_import.py — the fail-closed-guard import repair.

The regression these cover: a bare ``import regression_guard`` raises
ModuleNotFoundError whenever runner/ is absent from sys.path, and every merge
gate treats that as a regression verdict, blocking additive branches.
"""

import importlib
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sibling_import  # noqa: E402


RUNNER_DIR = os.path.dirname(os.path.abspath(__file__))


class SiblingDirTests(unittest.TestCase):
    def test_points_at_runner_directory(self):
        self.assertEqual(sibling_import.sibling_dir(), RUNNER_DIR)


class LoadSiblingTests(unittest.TestCase):
    def setUp(self):
        self._path = list(sys.path)
        self._modules = dict(sys.modules)

    def tearDown(self):
        sys.path[:] = self._path
        for name in list(sys.modules):
            if name not in self._modules:
                sys.modules.pop(name, None)

    def _strip_runner_from_path(self):
        sys.path[:] = [p for p in sys.path
                       if os.path.abspath(p or ".") != RUNNER_DIR]

    def test_loads_regression_guard_with_runner_on_path(self):
        module = sibling_import.load_sibling("regression_guard")
        self.assertIsNotNone(module)
        self.assertTrue(hasattr(module, "gate"))

    def test_loads_regression_guard_without_runner_on_path(self):
        """The exact failure mode: sys.path no longer contains runner/."""
        sys.modules.pop("regression_guard", None)
        self._strip_runner_from_path()
        with self.assertRaises(ImportError):
            importlib.import_module("regression_guard")
        module = sibling_import.load_sibling("regression_guard")
        self.assertIsNotNone(module)
        self.assertTrue(callable(getattr(module, "gate", None)))

    def test_returns_cached_module_when_already_imported(self):
        first = sibling_import.load_sibling("sibling_import")
        second = sibling_import.load_sibling("sibling_import")
        self.assertIs(first, second)

    def test_missing_module_returns_none_not_raise(self):
        self.assertIsNone(
            sibling_import.load_sibling("definitely_not_a_runner_module_x9"))

    def test_bad_input_returns_none(self):
        for value in (None, "", 42, [], {}):
            self.assertIsNone(sibling_import.load_sibling(value))

    def test_does_not_leave_partial_module_registered_on_failure(self):
        name = "definitely_not_a_runner_module_x9"
        sibling_import.load_sibling(name)
        self.assertNotIn(name, sys.modules)


class GuardCallSiteTests(unittest.TestCase):
    """Each fail-closed gate must resolve its guard through the shared loader."""

    def test_merge_train_load_guard_resolves(self):
        merge_train = sibling_import.load_sibling("merge_train")
        if merge_train is None:
            self.skipTest("merge_train not importable in this environment")
        self.assertIsNotNone(merge_train._load_guard("regression_guard"))
        self.assertIsNone(merge_train._load_guard("no_such_guard_module_x9"))

    def test_auto_conflict_resolver_load_guard_resolves(self):
        acr = sibling_import.load_sibling("auto_conflict_resolver")
        if acr is None:
            self.skipTest("auto_conflict_resolver not importable here")
        self.assertIsNotNone(acr._load_guard("regression_guard"))
        self.assertIsNone(acr._load_guard("no_such_guard_module_x9"))


if __name__ == "__main__":
    unittest.main()
