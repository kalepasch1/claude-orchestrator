#!/usr/bin/env python3
import os
import sys
import time
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from warm_pool import WarmPool, _build_context, _read_claude_md, SLOT_TTL
import warm_pool as _warm_pool_module


def _repo(claude_md=None):
    d = tempfile.mkdtemp()
    if claude_md is not None:
        with open(os.path.join(d, "CLAUDE.md"), "w") as f:
            f.write(claude_md)
    return d


class WarmPoolAcquireTest(unittest.TestCase):

    def test_missing_dir_returns_empty(self):
        pool = WarmPool(pool_size=3)
        self.assertEqual(pool.acquire("/nonexistent/path/xyz"), "")

    def test_repo_without_claude_md_returns_empty(self):
        d = _repo()
        pool = WarmPool(pool_size=3)
        self.assertEqual(pool.acquire(d), "")

    def test_repo_with_claude_md_returns_prefix(self):
        d = _repo("# Guide\n\nUse Python 3.10+")
        pool = WarmPool(pool_size=3)
        result = pool.acquire(d)
        self.assertIn("Guide", result)
        self.assertIn("pre-loaded", result)

    def test_second_acquire_served_from_cache(self):
        d = _repo("# Cached version")
        pool = WarmPool(pool_size=3)
        r1 = pool.acquire(d)
        # mutate file after first load — cached result should be returned unchanged
        with open(os.path.join(d, "CLAUDE.md"), "w") as f:
            f.write("# Changed")
        r2 = pool.acquire(d)
        self.assertEqual(r1, r2)

    def test_hits_counter_increments(self):
        d = _repo("# Hit counter")
        pool = WarmPool(pool_size=3)
        pool.acquire(d)
        pool.acquire(d)
        st = pool.stats()
        self.assertEqual(st["repos"][0]["hits"], 2)

    def test_none_input_returns_empty(self):
        pool = WarmPool(pool_size=3)
        self.assertEqual(pool.acquire(None), "")

    def test_empty_string_input_returns_empty(self):
        pool = WarmPool(pool_size=3)
        self.assertEqual(pool.acquire(""), "")

    def test_acquire_never_raises_on_bad_input(self):
        pool = WarmPool(pool_size=3)
        for bad in [None, "", "/dev/null/x", 0]:
            try:
                result = pool.acquire(bad)
                self.assertIsInstance(result, str)
            except Exception as e:
                self.fail(f"acquire({bad!r}) raised {e!r}")


class WarmPoolEvictionTest(unittest.TestCase):

    def test_pool_size_limit_enforced(self):
        repos = [_repo(f"# Project {i}") for i in range(4)]
        pool = WarmPool(pool_size=2)
        for r in repos:
            pool.acquire(r)
        self.assertLessEqual(pool.stats()["loaded"], 2)

    def test_oldest_slot_evicted_when_full(self):
        r1, r2, r3 = _repo("# R1"), _repo("# R2"), _repo("# R3")
        pool = WarmPool(pool_size=2)
        pool.acquire(r1)
        time.sleep(0.01)
        pool.acquire(r2)
        # Third acquire should evict r1 (oldest)
        pool.acquire(r3)
        repos_in_pool = {e["repo"] for e in pool.stats()["repos"]}
        self.assertNotIn(os.path.basename(r1), repos_in_pool)


class WarmPoolInvalidateTest(unittest.TestCase):

    def test_invalidate_removes_slot(self):
        d = _repo("# Invalidate me")
        pool = WarmPool(pool_size=3)
        pool.acquire(d)
        self.assertEqual(pool.stats()["loaded"], 1)
        pool.invalidate(d)
        self.assertEqual(pool.stats()["loaded"], 0)

    def test_acquire_after_invalidate_re_reads_disk(self):
        d = _repo("# Original")
        pool = WarmPool(pool_size=3)
        pool.acquire(d)
        pool.invalidate(d)
        with open(os.path.join(d, "CLAUDE.md"), "w") as f:
            f.write("# Updated content")
        result = pool.acquire(d)
        self.assertIn("Updated content", result)


class WarmPoolStaleTest(unittest.TestCase):

    def test_stale_slot_reloads_updated_file(self):
        d = _repo("# Stale original")
        pool = WarmPool(pool_size=3)
        pool.acquire(d)
        # Force slot to be stale
        with pool._lock:
            pool._slots[d].loaded_at = time.time() - SLOT_TTL - 1
        with open(os.path.join(d, "CLAUDE.md"), "w") as f:
            f.write("# Refreshed after stale")
        result = pool.acquire(d)
        self.assertIn("Refreshed after stale", result)


