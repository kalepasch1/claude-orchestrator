"""The runner's merge-candidate filter, and its agreement with the tools/ copy.

`runner/merged_diff_memory.py::_get_merged_commits()` used to return every merge
commit in the lookback window. Each one then cost three git subprocesses plus a
quality-gate pass in `_extract_patterns_from_commit()` — and a revert, a WIP
merge, or a merge of a non-agent branch cannot produce a reusable convention, so
that work bought a guaranteed rejection. The measured history here is stark: a
14-day window once put 447 commits through the gate and had 447 rejected.

The rules already exist in `tools/merged_diff_memory.py`. They are duplicated into
`runner/merge_candidate.py` rather than imported, because `runner/` puts its own
directory on sys.path and does `import db` against it — reaching sideways into
`tools/` from a module with five production importers is an import that works on
one machine and fails in the runner.

Duplication is a liability, so the last test in this file is the one that matters:
the two implementations must give the same answer on the same input.
"""
import importlib.util
import os
import sys
import unittest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(RUNNER)
sys.path.insert(0, RUNNER)

import merge_candidate as mc  # noqa: E402


# One table, used both for the runner's own behaviour and for the parity check, so
# the two can never be tested against different cases.
MESSAGE_CASES = [
    # (message, expected_is_candidate, why)
    ("Merge branch 'agent/fix-thing'", True, "the ordinary case"),
    ('Merge branch "agent/fix-thing"', True, "double quotes"),
    ("Merge branch 'agent/deeply/nested/name'", True, "slashes inside the branch name"),
    ("Merge branch 'agent/x'\n\nbody text", True, "only the first line is read"),
    ("  Merge branch 'agent/x'  ", True, "surrounding whitespace"),
    ("Merge branch 'main'", False, "not an agent branch"),
    ("Merge branch 'feature/x'", False, "not an agent branch"),
    ("Merge pull request #12 from foo", False, "not the agent merge shape"),
    ("fix(lint): a normal commit", False, "not a merge at all"),
    ("Revert \"Merge branch 'agent/x'\"", False, "a revert undoes the thing worth learning"),
    ("revert: Merge branch 'agent/x'", False, "revert, lowercase"),
    ("WIP Merge branch 'agent/x'", False, "WIP carries no settled convention"),
    ("wip: Merge branch 'agent/x'", False, "wip, lowercase"),
    ("fixup! Merge branch 'agent/x'", False, "fixup"),
    ("squash! Merge branch 'agent/x'", False, "squash"),
    ("amend! Merge branch 'agent/x'", False, "amend"),
    ("Merge branch 'agent/'", False, "empty branch name"),
    ("", False, "blank"),
    ("   ", False, "whitespace only"),
    (None, False, "None"),
    (42, False, "not a string"),
]

PATH_CASES = [
    ("runner/foo.py", False, "ordinary source"),
    ("package-lock.json", True, "lockfile"),
    ("yarn.lock", True, "lockfile"),
    ("pnpm-lock.yaml", True, "lockfile"),
    ("app/Cargo.lock", True, "lockfile by glob, nested"),
    ("node_modules/left-pad/index.js", True, "vendored dependency"),
    ("a/b/__pycache__/x.pyc", True, "bytecode dir"),
    ("dist/bundle.js", True, "build output"),
    ("build/out.o", True, "build output"),
    ("vendor/lib.go", True, "vendored"),
    ("coverage/lcov.info", True, "coverage"),
    ("assets/app.min.js", True, "minified"),
    ("assets/app.min.css", True, "minified"),
    ("assets/app.js.map", True, "sourcemap"),
    ("img/logo.png", True, "binary"),
    ("doc/spec.pdf", True, "binary"),
    ("./runner/foo.py", False, "leading ./ is normalised, still source"),
    ("runner\\foo.py", False, "backslashes normalised, still source"),
    ("", True, "blank counts as ignored"),
    (None, True, "None counts as ignored"),
]


class MessagePredicate(unittest.TestCase):
    def test_every_message_case(self):
        for message, expected, why in MESSAGE_CASES:
            with self.subTest(message=message, why=why):
                self.assertEqual(mc.is_merge_candidate(message), expected, why)

    def test_it_returns_the_branch_name_not_just_a_bool(self):
        self.assertEqual(mc.merge_candidate_branch("Merge branch 'agent/fix-thing'"), "fix-thing")
        self.assertIsNone(mc.merge_candidate_branch("Merge branch 'main'"))

    def test_it_never_raises(self):
        for junk in (None, 42, [], {}, object()):
            self.assertFalse(mc.is_merge_candidate(junk))


