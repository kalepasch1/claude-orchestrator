"""Tests for the bridge-artifact side of the worktree-evidence reconciler.

The failure these guard against is expensive and quiet. A ChatGPT-bridge patch
that was PUBLISHED as a branch but never merged looks, to every check the
reconciler used to run, exactly like a patch that was silently lost: absent
from the default branch, and still applying cleanly. It therefore got
classified RECOVERABLE_VALUE and a recovery task was queued to re-apply work
that already existed on origin — a duplicate branch for the same change.

Observed live on
_applied/20260812-020326--...-operator-output-truth-session-fabric-20260812.patch,
whose branch chatgpt/operator-output-truth-session-fabric-20260812-08120203 was
sitting unmerged on origin with byte-identical content.
"""
import os
import subprocess
import tempfile
import unittest

import reconcile_worktree_evidence as rwe


def run(repo, *args):
    return subprocess.run(("git", "-C", repo) + args,
                          capture_output=True, text=True, check=True).stdout


class PublishedBridgeBranchTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = self._tmp.name
        # A bare "origin" plus a clone, so `git ls-remote origin` is real.
        self.origin = os.path.join(root, "origin.git")
        self.repo = os.path.join(root, "clone")
        self.dropbox = os.path.join(root, "dropbox")
        os.makedirs(self.dropbox)
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", self.origin],
                       check=True, capture_output=True)
        subprocess.run(["git", "clone", "-q", self.origin, self.repo],
                       check=True, capture_output=True)
        with open(os.path.join(self.repo, "a.txt"), "w") as fh:
            fh.write("base\n")
        run(self.repo, "add", "a.txt")
        subprocess.run(
            ["git", "-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@t",
             "commit", "-q", "-m", "base"], check=True, capture_output=True)
        run(self.repo, "push", "-q", "origin", "HEAD:main")

    def tearDown(self):
        self._tmp.cleanup()

    def artifact(self, name="p.patch", sidecar=None, suffix=".result.txt"):
        path = os.path.join(self.dropbox, name)
        with open(path, "w") as fh:
            fh.write("diff --git a/a.txt b/a.txt\n")
        if sidecar is not None:
            with open(path + suffix, "w") as fh:
                fh.write(sidecar)
        return path

    def publish(self, branch):
        run(self.repo, "push", "-q", "origin", "HEAD:refs/heads/" + branch)

    def test_finds_the_branch_the_bridge_recorded(self):
        self.publish("chatgpt/session-fabric-20260812-08120203")
        path = self.artifact(sidecar=(
            "[chatgpt-bridge] repo=claude-orchestrator root=/x "
            "branch=chatgpt/session-fabric-20260812-08120203\n"))
        self.assertEqual(
            rwe.published_bridge_branch(path, self.repo),
            "chatgpt/session-fabric-20260812-08120203")

    def test_a_recorded_branch_that_is_not_on_origin_does_not_count(self):
        """A sidecar is a claim. Only origin is evidence."""
        path = self.artifact(sidecar="[chatgpt-bridge] branch=chatgpt/never-pushed\n")
        self.assertEqual(rwe.published_bridge_branch(path, self.repo), "")

    def test_no_sidecar_means_no_published_branch(self):
        self.assertEqual(
            rwe.published_bridge_branch(self.artifact(), self.repo), "")

    def test_the_error_sidecar_is_read_too(self):
        """A bridge run can fail after pushing; the branch still exists."""
        self.publish("chatgpt/pushed-then-failed")
        path = self.artifact(
            sidecar="[chatgpt-bridge] branch=chatgpt/pushed-then-failed\n",
            suffix=".error.txt")
        self.assertEqual(rwe.published_bridge_branch(path, self.repo),
                         "chatgpt/pushed-then-failed")

    def test_a_sidecar_with_no_branch_token_is_not_a_crash(self):
        path = self.artifact(sidecar="[chatgpt-bridge] repo=x root=/y\n")
        self.assertEqual(rwe.published_bridge_branch(path, self.repo), "")

    def test_an_empty_branch_value_is_ignored(self):
        path = self.artifact(sidecar="[chatgpt-bridge] branch=\n")
        self.assertEqual(rwe.published_bridge_branch(path, self.repo), "")

    def test_an_unreadable_sidecar_is_survived(self):
        """Fail-soft: a bad sidecar must not wedge a whole reconcile run."""
        path = self.artifact(sidecar="[chatgpt-bridge] branch=chatgpt/x\n")
        os.chmod(path + ".result.txt", 0o000)
        try:
            self.assertEqual(rwe.published_bridge_branch(path, self.repo), "")
        finally:
            os.chmod(path + ".result.txt", 0o600)


if __name__ == "__main__":
    unittest.main()