class WarmPoolMemoryGateTest(unittest.TestCase):

    def test_new_entry_blocked_when_pool_full_and_mem_low(self):
        repos = [_repo(f"# Gated {i}") for i in range(2)]
        pool = WarmPool(pool_size=2)
        pool.preload(repos)
        extra = _repo("# Extra (should be blocked)")
        with patch.object(pool, "_mem_ok", return_value=False):
            pool._warm_one(extra)
        self.assertLessEqual(pool.stats()["loaded"], 2)
        self.assertNotIn(extra, pool._slots)

    def test_existing_slot_refreshes_regardless_of_mem(self):
        d = _repo("# Existing")
        pool = WarmPool(pool_size=2)
        pool.acquire(d)
        # Force stale
        with pool._lock:
            pool._slots[d].loaded_at = time.time() - SLOT_TTL - 1
        with open(os.path.join(d, "CLAUDE.md"), "w") as f:
            f.write("# Refreshed under mem pressure")
        # Refreshing an existing slot doesn't go through the eviction+mem gate
        with patch.object(pool, "_mem_ok", return_value=False):
            result = pool.acquire(d)
        self.assertIn("Refreshed", result)


class WarmPoolEnabledTest(unittest.TestCase):

    def test_disabled_pool_returns_empty(self):
        d = _repo("# Disabled")
        pool = WarmPool(pool_size=3)
        pool.acquire(d)
        pool.set_enabled(False)
        self.assertEqual(pool.acquire(d), "")

    def test_disabled_pool_clears_slots(self):
        d = _repo("# Clear me")
        pool = WarmPool(pool_size=3)
        pool.acquire(d)
        pool.set_enabled(False)
        self.assertEqual(pool.stats()["loaded"], 0)


class WarmPoolPreloadTest(unittest.TestCase):

    def test_preload_warms_multiple_repos(self):
        repos = [_repo(f"# Pre {i}") for i in range(3)]
        pool = WarmPool(pool_size=5)
        pool.preload(repos)
        self.assertEqual(pool.stats()["loaded"], 3)

    def test_preload_skips_missing_dirs(self):
        pool = WarmPool(pool_size=3)
        pool.preload(["/no/such/dir", None, ""])
        self.assertEqual(pool.stats()["loaded"], 0)


class WarmPoolStatsTest(unittest.TestCase):

    def test_stats_structure(self):
        d = _repo("# Stats")
        pool = WarmPool(pool_size=5)
        pool.acquire(d)
        st = pool.stats()
        self.assertEqual(st["pool_size"], 5)
        self.assertEqual(st["loaded"], 1)
        self.assertTrue(st["enabled"])
        self.assertEqual(len(st["repos"]), 1)
        self.assertIn("age_s", st["repos"][0])
        self.assertIn("hits", st["repos"][0])


class BuildContextTest(unittest.TestCase):

    def test_empty_repo_gives_empty_prefix(self):
        d = _repo()
        prefix, cs = _build_context(d)
        self.assertEqual(prefix, "")

    def test_claude_md_content_in_prefix(self):
        d = _repo("Follow the style guide.\nAlways write tests.")
        prefix, cs = _build_context(d)
        self.assertIn("Follow the style guide", prefix)
        self.assertIn("Always write tests", prefix)
        self.assertTrue(len(cs) > 0)

    def test_checksum_changes_with_content(self):
        d1 = _repo("# V1")
        d2 = _repo("# V2")
        _, cs1 = _build_context(d1)
        _, cs2 = _build_context(d2)
        self.assertNotEqual(cs1, cs2)

    def test_whitespace_only_file_returns_empty(self):
        d = _repo("   \n   \t  ")
        prefix, _ = _build_context(d)
        self.assertEqual(prefix, "")


