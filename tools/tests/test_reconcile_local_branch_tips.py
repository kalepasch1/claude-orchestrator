"""Unit tests for the local-branch-tip reconciler.

Run: python3 -m pytest tools/tests/test_reconcile_local_branch_tips.py

Builds a throwaway git repo per test so the assertions exercise real git
plumbing rather than mocks — the classifier's whole job is reading git state
correctly, and a mock would happily agree with a wrong command.
"""

import os
import subprocess
import tempfile
import unittest

import sys
# The module under test lives one directory up, beside the rest of tools/.
# This file moved into tools/tests/ so it satisfies write_guard's rule that
# test files live in a `tests` directory; the import target did not move.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import reconcile_local_branch_tips as r  # noqa: E402


def run(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True,
                   capture_output=True, text=True)


def commit(repo, message):
    run(repo, "add", "-A")
    run(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", message)


def write(repo, rel, body):
    path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(body)


class ReconcilerTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        run(self.repo, "init", "-q", "-b", "main")
        write(self.repo, "src/app.ts", "export const x = 1\n")
        write(self.repo, "src/__tests__/app.test.ts",
              "describe('x', () => {\n"
              "  it('keeps one', () => {})\n"
              "  it('keeps two', () => {})\n"
              "})\n")
        commit(self.repo, "base")
        self.addCleanup(self.tmp.cleanup)

    def branch(self, name):
        run(self.repo, "checkout", "-q", "-b", name)

    def back(self):
        run(self.repo, "checkout", "-q", "main")

    def classify(self, ref, states=None):
        return r.classify(self.repo, "main", ref, states or {})


class TestEmptyAndPresent(ReconcilerTestCase):
    def test_branch_with_no_unique_commits_is_already_present(self):
        self.branch("agent/empty")
        self.back()
        self.assertEqual(self.classify("agent/empty").classification,
                         "ALREADY_PRESENT")

    def test_live_task_ownership_beats_content_inspection(self):
        self.branch("agent/owned")
        write(self.repo, ".recovery-intent-owned.txt", "marker\n")
        commit(self.repo, "marker only")
        self.back()
        item = self.classify("agent/owned", {"owned": "QUEUED"})
        self.assertEqual(item.classification, "ACTIVE_IN_ANOTHER_TASK")


class TestRegressionGuards(ReconcilerTestCase):
    def test_marker_only_branch_has_nothing_to_recover(self):
        self.branch("agent/marker")
        write(self.repo, ".recovery-intent-marker.txt", "recovery-intent: marker\n")
        commit(self.repo, "marker only")
        self.back()
        item = self.classify("agent/marker")
        self.assertEqual(item.classification, "SUPERSEDED_BY_NEWER")
        self.assertIn("marker file", item.disposition)

    def test_clean_merge_that_deletes_a_live_file_needs_a_focused_task(self):
        self.branch("agent/deleter")
        os.remove(os.path.join(self.repo, "src/app.ts"))
        commit(self.repo, "drop app")
        self.back()
        item = self.classify("agent/deleter")
        self.assertEqual(item.classification, "CONFLICTED_NEEDS_FOCUSED_TASK")
        self.assertIn("src/app.ts", item.deletes)

    def test_clean_merge_that_strips_test_cases_needs_a_focused_task(self):
        """The regression that a file-deletion check alone would wave through."""
        self.branch("agent/coverage-cut")
        write(self.repo, "src/__tests__/app.test.ts",
              "describe('x', () => {\n"
              "  it('keeps one', () => {})\n"
              "})\n")
        commit(self.repo, "drop a test case")
        self.back()
        item = self.classify("agent/coverage-cut")
        self.assertEqual(item.classification, "CONFLICTED_NEEDS_FOCUSED_TASK")
        self.assertIn("REMOVES 1 test case", item.disposition)

    def test_clean_merge_that_guts_a_surviving_module_needs_a_focused_task(self):
        """Gutting a file leaves an `M`, so a file-level check alone misses it."""
        write(self.repo, "runner/tool.py",
              "def keep():\n    return 1\n\n\ndef gutted():\n    return 2\n")
        commit(self.repo, "add tool")
        self.branch("agent/gutter")
        write(self.repo, "runner/tool.py", "def keep():\n    return 1\n")
        commit(self.repo, "strip gutted()")
        self.back()
        item = self.classify("agent/gutter")
        self.assertEqual(item.classification, "CONFLICTED_NEEDS_FOCUSED_TASK")
        self.assertIn("gutted", item.disposition)

    def test_renaming_is_not_treated_as_removal_when_symbol_is_re_added(self):
        write(self.repo, "runner/tool.py", "def alpha():\n    return 1\n")
        commit(self.repo, "add tool")
        self.branch("agent/reorder")
        write(self.repo, "runner/tool.py", "# moved\ndef alpha():\n    return 1\n")
        commit(self.repo, "reorder only")
        self.back()
        self.assertEqual(self.classify("agent/reorder").classification,
                         "RECOVERABLE_VALUE")

    def test_additive_change_is_recoverable(self):
        self.branch("agent/additive")
        write(self.repo, "src/feature.ts", "export const y = 2\n")
        commit(self.repo, "add feature")
        self.back()
        item = self.classify("agent/additive")
        self.assertEqual(item.classification, "RECOVERABLE_VALUE")
        self.assertEqual(item.deletes, [])


class TestStaleMergeBase(ReconcilerTestCase):
    def test_branch_whose_content_already_landed_is_already_present(self):
        """The three-dot diff still shows a patch; the blobs say it already landed."""
        self.branch("agent/landed")
        write(self.repo, "src/feature.ts", "export const y = 2\n")
        commit(self.repo, "feature on branch")
        self.back()
        # Same content lands on main by another route, so the branch adds nothing.
        write(self.repo, "src/feature.ts", "export const y = 2\n")
        commit(self.repo, "same feature via another path")

        self.assertTrue(r.git(self.repo, "diff", "--name-only", "main...agent/landed"),
                        "precondition: three-dot diff still reports a patch")
        item = self.classify("agent/landed")
        self.assertEqual(item.classification, "ALREADY_PRESENT")
        self.assertIn("stale merge base", item.disposition)

    def test_contribution_already_upstream_inside_a_file_that_moved_on(self):
        """The file still differs, but the branch's own line is already on main.

        Models `fix-release-train-manifest-import`: the branch adds one import that
        main has since acquired, while main also grew unrelated code far below. The
        blobs differ, so a blob comparison calls it recoverable; merging proves it
        contributes nothing.
        """
        body = "".join(f"line_{n} = {n}\n" for n in range(40))
        write(self.repo, "runner/train.py", f"import a\nimport b\n\n{body}")
        commit(self.repo, "add train")
        self.branch("agent/adds-import")
        write(self.repo, "runner/train.py", f"import a\nimport b\nimport manifest\n\n{body}")
        commit(self.repo, "add the import")
        self.back()
        # main gains the same import, plus unrelated work far from the import block.
        write(self.repo, "runner/train.py",
              f"import a\nimport b\nimport manifest\n\n{body}\n\ndef later():\n    return 1\n")
        commit(self.repo, "same import, plus later work")

        self.assertNotEqual(r.git(self.repo, "rev-parse", "agent/adds-import:runner/train.py"),
                            r.git(self.repo, "rev-parse", "main:runner/train.py"),
                            "precondition: the blobs must differ")
        item = self.classify("agent/adds-import")
        self.assertEqual(item.classification, "ALREADY_PRESENT")
        self.assertIn("would change nothing", item.disposition)

    def test_genuinely_divergent_content_is_not_swallowed(self):
        """Both sides wrote the same path differently: a real conflict, not a no-op."""
        self.branch("agent/divergent")
        write(self.repo, "src/feature.ts", "export const y = 2\n")
        commit(self.repo, "feature on branch")
        self.back()
        write(self.repo, "src/feature.ts", "export const y = 999\n")
        commit(self.repo, "different content on main")
        item = self.classify("agent/divergent")
        self.assertEqual(item.classification, "CONFLICTED_NEEDS_FOCUSED_TASK")
        self.assertIn("src/feature.ts", item.conflicts)


class TestConflictDetection(ReconcilerTestCase):
    def test_conflicting_edit_is_reported_with_its_paths(self):
        """Regression guard: `git merge-tree` exits 1 on conflict, and an exit-code
        check that treats that as failure reports every branch as merging cleanly."""
        write(self.repo, "src/shared.ts", "export const v = 'base'\n")
        commit(self.repo, "add shared")
        self.branch("agent/edit-a")
        write(self.repo, "src/shared.ts", "export const v = 'branch'\n")
        commit(self.repo, "branch edit")
        self.back()
        write(self.repo, "src/shared.ts", "export const v = 'main'\n")
        commit(self.repo, "main edit")

        conflicts = r.merge_conflicts(self.repo, "main", "agent/edit-a")
        self.assertEqual(conflicts, ["src/shared.ts"])

    def test_clean_merge_reports_no_conflicts(self):
        self.branch("agent/clean")
        write(self.repo, "src/other.ts", "export const z = 1\n")
        commit(self.repo, "unrelated file")
        self.back()
        self.assertEqual(r.merge_conflicts(self.repo, "main", "agent/clean"), [])


class TestDuplicateDetection(ReconcilerTestCase):
    def test_identical_patches_share_a_digest(self):
        """Self-heal retries produce many refs for one patch; the digest collapses them."""
        digests = set()
        for name in ("agent/retry-a", "agent/retry-b"):
            self.branch(name)
            write(self.repo, "src/feature.ts", "export const y = 2\n")
            commit(self.repo, f"retry {name}")
            self.back()
            digests.add(self.classify(name).patch_digest)
        self.assertEqual(len(digests), 1)

    def test_different_patches_do_not_collide(self):
        self.branch("agent/one")
        write(self.repo, "src/one.ts", "export const a = 1\n")
        commit(self.repo, "one")
        self.back()
        self.branch("agent/two")
        write(self.repo, "src/two.ts", "export const b = 2\n")
        commit(self.repo, "two")
        self.back()
        self.assertNotEqual(self.classify("agent/one").patch_digest,
                            self.classify("agent/two").patch_digest)


class TestStaleEvidence(ReconcilerTestCase):
    """A concurrent executor can delete a ref between snapshot and reconciliation."""

    def setUp(self):
        super().setUp()
        # Stand up a fake 'origin' so refs/remotes/origin/* exists to fall back to.
        self.upstream = tempfile.TemporaryDirectory()
        self.addCleanup(self.upstream.cleanup)
        run(self.upstream.name, "init", "-q", "--bare", "-b", "main")
        run(self.repo, "remote", "add", "origin", self.upstream.name)

    def test_vanished_local_ref_is_classified_from_origin_not_dropped(self):
        self.branch("agent/published")
        write(self.repo, "src/feature.ts", "export const y = 2\n")
        commit(self.repo, "published work")
        run(self.repo, "push", "-q", "origin", "agent/published")
        self.back()
        run(self.repo, "branch", "-D", "agent/published")  # simulate the other executor

        item = self.classify("agent/published")
        self.assertEqual(item.classification, "ALREADY_PRESENT")
        self.assertIn("published at origin/agent/published", item.disposition)
        self.assertTrue(item.sha, "must still resolve a sha for provenance")


class TestReadOnly(ReconcilerTestCase):
    def test_classification_does_not_move_head_or_touch_branches(self):
        self.branch("agent/probe")
        write(self.repo, "src/feature.ts", "export const y = 2\n")
        commit(self.repo, "probe")
        self.back()
        before_head = r.git(self.repo, "rev-parse", "HEAD")
        before_refs = r.git(self.repo, "for-each-ref", "--format=%(refname) %(objectname)")
        self.classify("agent/probe")
        self.assertEqual(r.git(self.repo, "rev-parse", "HEAD"), before_head)
        self.assertEqual(
            r.git(self.repo, "for-each-ref", "--format=%(refname) %(objectname)"),
            before_refs)


if __name__ == "__main__":
    unittest.main()
