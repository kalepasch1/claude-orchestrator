"""Tests for unregistered-checkout classification.

The failure these guard against: the scan counted UNTRACKED files as
uncommitted work at risk, so /Users/kpasch/Documents/_Trojun_archived was
reported RECOVERABLE_VALUE with "223 uncommitted paths" and queued as "the
single largest pocket of unreviewed local state found in the sweep".

222 of those 223 were untracked. 169 were byte-identical copies of files
already on origin/master at a shifted path (web/supabase/migrations/ rather
than supabase/migrations/), and the rest belonged to a different product built
in a clone of the orchestrator repo. Nothing was at risk; nothing was landable.

A tracked modification overwrites content the base already has, so losing the
checkout loses it for good. An untracked file may be anything at all.
"""
import os
import subprocess
import tempfile
import unittest

import reconcile_unregistered_repos as r


def run(repo, *args):
    return subprocess.run(("git", "-C", repo) + args,
                          capture_output=True, text=True, check=True).stdout


def write(repo, rel, body):
    path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(body)


def commit(repo, message):
    run(repo, "add", "-A")
    subprocess.run(
        ["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t",
         "commit", "-q", "--no-verify", "-m", message],
        check=True, capture_output=True, text=True)


class ClassifyTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = self._tmp.name
        self.origin = os.path.join(root, "origin.git")
        self.repo = os.path.join(root, "checkout")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", self.origin],
                       check=True, capture_output=True)
        subprocess.run(["git", "clone", "-q", self.origin, self.repo],
                       check=True, capture_output=True)
        write(self.repo, "src/app.py", "def a():\n    return 1\n")
        commit(self.repo, "base")
        run(self.repo, "push", "-q", "origin", "HEAD:main")

    def tearDown(self):
        self._tmp.cleanup()

    def classify(self, known_origin=False):
        item = r.Item(ref=self.repo)
        origins = {r.normalise_remote(self.origin)} if known_origin else set()
        r.classify(item, self.repo, origins, set())
        return item

    def test_untracked_only_is_triage_not_recovery(self):
        """The _Trojun_archived shape: many untracked, nothing tracked-dirty."""
        for i in range(5):
            write(self.repo, f"extra/file{i}.sql", f"-- {i}\n")
        item = self.classify()
        self.assertEqual(item.classification, "UNTRACKED_NEEDS_TRIAGE")
        self.assertEqual(item.untracked_paths, 5)
        self.assertEqual(item.tracked_dirty, 0)
        self.assertIn("before queueing any recovery", item.disposition)

    def test_a_tracked_modification_is_still_recoverable_value(self):
        """The guard must not blunt the case it protects."""
        write(self.repo, "src/app.py", "def a():\n    return 2\n")
        item = self.classify()
        self.assertEqual(item.classification, "RECOVERABLE_VALUE")
        self.assertEqual(item.tracked_dirty, 1)
        self.assertIn("1 tracked modification(s)", item.disposition)

    def test_one_tracked_edit_among_many_untracked_is_recoverable_value(self):
        """A single real edit keeps the checkout actionable."""
        write(self.repo, "src/app.py", "def a():\n    return 2\n")
        for i in range(20):
            write(self.repo, f"extra/file{i}.sql", f"-- {i}\n")
        item = self.classify()
        self.assertEqual(item.classification, "RECOVERABLE_VALUE")
        self.assertEqual(item.tracked_dirty, 1)
        self.assertEqual(item.untracked_paths, 20)
        # Both counts are reported, so the operator can see the split that the
        # single "223 dirty paths" number hid.
        self.assertIn("1 tracked modification(s)", item.disposition)
        self.assertIn("20 untracked path(s)", item.disposition)

    def test_untracked_only_but_with_unpushed_commits_stays_recoverable(self):
        run(self.repo, "checkout", "-q", "-b", "wip")
        write(self.repo, "src/new.py", "def b():\n    return 2\n")
        commit(self.repo, "unpushed work")
        write(self.repo, "extra/file.sql", "-- x\n")
        item = self.classify()
        self.assertEqual(item.classification, "RECOVERABLE_VALUE")

    def test_unpushed_commits_on_a_clean_tree_are_detected(self):
        """`--not` negates everything after it, so argument order is the bug.

        `rev-list --count --not --remotes <name>` excluded the BRANCH along
        with the remotes and returned 0 for every branch, so unpushed-work
        detection never fired once. A checkout holding real unpushed commits
        on a clean tree was classified ALREADY_PRESENT — silent loss, which is
        the single thing this scan exists to prevent.
        """
        run(self.repo, "checkout", "-q", "-b", "wip")
        write(self.repo, "src/new.py", "def b():\n    return 2\n")
        commit(self.repo, "unpushed work")
        item = self.classify(known_origin=True)
        self.assertEqual(item.unpushed_branches, ["wip(+1)"])
        self.assertEqual(item.classification, "ACTIVE_IN_ANOTHER_TASK")

    def test_a_pushed_branch_is_not_reported_as_unpushed(self):
        """The fix must not invert into false positives."""
        run(self.repo, "checkout", "-q", "-b", "shipped")
        write(self.repo, "src/new.py", "def b():\n    return 2\n")
        commit(self.repo, "work")
        run(self.repo, "push", "-q", "origin", "HEAD:shipped")
        item = self.classify(known_origin=True)
        self.assertEqual(item.unpushed_branches, [])
        self.assertEqual(item.classification, "ALREADY_PRESENT")

    def test_a_clean_checkout_is_already_present(self):
        item = self.classify(known_origin=True)
        self.assertEqual(item.classification, "ALREADY_PRESENT")

    def test_the_split_is_reported_in_files(self):
        write(self.repo, "src/app.py", "def a():\n    return 2\n")
        write(self.repo, "extra/x.sql", "-- x\n")
        item = self.classify()
        joined = " ".join(item.files)
        self.assertIn("1 tracked modification(s)", joined)
        self.assertIn("1 untracked path(s)", joined)

    def test_classification_is_read_only(self):
        """Classifying must never mutate the checkout it inspects."""
        write(self.repo, "extra/x.sql", "-- x\n")
        before = run(self.repo, "status", "--porcelain")
        head = run(self.repo, "rev-parse", "HEAD")
        self.classify()
        self.assertEqual(run(self.repo, "status", "--porcelain"), before)
        self.assertEqual(run(self.repo, "rev-parse", "HEAD"), head)


if __name__ == "__main__":
    unittest.main()
