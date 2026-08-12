"""Recovery must consult the durability archive before giving up.

branch_durability.safe_delete() archives a branch tip under refs/archive/<branch>/<epoch>
(and mirrors it to origin) precisely so the commits can be restored. branch_recovery never
looked there, so a branch deleted by approval_merge's conflict-redo path came back
"unrecoverable" and turned into a manual recover-missing-branch task -- re-generating code
that was sitting in the object store the whole time.

These run against real temporary git repos rather than mocks: the whole point is that the
ref plumbing behaves, and a mocked `git` would prove nothing about that.
"""
import os
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import branch_recovery


def _run(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def _init_repo(path):
    _run(path, "init", "-q", "-b", "main")
    _run(path, "config", "user.email", "test@example.com")
    _run(path, "config", "user.name", "test")
    with open(os.path.join(path, "f.txt"), "w") as fh:
        fh.write("base\n")
    _run(path, "add", "-A")
    _run(path, "commit", "-q", "-m", "base")


def _commit_on(repo, branch, text):
    _run(repo, "checkout", "-q", "-b", branch)
    with open(os.path.join(repo, "f.txt"), "w") as fh:
        fh.write(text)
    _run(repo, "add", "-A")
    _run(repo, "commit", "-q", "-m", text)
    sha = _run(repo, "rev-parse", "HEAD").stdout.strip()
    _run(repo, "checkout", "-q", "main")
    return sha


class ArchiveRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="br-arch-")
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        _init_repo(self.repo)
        # No origin in these fixtures; the archive fetch must degrade quietly.
        os.environ["ORCH_BRANCH_RECOVERY_FETCH_ARCHIVE"] = "false"

    def tearDown(self):
        os.environ.pop("ORCH_BRANCH_RECOVERY_FETCH_ARCHIVE", None)
        subprocess.run(["rm", "-rf", self.tmp], capture_output=True)

    def _archive_and_delete(self, branch, sha, epoch=None):
        epoch = epoch or int(time.time())
        _run(self.repo, "update-ref", f"refs/archive/{branch}/{epoch}", sha)
        _run(self.repo, "branch", "-D", branch)

    def test_archived_branch_is_restored_not_declared_unrecoverable(self):
        sha = _commit_on(self.repo, "agent/x", "work that must survive")
        self._archive_and_delete("agent/x", sha)
        self.assertFalse(branch_recovery._branch_exists_local(self.repo, "agent/x"))

        result = branch_recovery.recover_branch(self.repo, "agent/x")

        self.assertEqual(result["status"], "recovered", result)
        self.assertIn("archive", result["action_taken"])
        # Exact restore: the original commit, not a regenerated equivalent.
        restored = _run(self.repo, "rev-parse", "agent/x").stdout.strip()
        self.assertEqual(restored, sha)

    def test_newest_archive_wins(self):
        old_sha = _commit_on(self.repo, "agent/y", "first attempt")
        self._archive_and_delete("agent/y", old_sha, epoch=1000)
        new_sha = _commit_on(self.repo, "agent/y", "second attempt")
        self._archive_and_delete("agent/y", new_sha, epoch=2000)

        branch_recovery.recover_branch(self.repo, "agent/y")

        restored = _run(self.repo, "rev-parse", "agent/y").stdout.strip()
        self.assertEqual(restored, new_sha)

    def test_archive_refs_sort_numerically_not_lexically(self):
        # "1000000000" < "999999999" lexically but not numerically; a string sort would
        # pick the older archive and silently restore stale work.
        sha_a = _commit_on(self.repo, "agent/z", "older")
        self._archive_and_delete("agent/z", sha_a, epoch=999999999)
        sha_b = _commit_on(self.repo, "agent/z", "newer")
        self._archive_and_delete("agent/z", sha_b, epoch=1000000000)

        refs = branch_recovery._archive_refs(self.repo, "agent/z")

        self.assertEqual(refs[0][2], sha_b)

    def test_no_archive_ref_reports_cleanly(self):
        ok, detail = branch_recovery._archive_recover(self.repo, "agent/never-existed")
        self.assertFalse(ok)
        self.assertEqual(detail, "no archive ref")

    def test_stat_counter_increments(self):
        before = branch_recovery.stats().get("recover_archive", 0)
        sha = _commit_on(self.repo, "agent/counted", "w")
        self._archive_and_delete("agent/counted", sha)
        branch_recovery.recover_branch(self.repo, "agent/counted")
        self.assertEqual(branch_recovery.stats()["recover_archive"], before + 1)

    def test_archive_is_tried_before_reflog(self):
        # Both sources could serve this branch; the archive is the exact record, so it must
        # win. Asserted via the action_taken string rather than call order.
        sha = _commit_on(self.repo, "agent/both", "w")
        self._archive_and_delete("agent/both", sha)
        result = branch_recovery.recover_branch(self.repo, "agent/both")
        self.assertIn("archive", result["action_taken"])
        self.assertNotIn("reflog", result["action_taken"])

    def test_dangling_archive_ref_does_not_create_a_broken_branch(self):
        # A ref whose object is gone must be skipped, not turned into a branch pointing
        # at nothing.
        _run(self.repo, "update-ref", "refs/archive/agent/dangling/1000", "0" * 40)
        ok, _detail = branch_recovery._archive_recover(self.repo, "agent/dangling")
        self.assertFalse(ok)
        self.assertFalse(branch_recovery._branch_exists_local(self.repo, "agent/dangling"))

    def test_bad_repo_path_is_fail_soft(self):
        result = branch_recovery.recover_branch("/nonexistent/path", "agent/x")
        self.assertEqual(result["status"], "unrecoverable")


if __name__ == "__main__":
    unittest.main()
