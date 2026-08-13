#!/usr/bin/env python3
"""Memory bounds for merged_diff_memory: the diff cache must give bytes back.

The cap was enforced by REFUSING writes, not by evicting: once CACHE_SIZE_BYTES of diffs
had accumulated the pool never accepted another entry and never released one. TTL did not
help — expiry was only checked inside get_diff(), and only for the key being looked up, so
a diff nobody asks for again was held for the life of the process. The steady state of a
long-running runner was therefore a permanently full cache of permanently stale content.

These tests pin the two properties that fix it: expired bytes are reclaimed, and a full
cache still accepts new work by evicting oldest-first.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import merged_diff_memory as mdm  # noqa: E402


class DiffPoolEvictionTest(unittest.TestCase):
    def setUp(self):
        self.pool = mdm._DiffPool()

    def _fill(self, n, size, prefix="c"):
        for i in range(n):
            self.pool.put_diff("main", "agent", f"{prefix}{i}", "x" * size)

    def test_a_full_cache_still_accepts_new_diffs(self):
        # The regression: the (n+1)th write used to be dropped forever.
        with patch.object(mdm, "CACHE_SIZE_BYTES", 1000):
            self._fill(10, 100)
            self.assertEqual(self.pool.stats()["bytes_used"], 1000)
            self.pool.put_diff("main", "agent", "newest", "y" * 100)
            self.assertEqual(self.pool.get_diff("main", "agent", "newest"), "y" * 100)

    def test_eviction_is_oldest_first(self):
        with patch.object(mdm, "CACHE_SIZE_BYTES", 1000):
            self._fill(10, 100)
            self.pool.put_diff("main", "agent", "newest", "y" * 100)
            self.assertEqual(self.pool.get_diff("main", "agent", "c0"), "",
                             "the oldest entry is the one that should go")
            self.assertEqual(self.pool.get_diff("main", "agent", "c9"), "x" * 100)

    def test_the_cap_is_never_exceeded(self):
        with patch.object(mdm, "CACHE_SIZE_BYTES", 1000):
            self._fill(50, 100)
            self.assertLessEqual(self.pool.stats()["bytes_used"], 1000)

    def test_expired_bytes_are_reclaimed_without_anyone_reading_them(self):
        # A diff nobody looks up again used to be held forever. TTL now reclaims it.
        with patch.object(mdm, "CACHE_SIZE_BYTES", 1000), patch.object(mdm, "CACHE_TTL", -1):
            self._fill(10, 100)
            self.pool.put_diff("main", "agent", "newest", "y" * 100)
            self.assertEqual(self.pool.stats()["bytes_used"], 100,
                             "every expired entry should have been dropped, not just one")

    def test_expired_entries_are_evicted_before_live_ones(self):
        with patch.object(mdm, "CACHE_SIZE_BYTES", 1000):
            with patch.object(mdm, "CACHE_TTL", -1):
                self._fill(9, 100, prefix="stale")
            self.pool.put_diff("main", "agent", "live", "z" * 100)
            self.pool.put_diff("main", "agent", "newest", "y" * 100)
            self.assertEqual(self.pool.get_diff("main", "agent", "live"), "z" * 100,
                             "a live entry must not be evicted while stale ones remain")

    def test_stats_report_evictions(self):
        with patch.object(mdm, "CACHE_SIZE_BYTES", 1000):
            self._fill(10, 100)
            self.assertEqual(self.pool.stats()["evictions"], 0)
            self.pool.put_diff("main", "agent", "newest", "y" * 100)
            self.assertGreater(self.pool.stats()["evictions"], 0)

    def test_overwriting_a_key_does_not_leak_its_bytes(self):
        with patch.object(mdm, "CACHE_SIZE_BYTES", 1000):
            for _ in range(20):
                self.pool.put_diff("main", "agent", "same", "x" * 100)
            self.assertEqual(self.pool.stats()["entries"], 1)
            self.assertEqual(self.pool.stats()["bytes_used"], 100)

    def test_invalidate_zeroes_the_eviction_counter(self):
        with patch.object(mdm, "CACHE_SIZE_BYTES", 1000):
            self._fill(15, 100)
            self.pool.invalidate()
            self.assertEqual(self.pool.stats(),
                             {"entries": 0, "bytes_used": 0, "hits": 0,
                              "misses": 0, "evictions": 0})


class RecentDiffSizeCapTest(unittest.TestCase):
    """recent() holds every diff in memory at once; each one must be bounded."""

    def _run(self, env, diff_size):
        def fake_safe_run(cmd, cwd=None):
            if "log" in cmd and "--format=%H" in cmd:
                return "sha1"
            if "show" in cmd:
                return "d" * diff_size
            return "meta"

        with patch.dict(os.environ, env, clear=False), \
             patch.object(mdm, "_safe_run", side_effect=fake_safe_run):
            return mdm.recent(days=1, limit=1, repo=".")

    def test_an_enormous_diff_is_truncated_to_the_cap(self):
        out = self._run({"ORCH_DIFF_RECENT_MAX_BYTES": "512"}, 100_000)
        self.assertEqual(len(out[0]["diff"]), 512)

    def test_a_small_diff_is_untouched(self):
        out = self._run({"ORCH_DIFF_RECENT_MAX_BYTES": "512"}, 100)
        self.assertEqual(len(out[0]["diff"]), 100)

    def test_the_cap_can_be_disabled(self):
        out = self._run({"ORCH_DIFF_RECENT_MAX_BYTES": "0"}, 5_000)
        self.assertEqual(len(out[0]["diff"]), 5_000)

    def test_a_junk_cap_falls_back_to_the_default(self):
        out = self._run({"ORCH_DIFF_RECENT_MAX_BYTES": "not-a-number"}, 400_000)
        self.assertEqual(len(out[0]["diff"]), 256 * 1024)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
