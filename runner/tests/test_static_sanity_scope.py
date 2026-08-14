#!/usr/bin/env python3
"""static_sanity scope discipline: avoid directories, files first, narrow the retry.

The owner module for this intent is runner/static_sanity.py — see
docs/relfix-local-lora-distill-add-test-check-locate-owner-and-baseline.md §2.6, which
identified check()/all_modules() as the scope-limiting surface.

Three properties, each of which failed against the original code:

  * DIRECTORIES ARE AVOIDED — check() filtered on os.path.exists(), which a directory
    satisfies. os.listdir() in all_modules() yields directories too, so a directory
    named "<something>.py" went straight to pyflakes.
  * FILES FIRST — a directory in the batch makes pyflakes error, _pyflakes returns None,
    and check() reports None, which assert_critical() reads as "tooling unavailable" and
    passes EVERYTHING. One bad path silently disabled the gate for every real file.
  * SMALLER RETRY SCOPE — when the whole batch fails, retry file by file so one casualty
    costs one file's coverage instead of all of it.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import static_sanity


class DirectoriesAreAvoidedTest(unittest.TestCase):
    def test_a_directory_named_like_a_module_is_not_scanned(self, ):
        with mock.patch.object(static_sanity, "_pyflakes", return_value="") as pf:
            static_sanity.check([os.path.dirname(static_sanity.__file__)])
        pf.assert_not_called()

    def test_a_batch_of_only_directories_is_clean_not_unavailable(self):
        """[] means 'nothing to report'; None would mean 'gate off' and pass everything."""
        here = os.path.dirname(static_sanity.__file__)
        self.assertEqual(static_sanity.check([here, os.path.join(here, "tests")]), [])

    def test_files_survive_the_filter_while_the_directory_is_dropped(self):
        here = os.path.dirname(static_sanity.__file__)
        real = os.path.join(here, "static_sanity.py")
        seen = {}

        def fake(paths):
            seen["paths"] = list(paths)
            return ""

        with mock.patch.object(static_sanity, "_pyflakes", side_effect=fake):
            static_sanity.check([here, real])
        self.assertEqual(seen["paths"], [real])

    def test_all_modules_returns_only_files(self):
        for p in static_sanity.all_modules():
            self.assertTrue(os.path.isfile(p), p)

    def test_all_modules_still_finds_the_real_modules(self):
        names = {os.path.basename(p) for p in static_sanity.all_modules()}
        self.assertIn("static_sanity.py", names)
        self.assertTrue(all(not n.startswith("test_") for n in names))

    def test_a_nonexistent_path_is_dropped_like_a_directory(self):
        with mock.patch.object(static_sanity, "_pyflakes", return_value="") as pf:
            self.assertEqual(static_sanity.check(["/nope/does-not-exist.py"]), [])
        pf.assert_not_called()


class SmallerRetryScopeTest(unittest.TestCase):
    def _paths(self):
        here = os.path.dirname(static_sanity.__file__)
        return [os.path.join(here, "static_sanity.py"), os.path.join(here, "db.py")]

    def test_a_failed_batch_is_retried_one_file_at_a_time(self):
        calls = []

        def fake(paths):
            calls.append(list(paths))
            if len(paths) > 1:
                return None                      # the batch dies
            return "x.py:1 undefined name 'a'\n"  # each file alone is fine

        with mock.patch.object(static_sanity, "_pyflakes", side_effect=fake):
            findings = static_sanity.check(self._paths())

        self.assertEqual(len(calls[0]), 2)                 # batch attempted first
        self.assertTrue(all(len(c) == 1 for c in calls[1:]))  # then narrowed
        self.assertEqual(len(findings), 2)

    def test_one_bad_file_no_longer_blinds_the_gate_for_the_others(self):
        good, bad = self._paths()

        def fake(paths):
            if len(paths) > 1 or paths[0] == bad:
                return None
            return "good.py:1 undefined name 'z'\n"

        with mock.patch.object(static_sanity, "_pyflakes", side_effect=fake):
            findings = static_sanity.check([good, bad])

        self.assertIsNotNone(findings, "one bad path must not disable the whole gate")
        self.assertEqual(len(findings), 1)

    def test_a_genuinely_missing_pyflakes_still_reports_unavailable(self):
        """Narrowing must not turn 'no tool' into a false all-clear."""
        with mock.patch.object(static_sanity, "_pyflakes", return_value=None):
            self.assertIsNone(static_sanity.check(self._paths()))

    def test_a_single_file_batch_is_not_retried(self):
        calls = []

        def fake(paths):
            calls.append(list(paths))
            return None

        with mock.patch.object(static_sanity, "_pyflakes", side_effect=fake):
            self.assertIsNone(static_sanity.check(self._paths()[:1]))
        self.assertEqual(len(calls), 1)

    def test_a_clean_batch_is_not_retried_at_all(self):
        calls = []

        def fake(paths):
            calls.append(list(paths))
            return ""

        with mock.patch.object(static_sanity, "_pyflakes", side_effect=fake):
            self.assertEqual(static_sanity.check(self._paths()), [])
        self.assertEqual(len(calls), 1)


class ExistingContractIsUnchangedTest(unittest.TestCase):
    def test_findings_are_still_only_undefined_name_lines(self):
        out = "a.py:1 undefined name 'x'\na.py:2 'os' imported but unused\n"
        with mock.patch.object(static_sanity, "_pyflakes", return_value=out):
            findings = static_sanity.check(
                [os.path.join(os.path.dirname(static_sanity.__file__), "db.py")])
        self.assertEqual(findings, ["a.py:1 undefined name 'x'"])

    def test_the_default_batch_is_still_the_critical_modules(self):
        seen = {}
        with mock.patch.object(static_sanity, "_pyflakes",
                               side_effect=lambda p: seen.setdefault("p", list(p)) and ""):
            static_sanity.check()
        names = {os.path.basename(p) for p in seen["p"]}
        self.assertTrue(names.issubset(set(static_sanity.CRITICAL_MODULES)))
        self.assertIn("merge_train.py", names)

    def test_audit_covers_the_whole_tree(self):
        seen = {}

        def fake(paths):
            seen["n"] = len(paths)
            return ""

        with mock.patch.object(static_sanity, "_pyflakes", side_effect=fake):
            static_sanity.audit()
        self.assertGreater(seen["n"], len(static_sanity.CRITICAL_MODULES))


if __name__ == "__main__":
    unittest.main()
