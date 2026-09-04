"""find_duplicates.is_collected must read pytest.ini, not a hardcoded guess.

The defect this pins down: COLLECTED_DIRS was the literal ("runner/tests", "tests"),
while pytest.ini declares `testpaths = runner`. Every file at `runner/test_*.py` was
therefore reported `collected_by_pytest = NO`, and DUPLICATES_INVENTORY.md concluded
that ~4,600 lines of live test code was dead and suggested deleting seven files.

Canonical selection ranks "is it collected" FIRST, so a wrong collection model does
not skew the inventory — it inverts it.
"""
import importlib.util
import os
import textwrap
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_spec = importlib.util.spec_from_file_location(
    "find_duplicates", os.path.join(_ROOT, "scripts", "find_duplicates.py"))
find_duplicates = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(find_duplicates)


class CollectedDirsTest(unittest.TestCase):
    def test_it_reads_testpaths_from_pytest_ini(self):
        assert "runner" in find_duplicates.collected_dirs()

    def test_it_unions_rather_than_replaces_the_defaults(self):
        # testpaths governs a bare `pytest`; CI also names targets explicitly, and a
        # file collected by either route is collected.
        dirs = find_duplicates.collected_dirs()
        for default in find_duplicates.DEFAULT_COLLECTED_DIRS:
            assert default in dirs, default

    def test_a_missing_pytest_ini_falls_back(self):
        import pathlib
        got = find_duplicates.collected_dirs(pathlib.Path("/nonexistent-repo-root"))
        assert got == find_duplicates.DEFAULT_COLLECTED_DIRS

    def test_a_testpaths_less_pytest_ini_falls_back(self):
        import pathlib, tempfile
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / "pytest.ini").write_text("[pytest]\nmarkers =\n    slow\n")
            assert find_duplicates.collected_dirs(pathlib.Path(d)) == \
                find_duplicates.DEFAULT_COLLECTED_DIRS

    def test_it_honours_a_custom_testpaths(self):
        import pathlib, tempfile
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / "pytest.ini").write_text(
                textwrap.dedent("[pytest]\ntestpaths = src/checks other/\n"))
            dirs = find_duplicates.collected_dirs(pathlib.Path(d))
            assert "src/checks" in dirs
            assert "other" in dirs, "a trailing slash must not create a distinct entry"

    def test_it_never_raises_on_a_malformed_pytest_ini(self):
        import pathlib, tempfile
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / "pytest.ini").write_text("not an ini file at all [[[")
            assert isinstance(find_duplicates.collected_dirs(pathlib.Path(d)), tuple)


class IsCollectedTest(unittest.TestCase):
    def test_the_runner_top_level_tests_are_collected(self):
        # the exact false negative that produced the wrong inventory
        assert find_duplicates.is_collected("runner/test_qafix_comprehensive_final.py")
        assert find_duplicates.is_collected("runner/test_pricing_grid_reconstruction.py")

    def test_the_nested_and_root_suites_are_still_collected(self):
        assert find_duplicates.is_collected("runner/tests/test_anything.py")
        assert find_duplicates.is_collected("tests/test_anything.py")

    def test_a_test_file_outside_every_collected_root_is_not(self):
        assert not find_duplicates.is_collected("scripts/test_helper.py")
        assert not find_duplicates.is_collected("web/test_thing.py")

    def test_a_non_test_module_is_always_collected(self):
        # a normal module is imported by callers, not collected — reported as such
        assert find_duplicates.is_collected("runner/pricing_grid_reconstruction.py")
        assert find_duplicates.is_collected("scripts/find_duplicates.py")

    def test_a_prefix_match_is_not_a_path_match(self):
        assert not find_duplicates.is_collected("runner-old/test_thing.py",
                                                dirs=("runner",))

    def test_dirs_can_be_injected(self):
        assert find_duplicates.is_collected("a/b/test_x.py", dirs=("a/b",))
        assert not find_duplicates.is_collected("a/b/test_x.py", dirs=("c",))


if __name__ == "__main__":
    unittest.main()
