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


def _hold_and_record(lock_dir, repo, out_path, hold_seconds, ready=None):
    os.environ["ORCH_REPO_LOCK_DIR"] = lock_dir
    import importlib
    import repo_lock as rl
    importlib.reload(rl)
    with rl.hold(repo):
        if ready is not None:
            ready.set()
        with open(out_path, "a") as f:
            f.write(f"start {time.time()}\n")
        time.sleep(hold_seconds)
        with open(out_path, "a") as f:
            f.write(f"end {time.time()}\n")


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
        ready = multiprocessing.Event()
        holder = multiprocessing.Process(
            target=_hold_and_record, args=(self.lock_dir, "/contended/repo", out_path, 2.0, ready))
        holder.start()
        self.assertTrue(ready.wait(5), "holder process did not acquire the lock")
        got_it = None
        with repo_lock.hold("/contended/repo", timeout=0.5) as got:
            got_it = got
        self.assertFalse(got_it, "second caller should time out while the first holds the lock")
        holder.join(timeout=5)

    def test_sequential_after_release_succeeds(self):
        out_path = os.path.join(self.lock_dir, "out2.txt")
        ready = multiprocessing.Event()
        holder = multiprocessing.Process(
            target=_hold_and_record, args=(self.lock_dir, "/contended/repo2", out_path, 0.5, ready))
        holder.start()
        self.assertTrue(ready.wait(5), "holder process did not acquire the lock")
        with repo_lock.hold("/contended/repo2", timeout=5) as got:
            self.assertTrue(got, "caller should acquire once the holder releases within the timeout")
        holder.join(timeout=5)

    def test_no_timeout_blocks_until_acquired(self):
        out_path = os.path.join(self.lock_dir, "out3.txt")
        ready = multiprocessing.Event()
        holder = multiprocessing.Process(
            target=_hold_and_record, args=(self.lock_dir, "/contended/repo3", out_path, 0.5, ready))
        holder.start()
        self.assertTrue(ready.wait(5), "holder process did not acquire the lock")
        start = time.time()
        with repo_lock.hold("/contended/repo3") as got:
            elapsed = time.time() - start
            self.assertTrue(got)
            self.assertGreaterEqual(elapsed, 0.3, "blocking hold() should wait for the holder to release")
        holder.join(timeout=5)

    def test_falls_back_to_unlocked_when_dir_uncreatable(self):
        # point at a path that cannot be created as a directory (a file, not a dir)
        bad = os.path.join(self.lock_dir, "not_a_dir")
        with open(bad, "w") as f:
            f.write("x")
        os.environ["ORCH_REPO_LOCK_DIR"] = os.path.join(bad, "nested")
        import importlib
        importlib.reload(repo_lock)
        with repo_lock.hold("/some/repo") as got:
            self.assertTrue(got, "fail-soft: unavailable lock infra should still yield True and proceed")
        # restore
        os.environ["ORCH_REPO_LOCK_DIR"] = self.lock_dir
        importlib.reload(repo_lock)


if __name__ == "__main__":
    unittest.main()
