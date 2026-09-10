"""Namespace-ownership tests for the rescue-ref reconciler.

Run: python3 -m pytest tools/tests/test_rescue_ref_stash_boundary.py

Two reconcilers used to claim the same stash: reconcile_rescue_refs.py listed
`refs/stash` among its namespaces while reconcile_stashes.py documented that it
owned the class. That is not a tie to be broken by taste -- the rescue-ref
module reads every commit with `--first-parent`, so it cannot see the untracked
files a stash keeps on its third parent, and it wrote the item into the ledger
as fully handled anyway.

These tests build real stashes in throwaway repos, because the whole claim is
about what git actually stores.
"""

import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import reconcile_rescue_refs as r  # noqa: E402


def run(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def write(repo, rel, body):
    path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(path) or repo, exist_ok=True)
    with open(path, "w") as fh:
        fh.write(body)


class StashRepoTestCase(unittest.TestCase):
    """Each test runs inside its own repo; the module reads the process CWD."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        run(self.repo, "init", "-q", "-b", "main")
        write(self.repo, "app.py", "X = 1\n")
        run(self.repo, "add", "-A")
        run(self.repo, "-c", "user.name=t", "-c", "user.email=t@t",
            "commit", "-qm", "base")

        self._cwd = os.getcwd()
        os.chdir(self.repo)
        self.addCleanup(lambda: os.chdir(self._cwd))
        self.addCleanup(self.tmp.cleanup)

    def make_stash_with_untracked(self, message="wip"):
        write(self.repo, "app.py", "X = 2\n")
        write(self.repo, "brand_new.py", "NEW = True\n")
        run(self.repo, "stash", "push", "-q", "-u", "-m", message)

    def make_rescue_ref(self, name="20260803T000716-sweep"):
        run(self.repo, "checkout", "-q", "-b", "side")
        write(self.repo, "side_only.py", "S = 1\n")
        run(self.repo, "add", "-A")
        run(self.repo, "-c", "user.name=t", "-c", "user.email=t@t",
            "commit", "-qm", "orch-rescue: periodic sweep")
        sha = run(self.repo, "rev-parse", "HEAD")
        run(self.repo, "checkout", "-q", "main")
        run(self.repo, "branch", "-q", "-D", "side")
        run(self.repo, "update-ref", "refs/orch-rescue/" + name, sha)
        return sha


class TestStashIsNotEnumeratedHere(StashRepoTestCase):
    def test_stash_namespace_is_not_in_rescue_namespaces(self):
        self.assertNotIn(r.STASH_NAMESPACE, r.RESCUE_NAMESPACES)
        for ns in r.RESCUE_NAMESPACES:
            self.assertFalse(ns.startswith(r.STASH_NAMESPACE))

    def test_a_stash_does_not_appear_among_enumerated_items(self):
        self.make_stash_with_untracked()
        refs = [it.ref for it in r.enumerate_refs()]
        self.assertNotIn("refs/stash", refs)

    def test_rescue_refs_are_still_enumerated_alongside_a_stash(self):
        self.make_rescue_ref()
        self.make_stash_with_untracked()
        refs = [it.ref for it in r.enumerate_refs()]
        self.assertIn("refs/orch-rescue/20260803T000716-sweep", refs)
        self.assertNotIn("refs/stash", refs)

    def test_stash_ref_is_filtered_even_if_the_namespace_tuple_is_edited_back(self):
        self.make_stash_with_untracked()
        saved = r.RESCUE_NAMESPACES
        r.RESCUE_NAMESPACES = saved + (r.STASH_NAMESPACE,)
        self.addCleanup(lambda: setattr(r, "RESCUE_NAMESPACES", saved))
        refs = [it.ref for it in r.enumerate_refs()]
        self.assertNotIn("refs/stash", refs)


class TestWhyStashCannotBeClassifiedHere(StashRepoTestCase):
    """The reason for the boundary, asserted against real git output."""

    def test_first_parent_probe_misses_untracked_stash_content(self):
        self.make_stash_with_untracked()
        stash_sha = run(self.repo, "rev-parse", "refs/stash")

        # What this module's changed_files() would have reported.
        seen = r.changed_files(stash_sha)

        # What the stash actually carries.
        actual = run(self.repo, "stash", "show", "-u", "--name-only",
                     "stash@{0}").splitlines()

        self.assertIn("app.py", seen)
        self.assertIn("brand_new.py", actual)
        self.assertNotIn(
            "brand_new.py", seen,
            "if this ever passes, --first-parent started seeing the untracked "
            "parent and the boundary can be revisited",
        )

    def test_for_each_ref_reports_only_the_tip_of_the_stash_stack(self):
        self.make_stash_with_untracked("first")
        write(self.repo, "app.py", "X = 3\n")
        run(self.repo, "stash", "push", "-q", "-m", "second")

        listed = [ln for ln in run(self.repo, "stash", "list").splitlines()
                  if ln.strip()]
        via_for_each_ref = [
            ln for ln in run(self.repo, "for-each-ref",
                             "--format=%(refname)", "refs/stash*").splitlines()
            if ln.strip()
        ]
        self.assertEqual(len(listed), 2)
        self.assertEqual(len(via_for_each_ref), 1)


class TestDeferralIsRecorded(StashRepoTestCase):
    """Dropping the namespace silently would be a worse bug than the one fixed."""

    def test_no_stashes_means_no_deferral_record(self):
        self.assertIsNone(r.stash_deferral())

    def test_stashes_produce_a_deferral_naming_the_owning_tool(self):
        self.make_stash_with_untracked("first")
        write(self.repo, "app.py", "X = 3\n")
        run(self.repo, "stash", "push", "-q", "-m", "second")

        deferral = r.stash_deferral()
        self.assertIsNotNone(deferral)
        self.assertEqual(deferral["count"], 2)
        self.assertEqual(deferral["namespace"], "refs/stash")
        self.assertEqual(deferral["owner"], "tools/reconcile_stashes.py")
        self.assertIn("third parent", deferral["reason"])

    def test_count_stashes_matches_the_reflog(self):
        self.assertEqual(r.count_stashes(), 0)
        self.make_stash_with_untracked("only")
        self.assertEqual(r.count_stashes(), 1)


if __name__ == "__main__":
    unittest.main()
