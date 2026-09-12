"""conftest's module-isolation machinery runs on every test. It must not touch the disk.

WHAT THIS GUARDS. _remember_real_modules and _evict_stub_shadows both walk all of
sys.modules on EVERY test, and sys.modules holds ~1,000 entries once the suite is warm.
Until 2026-09-08 each entry cost an os.path.abspath and an os.path.isfile. cProfile over a
four-file slice, before and after:

    posix.stat   942,404 -> 29,516     912,888 removed
    isfile       913,450 ->     562    912,888 removed
    abspath      676,399 -> 16,250     660,149 removed

The call counts of the isolation helpers themselves are unchanged -- 788,125 either way.
They still run exactly as often; they just stopped re-deriving two unchanging answers from
the filesystem each time.

Wall clock, six interleaved runs of the same 192 tests on the same box:

    patched   21.13s  25.15s  25.27s      (min 21.13, spread  4.1s)
    original  56.15s  43.80s  68.70s      (min 43.80, spread 24.9s)

Non-overlapping, 2.1x on minimums. Note the spread: the removed work is syscalls, whose
cost tracks machine load, which is why the unpatched version varies six times as widely.
Worth stating plainly because an earlier single before/after pair on this same box read
"3.4x" and was wrong -- the baseline had been taken while the machine was busy.

These tests pin the CACHING, not the timings. A future edit that reintroduces a per-test
stat will fail here rather than quietly costing the suite a million syscalls again.
"""
import os
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: BOUND BY PATH, NOT BY NAME, and the reason is this repo's own layout: there is a
#: conftest.py at the REPO ROOT as well as this one under runner/tests/. Under pytest the
#: root one owns the name `conftest` in sys.modules, so a plain `import conftest` here
#: silently binds to the wrong file -- it resolves correctly standalone and fails only
#: inside the suite, which is the worst shape a test-only bug can have. Reaching for the
#: module object pytest already loaded also means these tests exercise the exact instance
#: the isolation machinery is running from, rather than a second execution of the file.
_THIS_CONFTEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "conftest.py")


def _loaded_conftest():
    for module in list(sys.modules.values()):
        path = getattr(module, "__file__", None)
        if path and os.path.abspath(path) == _THIS_CONFTEST:
            return module
    raise AssertionError(f"runner/tests/conftest.py is not loaded; looked for {_THIS_CONFTEST}")


conftest = _loaded_conftest()

EXPECTED_NONE = 0
EXPECTED_ONE = 1


class TheRunnerModuleListingIsReadOnce(unittest.TestCase):

    def test_repeated_calls_do_not_relist_the_directory(self):
        """One listdir for the life of the process, however many tests run."""
        conftest._runner_module_names.cache_clear()
        with patch.object(conftest.os, "listdir",
                          return_value=["queue_janitor.py", "db.py", "notes.txt"]) as listdir:
            first = conftest._runner_module_names()
            for _repeat in range(50):
                conftest._runner_module_names()
        self.assertEqual(listdir.call_count, EXPECTED_ONE,
                         "the runner/ listing was re-read; it is a per-test cost again")
        self.assertEqual(first, frozenset({"queue_janitor", "db"}))

    def test_it_agrees_with_the_isfile_check_it_replaced(self):
        """Equivalence against the original predicate, on the real runner/ directory."""
        conftest._runner_module_names.cache_clear()
        names = conftest._runner_module_names()
        for name in names:
            self.assertTrue(
                os.path.isfile(os.path.join(conftest._RUNNER_DIR, f"{name}.py")),
                f"{name} is listed as a runner module but has no runner/{name}.py")
        for entry in os.listdir(conftest._RUNNER_DIR):
            if entry.endswith(".py"):
                self.assertIn(entry[:-len(".py")], names,
                              f"{entry} exists in runner/ but the listing missed it")

    def test_a_directory_that_cannot_be_read_yields_an_empty_listing(self):
        """Fail soft. conftest must never be the thing that breaks collection."""
        conftest._runner_module_names.cache_clear()
        with patch.object(conftest.os, "listdir", side_effect=OSError("gone")):
            self.assertEqual(conftest._runner_module_names(), frozenset())
        conftest._runner_module_names.cache_clear()


class ThePathCheckIsCached(unittest.TestCase):

    def test_the_same_path_is_resolved_once(self):
        conftest._path_is_in_runner_dir.cache_clear()
        probe = os.path.join(conftest._RUNNER_DIR, "queue_janitor.py")
        with patch.object(conftest.os.path, "abspath", wraps=os.path.abspath) as abspath:
            for _repeat in range(50):
                conftest._path_is_in_runner_dir(probe)
        self.assertEqual(abspath.call_count, EXPECTED_ONE,
                         "abspath ran per call; the path check is uncached again")

    def test_it_still_answers_correctly_for_both_cases(self):
        conftest._path_is_in_runner_dir.cache_clear()
        self.assertTrue(conftest._path_is_in_runner_dir(
            os.path.join(conftest._RUNNER_DIR, "queue_janitor.py")))
        self.assertFalse(conftest._path_is_in_runner_dir("/usr/lib/python3/os.py"))

    def test_a_module_with_no_file_is_not_a_runner_module(self):
        """Namespace packages and C extensions have no __file__ at all."""
        conftest._path_is_in_runner_dir.cache_clear()
        bare = types.ModuleType("bare_probe")
        self.assertFalse(conftest._is_real_runner_module(bare))

    def test_a_module_inside_runner_is_recognised(self):
        conftest._path_is_in_runner_dir.cache_clear()
        stand_in = types.ModuleType("probe")
        stand_in.__file__ = os.path.join(conftest._RUNNER_DIR, "probe.py")
        self.assertTrue(conftest._is_real_runner_module(stand_in))


if __name__ == "__main__":
    unittest.main()
