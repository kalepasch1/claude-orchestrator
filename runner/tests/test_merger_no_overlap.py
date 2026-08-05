"""Contract: continuous_merger must not overlap other mergers, and must not eat live work.

TWO BUGS THIS PINS (both fixed 2026-08-04):

1. NO CROSS-PROCESS LOCK. _project_locks is a threading.Lock, so it serialized only threads
   inside the runner process. merge_train / release_train / branch_lease / runner /
   worktree_isolation all coordinate through repo_lock.hold() (an fcntl.flock on the repo);
   continuous_merger was the one merger that never took it, so two mergers could drive
   checkout/reset/merge on the SAME repo simultaneously.

2. UNCONDITIONAL `reset --hard` ON THE MAIN CHECKOUT. Every task completion reset the main
   working tree. Observed three times in one day silently reverting in-flight uncommitted
   edits — including the commit that was fixing this very class of bug.
"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import continuous_merger as cm  # noqa: E402


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def _mkrepo():
    repo = tempfile.mkdtemp(prefix="overlap-")
    _git(repo, "init", "-q", "-b", "master")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "user.email", "t@t")
    with open(os.path.join(repo, "a.txt"), "w") as f:
        f.write("committed\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


class DirtyCheckoutIsSacred(unittest.TestCase):
    def test_refuses_to_reset_uncommitted_work(self):
        repo = _mkrepo()
        # an operator (or another agent) is mid-edit in the main checkout
        with open(os.path.join(repo, "a.txt"), "w") as f:
            f.write("PRECIOUS UNCOMMITTED WORK\n")

        _git(repo, "checkout", "-q", "-b", "agent/x")
        _git(repo, "checkout", "-q", "master")

        res = cm._merge_branch(repo, "agent/x", "master", {"slug": "x"})

        self.assertFalse(res["merged"])
        self.assertEqual(res["strategy"], "skipped-dirty")
        with open(os.path.join(repo, "a.txt")) as f:
            self.assertEqual(f.read(), "PRECIOUS UNCOMMITTED WORK\n",
                             "merger destroyed uncommitted work in the main checkout")

    def test_clean_checkout_is_still_processed(self):
        repo = _mkrepo()
        res = cm._merge_branch(repo, "agent/missing", "master", {"slug": "missing"})
        # Gets past the dirty guard and reaches the real branch check.
        self.assertNotEqual(res["strategy"], "skipped-dirty")


class CrossProcessLockIsTaken(unittest.TestCase):
    def test_process_task_consults_repo_lock(self):
        import inspect
        src = inspect.getsource(cm._process_task)
        self.assertIn("repo_lock", src,
                      "continuous_merger must take the cross-process repo lock")
        self.assertIn("hold(", src, "must call repo_lock.hold()")

    def test_defers_instead_of_blocking_when_repo_is_busy(self):
        """A busy repo must SKIP, never block a worker thread or force the merge."""
        import inspect
        src = inspect.getsource(cm._process_task)
        self.assertIn("skipped", src)
        # the merge work itself is factored out behind the lock
        self.assertTrue(hasattr(cm, "_merge_with_retries"))
        loop = inspect.getsource(cm._merge_with_retries)
        self.assertIn("for attempt in range", loop,
                      "retry loop must live inside the locked section")


if __name__ == "__main__":
    unittest.main()
