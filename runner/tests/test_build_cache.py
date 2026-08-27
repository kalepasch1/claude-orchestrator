#!/usr/bin/env python3
"""Tests for runner/build_cache.py.

WHAT THIS FILE USED TO TEST
---------------------------
It tested `build_cache.cache_key(worktree)`, `build_cache.restore(wt, root=...)`
and `build_cache.save(wt, root=...)` — a filesystem cache that hashes a
package-lock.json and tars node_modules/.nuxt aside.  runner/build_cache.py has
never had any of those functions, and no module in the repository does; all
seven tests died with AttributeError at collection.  The capability itself does
exist, under a different name and a much more developed design, in
runner/dependency_prewarm.py (fingerprinted snapshot/restore of an install).

runner/build_cache.py is a different thing: a DB-backed cache of BUILD-GATE
RESULTS keyed by (repo, commit sha, build command), so a rebase or retry that
lands on a commit already built does not pay the 2-5 minute build again.  It had
no tests at all.  These are those.
"""
import json
import os
import sys
import time
import types
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import build_cache  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self):
        self._db = build_cache.db
        self.db = types.SimpleNamespace(
            select=MagicMock(return_value=[]),
            upsert=MagicMock(return_value={"key": "k"}),
        )
        build_cache.db = self.db
        self._enabled = build_cache.CACHE_ENABLED
        self._ttl = build_cache.CACHE_TTL_HOURS
        build_cache.CACHE_ENABLED = True
        build_cache.CACHE_TTL_HOURS = 6
        # Restored in tearDown: a stub left bound to the module outlives the test
        # that installed it and silently rewrites the behaviour of every later
        # test in the session that imports build_cache.
        self._commit_sha = build_cache._commit_sha

    def tearDown(self):
        build_cache.db = self._db
        build_cache.CACHE_ENABLED = self._enabled
        build_cache.CACHE_TTL_HOURS = self._ttl
        build_cache._commit_sha = self._commit_sha

    def _row(self, ok=True, log="built", ts=None, updated_at=None):
        payload = {"ok": ok, "log": log}
        if ts is not None:
            payload["ts"] = ts
        row = {"value": json.dumps(payload)}
        if updated_at is not None:
            row["updated_at"] = updated_at
        return [row]


class TestCacheKey(_Base):
    def test_same_inputs_give_the_same_key(self):
        a = build_cache._cache_key("/x/repo", "abc123", "npm run build")
        b = build_cache._cache_key("/y/repo", "abc123", "npm run build")
        self.assertEqual(a, b, "the key is the repo BASENAME plus sha plus command")

    def test_a_different_commit_gives_a_different_key(self):
        a = build_cache._cache_key("/x/repo", "abc123", "npm run build")
        b = build_cache._cache_key("/x/repo", "def456", "npm run build")
        self.assertNotEqual(a, b)

    def test_a_different_build_command_gives_a_different_key(self):
        """A cached `npm run build` must not answer for `npm run build:prod`."""
        a = build_cache._cache_key("/x/repo", "abc123", "npm run build")
        b = build_cache._cache_key("/x/repo", "abc123", "npm run build:prod")
        self.assertNotEqual(a, b)

    def test_a_different_repo_gives_a_different_key(self):
        a = build_cache._cache_key("/x/alpha", "abc123", "npm run build")
        b = build_cache._cache_key("/x/beta", "abc123", "npm run build")
        self.assertNotEqual(a, b)

    def test_the_key_is_a_fixed_width_hex_digest(self):
        k = build_cache._cache_key("/x/repo", "abc123", "npm run build")
        self.assertEqual(len(k), 32)
        int(k, 16)


class TestTTL(_Base):
    """CACHE_TTL_HOURS was documented and never applied: lookup() checked only
    that `updated_at` was non-empty, so an entry never expired.  For a build
    gate that means a green recorded weeks ago can let a branch merge on a build
    nobody has run since."""

    def test_a_fresh_entry_is_a_hit(self):
        self.db.select.return_value = self._row(ok=True, ts=time.time() - 60)
        self.assertEqual(build_cache.lookup("/r", "sha", "cmd"), (True, "built"))

    def test_an_entry_older_than_the_ttl_is_a_miss(self):
        self.db.select.return_value = self._row(ts=time.time() - 7 * 3600)
        self.assertIsNone(build_cache.lookup("/r", "sha", "cmd"))

    def test_the_boundary_is_not_a_hit_a_second_past_it(self):
        self.db.select.return_value = self._row(ts=time.time() - (6 * 3600 + 1))
        self.assertIsNone(build_cache.lookup("/r", "sha", "cmd"))

    def test_an_entry_with_no_age_at_all_is_a_miss(self):
        """Undeterminable age must not be replayed as a fresh build result."""
        self.db.select.return_value = self._row(ts=None, updated_at="")
        self.assertIsNone(build_cache.lookup("/r", "sha", "cmd"))

    def test_an_unparseable_timestamp_is_a_miss(self):
        self.db.select.return_value = self._row(ts=None, updated_at="whenever")
        self.assertIsNone(build_cache.lookup("/r", "sha", "cmd"))

    def test_a_server_timestamp_is_used_when_the_payload_has_no_ts(self):
        import datetime
        recent = (datetime.datetime.now(datetime.timezone.utc)
                  - datetime.timedelta(minutes=5)).isoformat()
        self.db.select.return_value = self._row(ts=None, updated_at=recent)
        self.assertEqual(build_cache.lookup("/r", "sha", "cmd"), (True, "built"))

    def test_a_naive_server_timestamp_is_read_as_utc(self):
        import datetime
        recent = (datetime.datetime.now(datetime.timezone.utc)
                  - datetime.timedelta(minutes=5)).replace(tzinfo=None).isoformat()
        self.db.select.return_value = self._row(ts=None, updated_at=recent)
        self.assertEqual(build_cache.lookup("/r", "sha", "cmd"), (True, "built"))


