"""The hardcoded-secret lint tests must survive a whole-suite run.

`lint_conventions.py` exists TWICE — `tools/lint_conventions.py` and
`runner/tools/lint_conventions.py` — and ten test modules import it as the bare name
`lint_conventions`, each first inserting its own directory on sys.path. sys.path only
decides the FIRST import; after that the name is cached, so whichever module pytest
collects first binds it for the entire session and every later importer silently gets the
other file.

The result was four security tests aborting collection of the whole selection with

    ImportError: cannot import name 'RULE_HARDCODED_SECRET' from 'lint_conventions'

while each passed in isolation. A collection error is not one red test — pytest stops, so
the hardcoded-secret rule had no effective coverage in any combined run, and neither did
anything else selected alongside it.
"""
import os
import sys
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
RUNNER_DIR = os.path.dirname(TESTS_DIR)
REPO_ROOT = os.path.dirname(RUNNER_DIR)
if RUNNER_DIR not in sys.path:
    sys.path.insert(0, RUNNER_DIR)


class TestTheShadowingIsReal(unittest.TestCase):
    """Pin the situation, so nobody 'fixes' the guard by assuming it went away."""

    def test_both_lint_conventions_files_exist(self):
        self.assertTrue(os.path.isfile(os.path.join(REPO_ROOT, "tools", "lint_conventions.py")))
        self.assertTrue(os.path.isfile(os.path.join(RUNNER_DIR, "tools", "lint_conventions.py")))

    def test_only_one_of_them_defines_the_secret_rule(self):
        """This asymmetry is what turns the shadow into an ImportError."""
        root = open(os.path.join(REPO_ROOT, "tools", "lint_conventions.py"),
                    encoding="utf-8").read()
        nested = open(os.path.join(RUNNER_DIR, "tools", "lint_conventions.py"),
                      encoding="utf-8").read()
        self.assertNotIn("RULE_HARDCODED_SECRET", root)
        self.assertIn("RULE_HARDCODED_SECRET", nested)


class TestConftestEvictsTheShadow(unittest.TestCase):
    def setUp(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_conftest_shadow_under_test", os.path.join(TESTS_DIR, "conftest.py"))
        self.conftest = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.conftest)

    def test_lint_conventions_is_recognised_as_ambiguous(self):
        self.assertIn("lint_conventions", self.conftest._AMBIGUOUS)

    def test_a_uniquely_named_module_is_not_treated_as_ambiguous(self):
        self.assertNotIn("queue_velocity", self.conftest._AMBIGUOUS)

    def test_conftest_is_never_evicted(self):
        """pytest owns the `conftest` name; evicting it would break collection."""
        sys.modules.setdefault("conftest", self.conftest)
        self.conftest._evict_ambiguous_modules()
        self.assertIn("conftest", sys.modules)

    def test_the_cached_shadow_is_dropped(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "lint_conventions", os.path.join(REPO_ROOT, "tools", "lint_conventions.py"))
        wrong = importlib.util.module_from_spec(spec)
        sys.modules["lint_conventions"] = wrong          # simulate the first importer

        self.conftest._evict_ambiguous_modules()

        self.assertNotIn("lint_conventions", sys.modules,
                         "the shadow survived; the next importer would get the wrong file")

    def test_the_secret_rule_imports_after_eviction(self):
        """End to end: the exact import that was failing whole-suite collection."""
        self.conftest._evict_ambiguous_modules()
        sys.path.insert(0, os.path.join(RUNNER_DIR, "tools"))
        try:
            from lint_conventions import RULE_HARDCODED_SECRET, ConventionChecker  # noqa: F401
            self.assertTrue(RULE_HARDCODED_SECRET)
        finally:
            sys.path.remove(os.path.join(RUNNER_DIR, "tools"))
            sys.modules.pop("lint_conventions", None)


if __name__ == "__main__":
    unittest.main()