class WarmPoolThreadSafetyTest(unittest.TestCase):
    """Thread-safety tests for WarmPool: concurrent access, lock contention, race conditions."""

    # ── helpers ────────────────────────────────────────────────────────────────

    def _run_threads(self, fn, n=20):
        """Run *fn* on *n* threads, return list of results (exceptions as values)."""
        barrier = threading.Barrier(n)
        results = [None] * n

        def worker(idx):
            barrier.wait()        # synchronize start to maximize contention
            try:
                results[idx] = fn(idx)
            except Exception as exc:
                results[idx] = exc

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        return results

    # ── 1. concurrent acquire on same repo ────────────────────────────────────

    def test_concurrent_acquire_same_repo_no_exceptions(self):
        d = _repo("# Concurrent same")
        pool = WarmPool(pool_size=5)
        results = self._run_threads(lambda _: pool.acquire(d), n=20)
        errors = [r for r in results if isinstance(r, Exception)]
        self.assertEqual(errors, [], f"Exceptions raised: {errors}")

    def test_concurrent_acquire_same_repo_consistent_result(self):
        """All threads should get an identical prefix for the same repo."""
        d = _repo("# Consistent")
        pool = WarmPool(pool_size=5)
        results = self._run_threads(lambda _: pool.acquire(d), n=20)
        unique = set(r for r in results if not isinstance(r, Exception))
        self.assertEqual(len(unique), 1, f"Got multiple distinct prefixes: {unique}")

    # ── 2. concurrent acquire on different repos ───────────────────────────────

    def test_concurrent_acquire_different_repos_pool_limit_respected(self):
        """Pool size must never be exceeded under concurrent writes."""
        repos = [_repo(f"# Repo {i}") for i in range(20)]
        pool = WarmPool(pool_size=3)
        self._run_threads(lambda i: pool.acquire(repos[i]), n=20)
        self.assertLessEqual(pool.stats()["loaded"], 3)

    # ── 3. race between acquire and invalidate ─────────────────────────────────

    def test_concurrent_acquire_and_invalidate_no_deadlock(self):
        """acquire() and invalidate() racing on the same repo must not deadlock or raise."""
        d = _repo("# Race target")
        pool = WarmPool(pool_size=5)
        stop = threading.Event()
        errors = []

        def invalidator():
            while not stop.is_set():
                pool.invalidate(d)
                time.sleep(0.001)

        t = threading.Thread(target=invalidator, daemon=True)
        t.start()
        try:
            results = self._run_threads(lambda _: pool.acquire(d), n=10)
            errors = [r for r in results if isinstance(r, Exception)]
        finally:
            stop.set()
            t.join(timeout=2)
        self.assertEqual(errors, [])

    # ── 4. race between acquire and set_enabled(False) ────────────────────────

    def test_concurrent_acquire_while_disabling_returns_str(self):
        """Disabling mid-flight must not raise; every result is a str."""
        d = _repo("# Disable race")
        pool = WarmPool(pool_size=5)
        pool.acquire(d)   # warm it first

        ready = threading.Barrier(11)

        def acquire_worker(_):
            ready.wait()
            return pool.acquire(d)

        def disable_worker():
            ready.wait()
            pool.set_enabled(False)

        t = threading.Thread(target=disable_worker)
        t.start()
        results = self._run_threads(acquire_worker, n=10)
        t.join(timeout=2)
        for r in results:
            self.assertIsInstance(r, str, f"Expected str, got {r!r}")

    # ── 5. stats consistency under concurrent access ───────────────────────────

    def test_stats_internally_consistent_under_concurrent_load(self):
        """stats() must always report loaded ≤ pool_size, even during concurrent writes."""
        repos = [_repo(f"# Stats {i}") for i in range(30)]
        pool = WarmPool(pool_size=4)

        inconsistencies = []

        def worker(i):
            pool.acquire(repos[i % len(repos)])
            st = pool.stats()
            if st["loaded"] > st["pool_size"]:
                inconsistencies.append(st)

        self._run_threads(worker, n=30)
        self.assertEqual(inconsistencies, [],
                         f"Stats inconsistency detected: {inconsistencies[:3]}")

    # ── 6. concurrent invalidate — no deadlock ────────────────────────────────

    def test_concurrent_invalidate_same_repo_no_deadlock(self):
        d = _repo("# Multi-invalidate")
        pool = WarmPool(pool_size=5)
        pool.acquire(d)
        results = self._run_threads(lambda _: pool.invalidate(d), n=20)
        errors = [r for r in results if isinstance(r, Exception)]
        self.assertEqual(errors, [])
        self.assertEqual(pool.stats()["loaded"], 0)

    # ── 7. module-level singleton thread safety ────────────────────────────────

    def test_module_singleton_acquire_thread_safe(self):
        """Module-level acquire()/invalidate()/stats() share one singleton — no exceptions."""
        d = _repo("# Module singleton")
        errors = []

        def worker(_):
            _warm_pool_module.acquire(d)
            _warm_pool_module.stats()
            _warm_pool_module.invalidate(d)

        results = self._run_threads(worker, n=15)
        errors = [r for r in results if isinstance(r, Exception)]
        self.assertEqual(errors, [])

    # ── 8. preload + acquire concurrently ─────────────────────────────────────

    def test_concurrent_preload_and_acquire_no_exception(self):
        repos = [_repo(f"# PA {i}") for i in range(5)]
        pool = WarmPool(pool_size=5)

        ready = threading.Barrier(2)
        results = []

        def preloader():
            ready.wait()
            pool.preload(repos)

        def acquirer():
            ready.wait()
            return [pool.acquire(r) for r in repos]

        t = threading.Thread(target=preloader)
        t.start()
        out = acquirer()
        t.join(timeout=5)

        # all results must be strings (not exceptions)
        for v in out:
            self.assertIsInstance(v, str)

    # ── 9. pool stays bounded under heavy write contention ────────────────────

    def test_pool_bounded_under_heavy_concurrent_writes(self):
        """Stress: 50 threads each writing a unique repo, pool capped at 5."""
        repos = [_repo(f"# Heavy {i}") for i in range(50)]
        pool = WarmPool(pool_size=5)
        self._run_threads(lambda i: pool.acquire(repos[i]), n=50)
        st = pool.stats()
        self.assertLessEqual(st["loaded"], 5)
        self.assertGreaterEqual(st["loaded"], 0)

    # ── 10. hits counter is monotonically non-negative under concurrent reads ──

    def test_hits_counter_non_negative_after_concurrent_reads(self):
        d = _repo("# Hits thread")
        pool = WarmPool(pool_size=5)
        pool.acquire(d)
        self._run_threads(lambda _: pool.acquire(d), n=30)
        st = pool.stats()
        if st["repos"]:
            self.assertGreaterEqual(st["repos"][0]["hits"], 0)


if __name__ == "__main__":
    unittest.main()
