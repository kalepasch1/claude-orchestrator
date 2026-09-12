#!/usr/bin/env python3
"""Tests for repo_lock.py — the per-repo mutex fixing the 2026-07-08 merge-stall race."""
import os
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import repo_lock


#: The holder's whole job, run in a FRESH interpreter via subprocess.
#:
#: This was a multiprocessing.Process targeting a module-level function, which on
#: macOS (spawn) means the child unpickles the target BY MODULE PATH and must import
#: `runner.tests.test_repo_lock` to do it. That import is not reliably available to
#: the child, because this very file puts `runner/` on sys.path -- and `runner/`
#: contains runner.py, so `import runner` resolves to the MODULE and shadows the
#: PACKAGE:
#:
#:     >>> sys.path.insert(0, "runner"); import runner
#:     runner/runner.py          # not a package -> runner.tests.* is unimportable
#:
#: Whether the child survives therefore depends on where `runner/` sits in sys.path
#: relative to the repo root, which depends on which test files were imported first,
#: which depends on what else is being collected. It works today. It is the exact
#: shape of "green alone, red together", and the identical failure took down
#: runner/test_repo_lock_holder.py — where it presented as "holder process never
#: acquired the lock", pointing at repo_lock rather than at the import.
#:
#: A subprocess pickles nothing and imports no test module, so none of that applies.
_HOLDER_SCRIPT = """
import os, sys, time
os.environ["ORCH_REPO_LOCK_DIR"] = sys.argv[1]
sys.path.insert(0, sys.argv[2])
import repo_lock as rl
with rl.hold(sys.argv[3]):
    with open(sys.argv[4], "a") as fh:
        fh.write("start %f\\n" % time.time())
    time.sleep(float(sys.argv[5]))
    with open(sys.argv[4], "a") as fh:
        fh.write("end %f\\n" % time.time())
"""


def _start_holder(lock_dir, repo, out_path, hold_seconds):
    """Hold REPO's lock in another process for HOLD_SECONDS, recording to OUT_PATH."""
    runner_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return subprocess.Popen(
        [sys.executable, "-c", _HOLDER_SCRIPT, lock_dir, runner_dir, repo,
         out_path, str(hold_seconds)])


def _wait_until_held(out_path, deadline_s=30.0):
    """Block until the holder subprocess has actually taken the lock.

    The contention tests used to do `holder.start(); time.sleep(0.1)` and assume
    the child had the lock by then. On macOS the default start method is spawn:
    the child is a fresh interpreter that re-imports the whole module graph
    before it reaches rl.hold(), which takes well over 100ms on a machine that
    is also running the rest of the suite. When it lost that race the parent
    acquired an uncontended lock and the assertions described nothing —
    test_no_timeout_blocks_until_acquired measured 0.0012s of "blocking" and
    failed in-suite while passing alone.

    _hold_and_record writes "start" the moment it holds the lock, so waiting for
    that line is a real handshake rather than a guess about scheduling.
    """
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        try:
            with open(out_path) as fh:
                if "start" in fh.read():
                    return True
        except FileNotFoundError:
            pass
        time.sleep(0.02)
    raise AssertionError(f"holder never acquired the lock within {deadline_s}s")


class TestRepoLock(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.lock_dir = self._tmp.name
        self._orig_env = os.environ.get("ORCH_REPO_LOCK_DIR")
        os.environ["ORCH_REPO_LOCK_DIR"] = self.lock_dir
        import importlib
        importlib.reload(repo_lock)

    def tearDown(self):
        if self._orig_env is None:
            os.environ.pop("ORCH_REPO_LOCK_DIR", None)
        else:
            os.environ["ORCH_REPO_LOCK_DIR"] = self._orig_env
        self._tmp.cleanup()

    def test_basic_acquire_release(self):
        with repo_lock.hold("/some/repo") as got:
            self.assertTrue(got)
        # lock file should exist and be reusable afterward
        with repo_lock.hold("/some/repo") as got2:
            self.assertTrue(got2)

    def test_different_repos_do_not_contend(self):
        # different repo paths hash to different lock files, so both should acquire
        # even if held "simultaneously" (sequential here since flock is per-process too,
        # but the important assertion is that they use distinct lock files)
        p1 = repo_lock._lock_path("/repo/a")
        p2 = repo_lock._lock_path("/repo/b")
        self.assertNotEqual(p1, p2)

    def test_same_repo_same_lock_path(self):
        self.assertEqual(repo_lock._lock_path("/repo/a"), repo_lock._lock_path("/repo/a"))

    def test_timeout_returns_false_when_contended(self):
        out_path = os.path.join(self.lock_dir, "out.txt")
        holder = _start_holder(self.lock_dir, "/contended/repo", out_path, 2.0)
        _wait_until_held(out_path)
        got_it = None
        with repo_lock.hold("/contended/repo", timeout=0.5) as got:
            got_it = got
        self.assertFalse(got_it, "second caller should time out while the first holds the lock")
        holder.wait(timeout=30)

    def test_sequential_after_release_succeeds(self):
        out_path = os.path.join(self.lock_dir, "out2.txt")
        holder = _start_holder(self.lock_dir, "/contended/repo2", out_path, 0.5)
        _wait_until_held(out_path)
        with repo_lock.hold("/contended/repo2", timeout=5) as got:
            self.assertTrue(got, "caller should acquire once the holder releases within the timeout")
        holder.wait(timeout=30)

    def test_no_timeout_blocks_until_acquired(self):
        out_path = os.path.join(self.lock_dir, "out3.txt")
        holder = _start_holder(self.lock_dir, "/contended/repo3", out_path, 1.0)
        # The clock starts only once the lock is demonstrably held, so `elapsed`
        # measures blocking rather than however long spawn happened to take. The
        # hold is 1.0s against a 0.3s floor, which leaves room for the handshake
        # poll without making the assertion depend on it.
        _wait_until_held(out_path)
        start = time.time()
        with repo_lock.hold("/contended/repo3") as got:
            elapsed = time.time() - start
            self.assertTrue(got)
            self.assertGreaterEqual(elapsed, 0.3, "blocking hold() should wait for the holder to release")
        holder.wait(timeout=30)

    def test_refuses_the_lock_when_dir_uncreatable(self):
        """REVERSED 2026-08-24. This asserted the opposite — that broken lock infra
        should yield True and let the caller proceed unlocked — while
        test_worktree_isolation.py::test_repo_lock_fails_closed_when_lock_directory_is_unavailable
        asserted False for the same branch. Two tests, one branch, contradictory
        invariants; the implementation satisfied this one, so that one had been red.

        False is the correct answer. An uncreatable LOCK_DIR stops every process on
        the host equally, so yielding True does not preserve exclusion for anyone —
        it just lets all of them rebase the same refs at once, which is the 32-hour
        merge stall in this module's own docstring. Every caller treats False as
        transient and retries, so refusing defers work; it does not wedge the fleet.
        """
        # point at a path that cannot be created as a directory (a file, not a dir)
        bad = os.path.join(self.lock_dir, "not_a_dir")
        with open(bad, "w") as f:
            f.write("x")
        os.environ["ORCH_REPO_LOCK_DIR"] = os.path.join(bad, "nested")
        import importlib
        importlib.reload(repo_lock)
        with repo_lock.hold("/some/repo") as got:
            self.assertFalse(got, "unavailable lock infra must refuse the lock, not "
                                  "hand out an unprotected True")
        # restore
        os.environ["ORCH_REPO_LOCK_DIR"] = self.lock_dir
        importlib.reload(repo_lock)


if __name__ == "__main__":
    unittest.main()
