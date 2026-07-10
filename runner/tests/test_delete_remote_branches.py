"""Acceptance tests for scripts/delete_remote_branches.py.

Sets up a bare-remote + cloned-local pair, pushes deletable branches, then:
  1. Dry-run: verifies output lists branches without deleting them.
  2. Actual run: verifies branches are removed from the remote and protected
     branches survive.
"""
import os
import subprocess
import sys
import tempfile
import unittest

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts")
SCRIPT = os.path.join(SCRIPTS_DIR, "delete_remote_branches.py")


def _git(cwd, *args):
    return subprocess.run(["git", "-C", cwd] + list(args), capture_output=True, text=True)


def _remote_branches(origin_bare):
    result = _git(origin_bare, "branch")
    return {b.strip().lstrip("* ") for b in result.stdout.splitlines() if b.strip()}


def _run_script(repo, branches, dry_run=False):
    cmd = [sys.executable, SCRIPT, "--repo", repo, "--branches", ",".join(branches)]
    if dry_run:
        cmd.append("--dry-run")
    return subprocess.run(cmd, capture_output=True, text=True)


class SetupMixin:
    def _setup_repos(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.origin = os.path.join(root, "origin.git")
        subprocess.run(["git", "init", "--bare", self.origin], capture_output=True)
        self.local = os.path.join(root, "local")
        subprocess.run(["git", "clone", self.origin, self.local], capture_output=True)
        _git(self.local, "config", "user.email", "t@t")
        _git(self.local, "config", "user.name", "t")
        # create initial commit on main
        open(os.path.join(self.local, "README"), "w").write("base\n")
        _git(self.local, "add", ".")
        _git(self.local, "commit", "-m", "base")
        _git(self.local, "branch", "-M", "main")
        _git(self.local, "push", "-u", "origin", "main")
        # push deletable feature branches
        for branch in ("feature-a", "feature-b", "stale-branch"):
            _git(self.local, "checkout", "-b", branch)
            open(os.path.join(self.local, f"{branch}.txt"), "w").write(branch)
            _git(self.local, "add", ".")
            _git(self.local, "commit", "-m", branch)
            _git(self.local, "push", "-u", "origin", branch)
            _git(self.local, "checkout", "main")
        # push a protected branch (develop) to verify it stays
        _git(self.local, "checkout", "-b", "develop")
        open(os.path.join(self.local, "dev.txt"), "w").write("dev\n")
        _git(self.local, "add", ".")
        _git(self.local, "commit", "-m", "dev")
        _git(self.local, "push", "-u", "origin", "develop")
        _git(self.local, "checkout", "main")


class TestDryRunOutput(SetupMixin, unittest.TestCase):
    def setUp(self):
        self._setup_repos()

    def tearDown(self):
        self.tmp.cleanup()

    def test_dry_run_lists_branches_without_deleting(self):
        branches_before = _remote_branches(self.origin)
        result = _run_script(self.local, ["feature-a", "feature-b"], dry_run=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("feature-a", result.stdout)
        self.assertIn("feature-b", result.stdout)
        self.assertIn("dry-run", result.stdout)
        # remote must be unchanged
        branches_after = _remote_branches(self.origin)
        self.assertEqual(branches_before, branches_after)

    def test_dry_run_skips_protected_without_deleting(self):
        result = _run_script(self.local, ["main", "develop", "feature-a"], dry_run=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("protected", result.stdout)
        self.assertIn("main", result.stdout)
        self.assertIn("develop", result.stdout)
        # feature-a would be deleted but remote is untouched
        self.assertIn("feature-a", result.stdout)
        self.assertIn("dry-run", result.stdout)
        self.assertIn("main", _remote_branches(self.origin))
        self.assertIn("develop", _remote_branches(self.origin))
        self.assertIn("feature-a", _remote_branches(self.origin))


class TestActualDeletionAndProtection(SetupMixin, unittest.TestCase):
    def setUp(self):
        self._setup_repos()

    def tearDown(self):
        self.tmp.cleanup()

    def test_deletes_specified_branches(self):
        result = _run_script(self.local, ["feature-a", "feature-b"], dry_run=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        remaining = _remote_branches(self.origin)
        self.assertNotIn("feature-a", remaining)
        self.assertNotIn("feature-b", remaining)

    def test_untargeted_branch_survives(self):
        _run_script(self.local, ["feature-a", "feature-b"], dry_run=False)
        self.assertIn("stale-branch", _remote_branches(self.origin))

    def test_protected_branches_not_deleted(self):
        result = _run_script(self.local, ["main", "develop", "feature-a"], dry_run=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        remaining = _remote_branches(self.origin)
        self.assertIn("main", remaining)
        self.assertIn("develop", remaining)
        self.assertNotIn("feature-a", remaining)
        self.assertIn("protected", result.stdout)

    def test_deletion_output_labels(self):
        result = _run_script(self.local, ["stale-branch"], dry_run=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("deleted", result.stdout)
        self.assertIn("stale-branch", result.stdout)


if __name__ == "__main__":
    unittest.main()