class PathPredicate(unittest.TestCase):
    def test_every_path_case(self):
        for path, expected, why in PATH_CASES:
            with self.subTest(path=path, why=why):
                self.assertEqual(mc.is_ignored_path(path), expected, why)

    def test_operator_supplied_globs_are_honoured(self):
        os.environ["MERGED_DIFF_IGNORED_GLOBS"] = "*.generated.ts, secrets.yml"
        try:
            self.assertTrue(mc.is_ignored_path("app/types.generated.ts"))
            self.assertTrue(mc.is_ignored_path("secrets.yml"))
            self.assertFalse(mc.is_ignored_path("app/types.ts"))
        finally:
            os.environ.pop("MERGED_DIFF_IGNORED_GLOBS", None)


class RecordPredicate(unittest.TestCase):
    def good(self, **over):
        base = {"commit_hash": "abc1234", "merge_message": "Merge branch 'agent/x'",
                "diff": "diff --git a/x b/x", "files": ["runner/x.py"]}
        base.update(over)
        return base

    def test_accepts_a_real_record(self):
        self.assertTrue(mc.is_merge_candidate_commit(self.good()))

    def test_rejects_an_empty_diff(self):
        # Acceptance criterion: an empty diff must not reach pattern extraction.
        self.assertFalse(mc.is_merge_candidate_commit(self.good(diff="")))
        self.assertFalse(mc.is_merge_candidate_commit(self.good(diff="   ")))
        self.assertFalse(mc.is_merge_candidate_commit(self.good(diff=None)))

    def test_rejects_a_merge_touching_only_ignored_paths(self):
        # Acceptance criterion: a lockfile-only merge carries no convention.
        self.assertFalse(mc.is_merge_candidate_commit(
            self.good(files=["package-lock.json", "node_modules/x/index.js", "dist/a.js"])))

    def test_one_real_file_among_ignored_ones_is_enough(self):
        self.assertTrue(mc.is_merge_candidate_commit(
            self.good(files=["package-lock.json", "runner/real.py"])))

    def test_rejects_missing_hash_bad_message_and_malformed_files(self):
        self.assertFalse(mc.is_merge_candidate_commit(self.good(commit_hash="")))
        self.assertFalse(mc.is_merge_candidate_commit(self.good(merge_message="Revert x")))
        self.assertFalse(mc.is_merge_candidate_commit(self.good(files="notalist")))
        self.assertFalse(mc.is_merge_candidate_commit(self.good(files=[])))

    def test_never_raises_on_junk(self):
        for junk in (None, 42, [], "string", object()):
            self.assertFalse(mc.is_merge_candidate_commit(junk))


class ScanFilter(unittest.TestCase):
    """filter_merge_candidates takes the exact shape _get_merged_commits returns."""

    def test_keeps_candidates_and_drops_the_rest(self):
        commits = [
            ("aaa1111", "Merge branch 'agent/keep-me'"),
            ("bbb2222", "Revert \"Merge branch 'agent/drop-me'\""),
            ("ccc3333", "Merge branch 'main'"),
            ("ddd4444", "WIP Merge branch 'agent/drop-me-too'"),
            ("eee5555", "Merge branch 'agent/keep-me-as-well'"),
        ]
        kept = mc.filter_merge_candidates(commits)
        self.assertEqual([h for h, _ in kept], ["aaa1111", "eee5555"])

    def test_survives_malformed_entries(self):
        # A scan that raises on one bad record loses the entire window.
        self.assertEqual(mc.filter_merge_candidates(
            [None, (), ("onlyhash",), ("", "Merge branch 'agent/x'"),
             ("fff6666", "Merge branch 'agent/ok'")]),
            [("fff6666", "Merge branch 'agent/ok'")])

    def test_empty_and_none_input(self):
        self.assertEqual(mc.filter_merge_candidates([]), [])
        self.assertEqual(mc.filter_merge_candidates(None), [])