class TestLookup(_Base):
    def test_a_miss_returns_none(self):
        self.db.select.return_value = []
        self.assertIsNone(build_cache.lookup("/r", "sha", "cmd"))

    def test_a_cached_failure_is_returned_as_a_failure(self):
        """A red build must be replayed as red, not softened into a hit."""
        self.db.select.return_value = self._row(ok=False, log="tsc error",
                                                ts=time.time())
        self.assertEqual(build_cache.lookup("/r", "sha", "cmd"), (False, "tsc error"))

    def test_no_sha_means_no_lookup(self):
        self.assertIsNone(build_cache.lookup("/r", "", "cmd"))
        self.db.select.assert_not_called()

    def test_disabled_means_no_lookup(self):
        build_cache.CACHE_ENABLED = False
        self.assertIsNone(build_cache.lookup("/r", "sha", "cmd"))
        self.db.select.assert_not_called()

    def test_a_db_failure_is_a_miss_not_an_exception(self):
        self.db.select.side_effect = RuntimeError("control plane down")
        self.assertIsNone(build_cache.lookup("/r", "sha", "cmd"))


class TestStore(_Base):
    def test_store_upserts_one_row_with_two_arguments(self):
        """db.upsert(table, row) takes two.  This was called with three and
        raised TypeError inside a fail-soft handler, so nothing was ever
        cached and every build re-ran from scratch."""
        build_cache.store("/r", "sha", "cmd", True, "ok")
        self.db.upsert.assert_called_once()
        args = self.db.upsert.call_args[0]
        self.assertEqual(len(args), 2)
        self.assertEqual(args[0], "controls")
        self.assertEqual(set(args[1]), {"key", "value"})

    def test_the_stored_key_matches_what_lookup_will_ask_for(self):
        build_cache.store("/r", "sha", "cmd", True, "ok")
        stored = self.db.upsert.call_args[0][1]["key"]
        build_cache.lookup("/r", "sha", "cmd")
        asked = self.db.select.call_args[0][1]["key"]
        self.assertEqual(asked, "eq." + stored)

    def test_the_payload_carries_its_own_timestamp(self):
        build_cache.store("/r", "sha", "cmd", True, "ok")
        payload = json.loads(self.db.upsert.call_args[0][1]["value"])
        self.assertIn("ts", payload)
        self.assertLess(abs(payload["ts"] - time.time()), 30)

    def test_a_long_log_is_truncated_to_the_tail(self):
        build_cache.store("/r", "sha", "cmd", False, "x" * 5000 + "TAIL")
        payload = json.loads(self.db.upsert.call_args[0][1]["value"])
        self.assertEqual(len(payload["log"]), 2000)
        self.assertTrue(payload["log"].endswith("TAIL"))

    def test_no_sha_stores_nothing(self):
        build_cache.store("/r", "", "cmd", True, "ok")
        self.db.upsert.assert_not_called()

    def test_a_db_failure_does_not_propagate(self):
        self.db.upsert.side_effect = RuntimeError("boom")
        build_cache.store("/r", "sha", "cmd", True, "ok")


class TestCachedBuild(_Base):
    def test_a_hit_does_not_run_the_build(self):
        self.db.select.return_value = self._row(ok=True, log="cached", ts=time.time())
        calls = []

        def run_fn(repo, branch, cmd):
            calls.append((repo, branch, cmd))
            return (False, "should not have run")

        build_cache._commit_sha = lambda repo, branch: "sha1"
        self.assertEqual(build_cache.cached_build("/r", "b", "cmd", run_fn),
                         (True, "cached"))
        self.assertEqual(calls, [])

    def test_a_miss_runs_the_build_and_stores_the_result(self):
        self.db.select.return_value = []
        build_cache._commit_sha = lambda repo, branch: "sha1"
        out = build_cache.cached_build("/r", "b", "cmd",
                                       lambda *a: (True, "fresh build"))
        self.assertEqual(out, (True, "fresh build"))
        self.db.upsert.assert_called_once()

    def test_an_expired_entry_causes_a_real_build(self):
        """The whole point of the TTL fix, end to end."""
        self.db.select.return_value = self._row(ok=True, log="stale",
                                                ts=time.time() - 7 * 3600)
        build_cache._commit_sha = lambda repo, branch: "sha1"
        out = build_cache.cached_build("/r", "b", "cmd", lambda *a: (False, "now red"))
        self.assertEqual(out, (False, "now red"))


if __name__ == "__main__":
    unittest.main()
