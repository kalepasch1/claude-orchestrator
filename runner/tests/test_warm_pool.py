#!/usr/bin/env python3
import os
import sys
import time
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from warm_pool import WarmPool, _build_context, _read_claude_md, SLOT_TTL


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


if __name__ == "__main__":
    unittest.main()
