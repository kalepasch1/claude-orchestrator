"""Tests for repo_lock holder diagnostics and the isolation-lock timeout knob.

Regression: "git-isolation blocked execution: repository isolation lock
unavailable" was the entire failure record for a blocked task. It named no
holder, no wait duration and no timeout, so it could not distinguish a
long-running merge-train rebase (wait) from a wedged holder (intervene), and the
task was retried into the same wall.
"""

import importlib
import multiprocessing
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _hold_for(lock_dir, repo, seconds, ready, purpose):
    os.environ["ORCH_REPO_LOCK_DIR"] = lock_dir
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import repo_lock as rl
    importlib.reload(rl)
    with rl.hold(repo, purpose=purpose) as ok:
        assert ok
        ready.set()
        time.sleep(seconds)


class HolderTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="repo-lock-test-")
        os.environ["ORCH_REPO_LOCK_DIR"] = self.dir
        import repo_lock
        self.rl = importlib.reload(repo_lock)
        self.repo = "/tmp/some/repo"

    def tearDown(self):
        os.environ.pop("ORCH_REPO_LOCK_DIR", None)

    def test_no_lock_file_describes_nothing(self):
        self.assertEqual(self.rl.describe_holder("/never/locked"), "")

    def test_holder_is_recorded_with_pid_and_purpose(self):
        with self.rl.hold(self.repo, purpose="merge_train:rebase") as ok:
            self.assertTrue(ok)
        described = self.rl.describe_holder(self.repo)
        self.assertIn(str(os.getpid()), described)
        self.assertIn("merge_train:rebase", described)
        self.assertIn("alive", described)

    def test_describe_holder_is_fail_soft_on_garbage(self):
        with open(self.rl._lock_path(self.repo), "w") as fh:
            fh.write("not json at all")
        self.assertEqual(self.rl.describe_holder(self.repo), "")

    def test_timeout_yields_false_and_names_the_other_holder(self):
        """The exact blocked-task shape: a second waiter times out."""
        ready = multiprocessing.Event()
        proc = multiprocessing.Process(
            target=_hold_for,
            args=(self.dir, self.repo, 3.0, ready, "ensure_task_worktree:other-slug"))
        proc.start()
        try:
            self.assertTrue(ready.wait(10), "holder process never acquired the lock")
            with self.rl.hold(self.repo, timeout=1) as ok:
                self.assertFalse(ok, "waiter should not have acquired a held lock")
            described = self.rl.describe_holder(self.repo)
            self.assertIn(str(proc.pid), described)
            self.assertIn("other-slug", described)
        finally:
            proc.join(10)

    def test_lock_is_reusable_after_release(self):
        with self.rl.hold(self.repo, timeout=5) as first:
            self.assertTrue(first)
        with self.rl.hold(self.repo, timeout=5) as second:
            self.assertTrue(second)


class TimeoutKnobTests(unittest.TestCase):
    def _reload(self, value):
        if value is None:
            os.environ.pop("ORCH_ISOLATION_LOCK_TIMEOUT", None)
        else:
            os.environ["ORCH_ISOLATION_LOCK_TIMEOUT"] = value
        import worktree_isolation
        return importlib.reload(worktree_isolation)

    def tearDown(self):
        self._reload(None)

    def test_default_is_the_previous_inline_value(self):
        self.assertEqual(self._reload(None).ISOLATION_LOCK_TIMEOUT, 120)

    def test_env_override_applies(self):
        self.assertEqual(self._reload("300").ISOLATION_LOCK_TIMEOUT, 300)

    def test_garbage_and_nonpositive_fall_back_to_the_default(self):
        for bad in ("", "abc", "0", "-5"):
            self.assertEqual(self._reload(bad).ISOLATION_LOCK_TIMEOUT, 120, bad)


if __name__ == "__main__":
    unittest.main()
