#!/usr/bin/env python3
"""What tools/lint_conventions.scan_directory is allowed to look at.

Scope is not a detail for this gate — it is the gate. The ratchet in
`regressions()` fails a commit when a rule's count RISES above the baseline, so
every file the scanner reaches becomes part of the number a future commit is
judged against. Two ways that goes wrong, both fixed here:

  * A nested checkout (an agent worktree, a vendored repo) is a second copy of
    the same source. Scanning it doubles every count. An unrelated worktree
    existing during a run fails an unrelated commit; removing one hides a real
    regression of the same size. Nothing records which copy the numbers came
    from, so the failure reads as "you introduced 3,276 violations".

  * The skip list was matched against the ABSOLUTE path, so any component of
    the checkout's own location could disable the gate. A machine keeping its
    repos under ~/build/ or ~/env/ scanned nothing and reported clean.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lint_conventions as lc  # noqa: E402


#: One MAGIC_NUMBERS violation, so each file contributes a countable amount.
VIOLATING_SOURCE = "def f():\n    return 12345\n"


class ScanScopeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # .resolve(): on macOS /tmp is a symlink to /private/tmp, and
        # scan_directory resolves its root, so an unresolved fixture root
        # cannot be used to relativise the paths it reports.
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, relpath, source=VIOLATING_SOURCE):
        path = self.root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
        return path

    def scanned_files(self):
        return {
            Path(v.filepath).relative_to(self.root).as_posix()
            for v in lc.scan_directory(str(self.root))
        }


class TestNestedCheckoutsAreNotCountedTwice(ScanScopeTest):
    def test_an_agent_worktree_sibling_dir_is_skipped(self):
        self.write("runner/real.py")
        self.write("claude-orchestrator-wt/some-slug/runner/real.py")
        self.assertEqual(self.scanned_files(), {"runner/real.py"})

    def test_a_directory_with_its_own_git_is_skipped(self):
        self.write("runner/real.py")
        self.write("vendor/other-repo/mod.py")
        (self.root / "vendor" / "other-repo" / ".git").mkdir()
        self.assertEqual(self.scanned_files(), {"runner/real.py"})

    def test_a_git_file_entry_marks_a_worktree_too(self):
        # git worktrees carry a .git FILE, not a directory.
        self.write("runner/real.py")
        self.write("nested/mod.py")
        (self.root / "nested" / ".git").write_text("gitdir: /elsewhere\n")
        self.assertEqual(self.scanned_files(), {"runner/real.py"})

    def test_the_count_does_not_double_when_a_worktree_exists(self):
        self.write("runner/real.py")
        before = len(lc.scan_directory(str(self.root)))
        self.write("repo-wt/branch-a/runner/real.py")
        after = len(lc.scan_directory(str(self.root)))
        self.assertEqual(before, after)
        self.assertGreater(before, 0, "the fixture must actually violate something")


class TestSkipListIsRelativeToTheScanRoot(ScanScopeTest):
    def test_a_root_named_like_a_skipped_dir_still_gets_scanned(self):
        # The whole tree lives under a directory called "build".
        root = self.root / "build" / "myrepo"
        (root / "runner").mkdir(parents=True)
        (root / "runner" / "real.py").write_text(VIOLATING_SOURCE)
        violations = lc.scan_directory(str(root))
        self.assertGreater(
            len(violations), 0,
            "matching the absolute path let the checkout's own location "
            "silently disable the gate",
        )

    def test_a_skipped_dir_inside_the_tree_is_still_skipped(self):
        self.write("runner/real.py")
        self.write("build/generated.py")
        self.write("node_modules/pkg/mod.py")
        self.write(".orch-tmp/scratch.py")
        self.write("runner/_to_delete/old.py")
        self.assertEqual(self.scanned_files(), {"runner/real.py"})


class TestOrderingIsStable(ScanScopeTest):
    def test_two_runs_report_in_the_same_order(self):
        for name in ("c.py", "a.py", "b.py"):
            self.write("runner/" + name)
        first = [v.filepath for v in lc.scan_directory(str(self.root))]
        second = [v.filepath for v in lc.scan_directory(str(self.root))]
        self.assertEqual(first, second)
        self.assertEqual(first, sorted(first))


class TestOrdinarySourceIsUnaffected(ScanScopeTest):
    def test_normal_files_are_still_scanned(self):
        self.write("runner/a.py")
        self.write("tools/b.py")
        self.write("scripts/nested/c.py")
        self.assertEqual(
            self.scanned_files(),
            {"runner/a.py", "tools/b.py", "scripts/nested/c.py"},
        )

    def test_a_clean_file_produces_no_violations(self):
        self.write("runner/clean.py", "def f():\n    return None\n")
        self.assertEqual(lc.scan_directory(str(self.root)), [])


class TestFrameworkMandatedNamesAreExempt(ScanScopeTest):
    """A name the library dispatches on is not a style choice.

    `ast.NodeVisitor` looks up `visit_<NodeType>` and `unittest` looks up
    `setUp`/`tearDown` by exact spelling, so "rename it to snake_case" is not a
    fix anyone can apply — it breaks the code. Thirteen of the tree's
    NAMING_CONVENTION violations were this linter's own visitor methods: the
    rule was punishing the code written to enforce it, which is the same trap
    `_is_regex_source` already exists to avoid.
    """

    def rules_for(self, source):
        self.write("mod.py", source)
        return [v.rule for v in lc.check_file(str(self.root / "mod.py"))]

    def test_ast_visitor_methods_are_not_flagged(self):
        source = (
            "import ast\n\n\n"
            "class V(ast.NodeVisitor):\n"
            "    def visit_ClassDef(self, node):\n        return None\n\n"
            "    def visit_AsyncFunctionDef(self, node):\n        return None\n\n"
            "    def generic_visit(self, node):\n        return None\n"
        )
        self.assertNotIn("NAMING_CONVENTION", self.rules_for(source))

    def test_unittest_fixtures_are_not_flagged(self):
        source = (
            "import unittest\n\n\n"
            "class T(unittest.TestCase):\n"
            "    def setUp(self):\n        return None\n\n"
            "    def tearDown(self):\n        return None\n\n"
            "    @classmethod\n"
            "    def setUpClass(cls):\n        return None\n"
        )
        self.assertNotIn("NAMING_CONVENTION", self.rules_for(source))

    def test_an_ordinary_camelcase_function_is_still_flagged(self):
        # The exemption is a named list, not an amnesty for capital letters.
        source = "def doTheThing():\n    return None\n"
        self.assertIn("NAMING_CONVENTION", self.rules_for(source))

    def test_a_lookalike_that_no_framework_dispatches_on_is_still_flagged(self):
        source = "def visitOrder(order):\n    return None\n"
        self.assertIn("NAMING_CONVENTION", self.rules_for(source))


if __name__ == "__main__":
    unittest.main(verbosity=2)
