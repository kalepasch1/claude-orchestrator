"""Tests for repo_lock holder diagnostics and the isolation-lock timeout knob.

Regression: "git-isolation blocked execution: repository isolation lock
unavailable" was the entire failure record for a blocked task. It named no
holder, no wait duration and no timeout, so it could not distinguish a
long-running merge-train rebase (wait) from a wedged holder (intervene), and the
task was retried into the same wall.
"""

import importlib
import os
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


#: Safety net only. The holder is released by the parent writing a file, not by
#: this; it exists so a wedged test cannot leave a child holding a lock forever.
_HOLDER_MAX_WAIT_S = 60

#: The child's whole job, run in a FRESH interpreter.
#:
#: This used to be a multiprocessing.Process targeting a module-level function, and
#: it failed for a reason worth writing down: macOS defaults to the SPAWN start
#: method, and spawn pickles the target BY MODULE PATH. Run on its own, pytest
#: imports this file as top-level `test_repo_lock_holder` and the child can import it
#: back. Run alongside other files, pytest names the module
#: `runner.test_repo_lock_holder`, and the child dies with
#:
#:     ModuleNotFoundError: No module named 'runner.test_repo_lock_holder';
#:     'runner' is not a package
#:
#: before it ever takes the lock. The parent then waited ten seconds for a `ready`
#: that was never coming. Passing alone and failing in the full run is the signature,
#: and it had nothing to do with the locking code or with timing.
#:
#: A plain subprocess has no pickling and no import of the test module at all, so it
#: behaves the same under every start method and every collection layout.
_HOLDER_SCRIPT = """
import os, sys, time
os.environ["ORCH_REPO_LOCK_DIR"] = sys.argv[1]
sys.path.insert(0, sys.argv[2])
import repo_lock as rl
with rl.hold(sys.argv[3], purpose=sys.argv[4]) as ok:
    assert ok, "holder could not take the lock"
    with open(sys.argv[5], "w") as fh:
        fh.write(str(os.getpid()))
    deadline = time.time() + float(sys.argv[7])
    while not os.path.exists(sys.argv[6]) and time.time() < deadline:
        time.sleep(0.02)
"""


def _start_holder(lock_dir, repo, purpose, ready_path, release_path):
    """Take the repo lock in another process and hold it until RELEASE_PATH appears."""
    return subprocess.Popen(
        [sys.executable, "-c", _HOLDER_SCRIPT, lock_dir,
         os.path.dirname(os.path.abspath(__file__)), repo, purpose,
         ready_path, release_path, str(_HOLDER_MAX_WAIT_S)])


def _wait_for(path, timeout):
    """True once PATH exists. The handshake, with no wall-clock assumption in it."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(path):
            return True
        time.sleep(0.02)
    return os.path.exists(path)


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
        ready_path = os.path.join(self.dir, "holder.ready")
        release_path = os.path.join(self.dir, "holder.release")
        proc = _start_holder(self.dir, self.repo,
                             "ensure_task_worktree:other-slug", ready_path, release_path)
        try:
            self.assertTrue(_wait_for(ready_path, 30),
                            "holder process never acquired the lock")
            # The holder keeps the lock until the release file below, so nothing here
            # races a sleep: it is genuinely held for every assertion in this block.
            with self.rl.hold(self.repo, timeout=1) as ok:
                self.assertFalse(ok, "waiter should not have acquired a held lock")
            described = self.rl.describe_holder(self.repo)
            self.assertIn(str(proc.pid), described)
            self.assertIn("other-slug", described)
        finally:
            with open(release_path, "w") as fh:
                fh.write("go")
            proc.wait(timeout=30)

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
