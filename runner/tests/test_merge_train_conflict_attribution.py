"""The merge train must blame the branch that owns the conflicting hunk.

`git rebase base branch` replays every commit reachable from the branch and not
from base. When a branch merged other agent branches in, that includes their
commits — and a conflict raised while replaying one of THOSE is reported
against whichever branch is currently being rebased.

The train then rebuilt that task and tried again. Three dropbox tasks reached
attempts 61, 36 and 134 on one identical error:

    train: still conflicts after 4 redos - needs manual rebase.
    Conflicting files: packages/darwin-kernel/src/passport/passport.ts.

At least one of them (agent commit ae4f5f7d64) touches exactly one file,
tests/test_lease_night_config_divergence.py. It could never have resolved a
passport.ts conflict; 14 other unmerged agent branches modify that file. Each
redo burned a full agent run to arrive back at the same message.
"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run(repo, *args):
    return subprocess.run(("git", "-C", repo) + args,
                          capture_output=True, text=True, check=True).stdout


def write(repo, rel, body):
    path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(path) or repo, exist_ok=True)
    with open(path, "w") as fh:
        fh.write(body)
    run(repo, "add", rel)


def commit(repo, message):
    subprocess.run(
        ["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t",
         "commit", "-q", "--no-verify", "-m", message],
        check=True, capture_output=True, text=True)


class ConflictAttributionTestCase(unittest.TestCase):
    """Exercises the pure helpers; no DB, no network, no train run."""

    @classmethod
    def setUpClass(cls):
        import merge_train
        cls.mt = merge_train

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = self._tmp.name
        run(self.repo, "init", "-q", "-b", "master")
        write(self.repo, "passport.ts", "export const a = 'base'\n")
        write(self.repo, "unrelated.py", "x = 1\n")
        commit(self.repo, "base")

    def tearDown(self):
        self._tmp.cleanup()

    def test_own_paths_are_the_branch_contribution(self):
        run(self.repo, "checkout", "-q", "-b", "agent/mine")
        write(self.repo, "mine.py", "y = 2\n")
        commit(self.repo, "my work")
        run(self.repo, "checkout", "-q", "master")
        self.assertEqual(
            self.mt._branch_own_paths(self.repo, "agent/mine", "master"),
            {"mine.py"})

    def test_a_conflict_in_a_file_the_branch_never_touched_is_foreign(self):
        """The passport.ts shape, reduced."""
        run(self.repo, "checkout", "-q", "-b", "agent/innocent")
        write(self.repo, "only_mine.py", "y = 2\n")
        commit(self.repo, "touches one unrelated file")
        run(self.repo, "checkout", "-q", "master")
        self.assertTrue(self.mt._conflict_is_foreign(
            self.repo, "agent/innocent", "master", "passport.ts"))

    def test_a_conflict_in_a_file_the_branch_owns_is_not_foreign(self):
        """The guard must not stop legitimate redos."""
        run(self.repo, "checkout", "-q", "-b", "agent/guilty")
        write(self.repo, "passport.ts", "export const a = 'branch'\n")
        commit(self.repo, "edits passport")
        run(self.repo, "checkout", "-q", "master")
        self.assertFalse(self.mt._conflict_is_foreign(
            self.repo, "agent/guilty", "master", "passport.ts"))

    def test_a_mixed_conflict_set_is_not_foreign(self):
        """One owned path is enough to make the redo worth attempting."""
        run(self.repo, "checkout", "-q", "-b", "agent/mixed")
        write(self.repo, "unrelated.py", "x = 2\n")
        commit(self.repo, "edits unrelated")
        run(self.repo, "checkout", "-q", "master")
        self.assertFalse(self.mt._conflict_is_foreign(
            self.repo, "agent/mixed", "master", "passport.ts\nunrelated.py"))

    def test_uncertain_attribution_falls_back_to_redo(self):
        """No detail, or an empty branch diff: redo is the cheaper mistake."""
        run(self.repo, "checkout", "-q", "-b", "agent/empty")
        run(self.repo, "checkout", "-q", "master")
        self.assertFalse(self.mt._conflict_is_foreign(
            self.repo, "agent/empty", "master", ""))
        self.assertFalse(self.mt._conflict_is_foreign(
            self.repo, "agent/empty", "master", "passport.ts"))
        self.assertFalse(self.mt._conflict_is_foreign(
            self.repo, "agent/missing-branch", "master", "passport.ts"))

    def test_owners_names_the_branches_that_really_modify_the_file(self):
        for name, path in (("agent/owner-a", "passport.ts"),
                           ("agent/owner-b", "passport.ts"),
                           ("agent/bystander", "unrelated.py")):
            run(self.repo, "checkout", "-q", "-b", name, "master")
            write(self.repo, path, f"// {name}\n")
            commit(self.repo, f"edit from {name}")
        run(self.repo, "checkout", "-q", "master")

        # _conflict_owners scans remote-tracking refs; this fixture has none, so
        # assert the underlying attribution it is built on instead.
        for name in ("agent/owner-a", "agent/owner-b"):
            self.assertIn("passport.ts",
                          self.mt._branch_own_paths(self.repo, name, "master"))
        self.assertNotIn("passport.ts",
                         self.mt._branch_own_paths(self.repo, "agent/bystander", "master"))


if __name__ == "__main__":
    unittest.main()
