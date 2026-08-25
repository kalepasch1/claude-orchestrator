#!/usr/bin/env python3
"""Tests for repo_lock.py — the per-repo mutex fixing the 2026-07-08 merge-stall race."""
import multiprocessing
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import repo_lock


def _hold_and_record(lock_dir, repo, out_path, hold_seconds):
    os.environ["ORCH_REPO_LOCK_DIR"] = lock_dir
    import importlib
    import repo_lock as rl
    importlib.reload(rl)
    with rl.hold(repo):
        with open(out_path, "a") as f:
            f.write(f"start {time.time()}\n")
        time.sleep(hold_seconds)
        with open(out_path, "a") as f:
            f.write(f"end {time.time()}\n")


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
        holder = multiprocessing.Process(
            target=_hold_and_record, args=(self.lock_dir, "/contended/repo", out_path, 2.0))
        holder.start()
        _wait_until_held(out_path)
        got_it = None
        with repo_lock.hold("/contended/repo", timeout=0.5) as got:
            got_it = got
        self.assertFalse(got_it, "second caller should time out while the first holds the lock")
        holder.join(timeout=5)

    def test_sequential_after_release_succeeds(self):
        out_path = os.path.join(self.lock_dir, "out2.txt")
        holder = multiprocessing.Process(
            target=_hold_and_record, args=(self.lock_dir, "/contended/repo2", out_path, 0.5))
        holder.start()
        _wait_until_held(out_path)
        with repo_lock.hold("/contended/repo2", timeout=5) as got:
            self.assertTrue(got, "caller should acquire once the holder releases within the timeout")
        holder.join(timeout=5)

    def test_no_timeout_blocks_until_acquired(self):
        out_path = os.path.join(self.lock_dir, "out3.txt")
        holder = multiprocessing.Process(
            target=_hold_and_record, args=(self.lock_dir, "/contended/repo3", out_path, 1.0))
        holder.start()
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
        holder.join(timeout=5)

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
