"""Fleet branch-share regression: a branch created on Mac A must be visible to the
sweeper/merge-train on Mac B once pushed to origin (root cause of the
recover-missing-branch churn: two Macs, one queue, local-only branches)."""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import integration_sweeper
import merge_train


def _git(cwd, *args):
    return subprocess.run(["git", "-C", cwd] + list(args), capture_output=True, text=True)


class BranchShareTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.origin = os.path.join(root, "origin.git")
        subprocess.run(["git", "init", "--bare", self.origin], capture_output=True)
        self.mac_a = os.path.join(root, "mac_a")
        self.mac_b = os.path.join(root, "mac_b")
        subprocess.run(["git", "clone", self.origin, self.mac_a], capture_output=True)
        for repo in (self.mac_a,):
            _git(repo, "config", "user.email", "t@t")
            _git(repo, "config", "user.name", "t")
        open(os.path.join(self.mac_a, "f.txt"), "w").write("base\n")
        _git(self.mac_a, "add", "."); _git(self.mac_a, "commit", "-m", "base")
        _git(self.mac_a, "branch", "-M", "main")
        _git(self.mac_a, "push", "-u", "origin", "main")
        subprocess.run(["git", "clone", self.origin, self.mac_b], capture_output=True)
        _git(self.mac_b, "config", "user.email", "t@t")
        _git(self.mac_b, "config", "user.name", "t")
        # Mac A does agent work and pushes the agent branch (the runner.py branch-share step)
        _git(self.mac_a, "checkout", "-b", "agent/test-slug")
        open(os.path.join(self.mac_a, "g.txt"), "w").write("work\n")
        _git(self.mac_a, "add", "."); _git(self.mac_a, "commit", "-m", "agent work")
        _git(self.mac_a, "push", "-u", "origin", "agent/test-slug")
        integration_sweeper._FETCHED_AGENT_REFS.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def test_local_only_check_misses_remote_branch(self):
        # documents the old bug: purely local check on Mac B cannot see Mac A's branch
        self.assertFalse(integration_sweeper._branch_exists(self.mac_b, "agent/test-slug"))

    def test_sweeper_sees_remote_branch(self):
        self.assertTrue(integration_sweeper._branch_exists_anywhere(self.mac_b, "agent/test-slug"))

    def test_sweeper_still_false_for_truly_missing(self):
        self.assertFalse(integration_sweeper._branch_exists_anywhere(self.mac_b, "agent/nope"))

    def test_merge_train_materializes_local_ref(self):
        self.assertTrue(merge_train._materialize_branch(self.mac_b, "agent/test-slug"))
        self.assertEqual(_git(self.mac_b, "rev-parse", "--verify", "agent/test-slug").returncode, 0)

    def test_materialize_false_when_absent_everywhere(self):
        self.assertFalse(merge_train._materialize_branch(self.mac_b, "agent/absent"))

    def test_no_repo_is_fail_soft(self):
        self.assertFalse(integration_sweeper._branch_exists_anywhere("", "agent/x"))
        self.assertFalse(integration_sweeper._branch_exists_anywhere("/nonexistent/path", "agent/x"))


if __name__ == "__main__":
    unittest.main()