class WiredIntoTheProductionScanner(unittest.TestCase):
    """A predicate nothing calls is the same defect as no predicate."""

    def _source(self):
        with open(os.path.join(RUNNER, "merged_diff_memory.py"), encoding="utf-8") as fh:
            return fh.read()

    def test_the_scan_entry_point_filters(self):
        src = self._source()
        self.assertIn("from merge_candidate import filter_merge_candidates", src)
        self.assertIn("filter_merge_candidates(commits)", src)

    def test_the_extraction_loop_drops_ignored_only_records(self):
        src = self._source()
        self.assertIn("_record_worth_keeping(p)", src)

    def test_the_gate_is_fail_soft(self):
        # An unimportable predicate must degrade to an unfiltered scan, not to no
        # scan at all — losing the whole window is worse than scanning noise.
        src = self._source()
        self.assertIn("scanning unfiltered", src)


class ParityWithTools(unittest.TestCase):
    """The duplication must not drift.

    `tools/merged_diff_memory.py` holds the same rules. It is loaded by PATH rather
    than imported by name, because that is exactly the cross-directory import the
    runner copy exists to avoid — the test may reach across; production may not.
    """

    @classmethod
    def setUpClass(cls):
        path = os.path.join(REPO, "tools", "merged_diff_memory.py")
        cls.tools = None
        cls.reason = ""
        if not os.path.isfile(path):
            cls.reason = "tools/merged_diff_memory.py is not present"
            return
        try:
            spec = importlib.util.spec_from_file_location("_tools_mdm", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception as exc:                     # noqa: BLE001
            cls.reason = f"tools/merged_diff_memory.py did not import: {exc}"
            return
        if not hasattr(mod, "is_merge_candidate"):
            cls.reason = ("tools/merged_diff_memory.py has no is_merge_candidate — the "
                          "predicate was added by commit ccba41d8, which is not on master")
            return
        cls.tools = mod

    def test_the_case_tables_are_not_empty(self):
        # A parity test over zero cases passes against anything.
        self.assertGreater(len(MESSAGE_CASES), 15)
        self.assertGreater(len(PATH_CASES), 15)

    def test_message_predicate_agrees(self):
        if self.tools is None:
            self.skipTest(self.reason)
        for message, _expected, why in MESSAGE_CASES:
            with self.subTest(message=message, why=why):
                self.assertEqual(mc.is_merge_candidate(message),
                                 self.tools.is_merge_candidate(message), why)

    def test_path_predicate_agrees(self):
        if self.tools is None:
            self.skipTest(self.reason)
        for path, _expected, why in PATH_CASES:
            with self.subTest(path=path, why=why):
                self.assertEqual(mc.is_ignored_path(path),
                                 self.tools._is_ignored_path(path), why)

    def test_record_predicate_agrees(self):
        if self.tools is None:
            self.skipTest(self.reason)
        records = [
            {"commit_hash": "a", "merge_message": "Merge branch 'agent/x'",
             "diff": "d", "files": ["runner/x.py"]},
            {"commit_hash": "a", "merge_message": "Merge branch 'agent/x'",
             "diff": "", "files": ["runner/x.py"]},
            {"commit_hash": "a", "merge_message": "Merge branch 'agent/x'",
             "diff": "d", "files": ["package-lock.json"]},
            {"commit_hash": "", "merge_message": "Merge branch 'agent/x'",
             "diff": "d", "files": ["runner/x.py"]},
        ]
        for rec in records:
            with self.subTest(rec=rec):
                self.assertEqual(mc.is_merge_candidate_commit(rec),
                                 self.tools.is_merge_candidate_commit(rec))

    def test_the_constant_tables_match(self):
        if self.tools is None:
            self.skipTest(self.reason)
        self.assertEqual(set(mc.IGNORED_PATH_GLOBS), set(self.tools.IGNORED_PATH_GLOBS))
        self.assertEqual(set(mc.IGNORED_PATH_SEGMENTS), set(self.tools.IGNORED_PATH_SEGMENTS))
        self.assertEqual(mc.EXCLUDED_MESSAGE_PATTERN.pattern,
                         self.tools.EXCLUDED_MESSAGE_PATTERN.pattern)
        self.assertEqual(mc.MERGE_COMMIT_PATTERN.pattern,
                         self.tools.MERGE_COMMIT_PATTERN.pattern)


if __name__ == "__main__":
    unittest.main()
