#!/usr/bin/env python3
"""Tests for account_pool.py credential rotation and its cross-module cache.

Tests validate:
- The thread-safe claude_exhausted() cache and its 15s window
- Robust file I/O: corrupt/wrong-shaped state, unwritable state, corrupt flag file
- Fail-soft behaviour on credential config load failures
- Thread-safe singleton pattern for AccountPool
- Exponential backoff on repeated credential exhaustion
- Credential rotation and mark_ok() reset behavior
- Exhausted flag persistence and clearing

REWRITE NOTES
-------------
1. Paths. account_pool computes CFG / STATE / EXHAUSTED_FLAG once, at import, from
   CLAUDE_ORCH_HOME. This file used to set that env var inside the test body, which
   changes nothing after import: every "temp dir" test was really reading and
   WRITING the operator's real ~/.claude-orchestrator. That is why the flag-file and
   backoff-counter assertions failed (they saw state left by earlier runs). All
   classes now redirect the module constants themselves — the convention used by
   runner/tests/test_account_pool.py and runner/test_account_pool_secret_outcomes.py.

2. `_exh_cache_ttl()` does not exist. The whole TestCacheTTLConfiguration class
   asserted against an ORCH_EXH_CACHE_TTL knob that account_pool never had; the cache
   window is a fixed 15 seconds inside claude_exhausted(). Those five tests were
   replaced by tests of the real caching contract (see TestExhaustedCacheWindow).

3. `TestFailSoftDocstrings` asserted the literal word "Fail-soft" appeared in four
   docstrings. That tests prose, not code — and would have been "fixed" by editing a
   comment. It is now TestFailSoftBehaviour, which asserts the four functions
   actually degrade instead of raising.
"""

import os
import sys
import json
import time
import tempfile
import shutil
import threading
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")

import account_pool
import subscription_guard


class _TempPaths:
    """Isolate account_pool from this machine: temp paths AND an offline control plane.

    REDIRECTING THE PATH CONSTANTS IS NOT ENOUGH (fixed 2026-08-26). _load_cfg reads
    the Supabase `accounts` table FIRST and only falls back to the local JSON when
    that returns nothing. So every test here that wrote a config file and then built
    an AccountPool got the OPERATOR'S REAL ACCOUNTS instead — which is why
    `pool.state["test"]` raised KeyError and stats() reported 3 accounts where the
    fixture had written 1.

    Worse than a wrong assertion: mark_exhausted() then ran against a real account.
    It does

        db.update("accounts", {"name": a["name"]}, {"cooldown_until": until})

    and sends a notification. Running this file put the operator's live Claude
    accounts into cooldown and paged about the rotation — a unit test that could
    pause the fleet's capacity. The captured stdout said so out loud:
    "[notify] Account 'kale@heretomorrow.us' hit its limit -> rotated to
    'kale@smrter.us'."

    So the control plane is stubbed for the whole class: select returns nothing (the
    documented fallback path, which is what the fixtures write), and the writes are
    inert. account_pool does `import db` inside its functions, so the patch has to
    land on the real db module rather than an attribute of account_pool.
    """

    def setup_method(self, method):
        self.temp_dir = tempfile.mkdtemp()
        self.cfg_path = os.path.join(self.temp_dir, "accounts.json")
        self.state_path = os.path.join(self.temp_dir, "accounts_state.json")
        self.flag_path = os.path.join(self.temp_dir, "claude_exhausted.json")
        self._orig = (account_pool.CFG, account_pool.STATE, account_pool.EXHAUSTED_FLAG)
        account_pool.CFG = self.cfg_path
        account_pool.STATE = self.state_path
        account_pool.EXHAUSTED_FLAG = self.flag_path
        self._env_backup = dict(os.environ)
        self._orig_pool = account_pool._pool
        account_pool._pool = None
        account_pool._EXH_CACHE = {"t": 0.0, "v": False}

        import db as _db
        import notify as _notify
        self._patchers = [
            patch.object(_db, "select", lambda *a, **k: []),
            patch.object(_db, "update", lambda *a, **k: None),
            patch.object(_db, "insert", lambda *a, **k: None),
            patch.object(_notify, "send", lambda *a, **k: None),
        ]
        for p in self._patchers:
            p.start()

    def teardown_method(self, method):
        for p in reversed(self._patchers):
            p.stop()
        account_pool.CFG, account_pool.STATE, account_pool.EXHAUSTED_FLAG = self._orig
        account_pool._pool = self._orig_pool
        account_pool._EXH_CACHE = {"t": 0.0, "v": False}
        os.environ.clear()
        os.environ.update(self._env_backup)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def write_cfg(self, cfg):
        with open(self.cfg_path, "w") as f:
            json.dump(cfg, f)

    def write_flag(self, until):
        with open(self.flag_path, "w") as f:
            json.dump({"until": until}, f)


# ============================================================================
# claude_exhausted() cache window (replaces TestCacheTTLConfiguration)
# ============================================================================

class TestExhaustedCacheWindow(_TempPaths):
    """The cross-module 'all Claude capacity is cooling' signal and its 15s cache.

    Replaces TestCacheTTLConfiguration, which called account_pool._exh_cache_ttl()
    — a function this module has never defined (every test errored with
    AttributeError). The cache window is the literal 15 in claude_exhausted().
    """

    def _exhaust_the_pool(self):
        """Leave one configured account cooling, with no flag file on disk."""
        self.write_cfg([{"name": "acct1", "type": "login"}])
        pool = account_pool.AccountPool()
        pool.mark_exhausted(pool.accts[0])
        os.remove(self.flag_path)   # force the derive-from-state path
        return pool

    def test_cached_value_is_reused_inside_the_15s_window(self):
        """A 14s-old cache entry is returned without re-deriving from state."""
        self._exhaust_the_pool()
        account_pool._EXH_CACHE = {"t": time.time() - 14, "v": False}
        # Live state says exhausted; the fresh cache entry must win.
        assert account_pool.claude_exhausted() is False

    def test_cache_recomputes_once_the_15s_window_passes(self):
        """A 16s-old entry is discarded and the live account state re-derived."""
        self._exhaust_the_pool()
        account_pool._EXH_CACHE = {"t": time.time() - 16, "v": False}
        assert account_pool.claude_exhausted() is True

    def test_cache_window_is_not_env_tunable(self):
        """ORCH_EXH_CACHE_TTL is not wired up; the window stays 15s either way.

        Was test_cache_ttl_respects_env_var, which asserted the env var changed the
        TTL. Nothing in account_pool reads it — pinning that down keeps a future
        reader from assuming the knob works."""
        self._exhaust_the_pool()
        os.environ["ORCH_EXH_CACHE_TTL"] = "3600"
        account_pool._EXH_CACHE = {"t": time.time() - 16, "v": False}
        assert account_pool.claude_exhausted() is True   # recomputed, not held 1h

    def test_recompute_writes_timestamp_and_value_back_to_cache(self):
        """Was test_cache_ttl_zero_allowed. The real invariant: after a miss the
        cache holds the fresh answer and the time it was taken."""
        self._exhaust_the_pool()
        account_pool._EXH_CACHE = {"t": 0.0, "v": False}
        before = time.time()

        assert account_pool.claude_exhausted() is True

        assert account_pool._EXH_CACHE["v"] is True
        assert account_pool._EXH_CACHE["t"] >= before

    def test_unexpired_flag_file_short_circuits_the_cache(self):
        """Was test_cache_ttl_large_value_allowed. The real fast path: the flag file
        written by mark_exhausted wins over a fresh cache entry, and an expired flag
        falls through to the derived answer."""
        self.write_cfg([{"name": "acct1", "type": "login"}])
        self.write_flag(time.time() + 300)
        account_pool._EXH_CACHE = {"t": time.time(), "v": False}
        assert account_pool.claude_exhausted() is True

        # Expired flag -> ignored; the pool is healthy, so no exhaustion.
        self.write_flag(time.time() - 1)
        account_pool._EXH_CACHE = {"t": 0.0, "v": False}
        assert account_pool.claude_exhausted() is False


# ============================================================================
# Test Thread-Safe Cache (claude_exhausted)
# ============================================================================

class TestThreadSafeExhaustedCache(_TempPaths):
    """Test claude_exhausted() cache is thread-safe."""

    def test_cache_returns_same_value_within_ttl(self):
        """Cache hit: claude_exhausted() returns cached value within TTL."""
        self.write_cfg([{"name": "acct1", "type": "login"}])
        account_pool._EXH_CACHE = {"t": time.time() - 5, "v": True}
        assert account_pool.claude_exhausted() is True

    def test_cache_recomputes_after_ttl(self):
        """Cache miss: claude_exhausted() recomputes after TTL expires."""
        # Was asserting only isinstance(result, bool); with a real (temp) config the
        # recomputed value is knowable: one healthy account -> not exhausted.
        self.write_cfg([{"name": "acct1", "type": "login"}])
        account_pool._EXH_CACHE = {"t": time.time() - 20, "v": True}
        assert account_pool.claude_exhausted() is False

    def test_cache_lock_prevents_race(self):
        """Multiple threads calling claude_exhausted() don't corrupt cache."""
        self.write_cfg([{"name": "acct1", "type": "login"}])
        results = []
        errors = []

        def call_claude_exhausted():
            try:
                for _ in range(10):
                    results.append(account_pool.claude_exhausted())
            except Exception as e:  # pragma: no cover - only on a real race
                errors.append(e)

        threads = [threading.Thread(target=call_claude_exhausted) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors in concurrent cache access: {errors}"
        assert len(results) == 50, "All calls should complete"
        assert all(r is False for r in results)   # healthy account, no flag file

    def test_cache_initialization_is_thread_safe(self):
        """Threads that all force a recompute leave a coherent cache entry."""
        self.write_cfg([{"name": "acct1", "type": "login"}])

        def reset_and_call():
            account_pool._EXH_CACHE["t"] = 0.0
            account_pool.claude_exhausted()

        threads = [threading.Thread(target=reset_and_call) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert isinstance(account_pool._EXH_CACHE, dict)
        assert set(account_pool._EXH_CACHE) == {"t", "v"}
        assert isinstance(account_pool._EXH_CACHE["v"], bool)


# ============================================================================
# Test Robust File I/O and Error Handling
# ============================================================================

class TestRobustFileIO(_TempPaths):
    """Test file I/O handles corruption and missing files gracefully."""

    def test_load_state_missing_file_returns_empty_dict(self):
        """_load_state() returns {} if file missing."""
        pool = account_pool.AccountPool()
        assert pool._load_state() == {}

    def test_load_state_corrupted_json_returns_empty_dict(self):
        """_load_state() returns {} if file contains invalid JSON."""
        with open(self.state_path, "w") as f:
            f.write("{ invalid json }")

        pool = account_pool.AccountPool()
        assert pool._load_state() == {}

    def test_load_state_wrong_type_returns_empty_dict(self):
        """_load_state() returns {} if file contains non-dict."""
        # This one was a genuine product gap, not just a path bug: _load_state
        # returned the parsed list as-is and current() later died on
        # list.get(). _load_state now type-checks before returning.
        with open(self.state_path, "w") as f:
            json.dump([1, 2, 3], f)

        pool = account_pool.AccountPool()
        assert pool._load_state() == {}
        assert pool.current()["name"] == "default"   # pool stays usable

    def test_load_cfg_missing_file_returns_default(self):
        """_load_cfg() returns default if file missing."""
        pool = account_pool.AccountPool()

        cfg = pool._load_cfg()
        assert isinstance(cfg, list)
        assert len(cfg) > 0
        assert cfg[0]["name"] == "default"

    def test_load_cfg_corrupted_json_returns_default(self):
        """_load_cfg() returns default if file contains invalid JSON."""
        with open(self.cfg_path, "w") as f:
            f.write("{ invalid json }")

        pool = account_pool.AccountPool()
        assert pool._load_cfg()[0]["name"] == "default"

    def test_save_disk_error_doesnt_raise(self):
        """_save() doesn't raise on disk write error.

        The old version chmod'ed the temp dir to 0o444, which does not stop root (CI
        runs as root) and pointed at the wrong STATE path anyway, so the write always
        succeeded and nothing was exercised. Putting a regular FILE where the state
        directory should be makes the write fail for every user."""
        blocker = os.path.join(self.temp_dir, "blocker")
        with open(blocker, "w") as f:
            f.write("not a directory")
        account_pool.STATE = os.path.join(blocker, "accounts_state.json")

        pool = account_pool.AccountPool()
        pool.state = {"test": {"use_count": 1}}
        pool._save()   # must not raise

        assert not os.path.exists(account_pool.STATE)
        assert pool.state == {"test": {"use_count": 1}}   # in-memory state intact

    def test_exhausted_flag_handles_corrupted_json(self):
        """claude_exhausted() handles corrupted exhausted flag file."""
        self.write_cfg([{"name": "acct1", "type": "login"}])
        with open(self.flag_path, "w") as f:
            f.write("{ invalid json }")

        # Falls through to the live derivation instead of raising.
        assert account_pool.claude_exhausted() is False

    def test_exhausted_flag_handles_missing_until_field(self):
        """claude_exhausted() handles exhausted flag with missing 'until' field."""
        self.write_cfg([{"name": "acct1", "type": "login"}])
        with open(self.flag_path, "w") as f:
            json.dump({"other_field": "value"}, f)

        assert account_pool.claude_exhausted() is False


# ============================================================================
# Test Thread-Safe Singleton Pattern
# ============================================================================

class TestThreadSafeSingleton(_TempPaths):
    """Test _get_pool() creates singleton safely."""

    def test_get_pool_creates_singleton(self):
        """_get_pool() creates AccountPool singleton."""
        pool1 = account_pool._get_pool()
        pool2 = account_pool._get_pool()

        assert pool1 is pool2, "Should return same instance"

    def test_get_pool_thread_safe_initialization(self):
        """Multiple threads calling _get_pool() get same instance."""
        pools = []
        lock = threading.Lock()

        def get_and_store():
            pool = account_pool._get_pool()
            with lock:
                pools.append(pool)

        threads = [threading.Thread(target=get_and_store) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should be the same instance
        assert len(pools) == 10
        assert all(p is pools[0] for p in pools)

    def test_module_level_stats_delegates_to_singleton(self):
        """stats() calls _get_pool().stats()."""
        self.write_cfg([{"name": "acct1", "type": "login"}])

        stats = account_pool.stats()
        assert stats["total_accounts"] == 1
        assert stats["current"] == "acct1"

        # It is the SAME singleton: a use recorded on it shows up in the next
        # module-level snapshot.
        account_pool._get_pool().record_use({"name": "acct1"})
        assert account_pool.stats()["accounts"][0]["use_count"] == 1

    def test_module_level_invalidate_delegates_to_singleton(self):
        """invalidate() calls _get_pool().invalidate()."""
        self.write_cfg([{"name": "acct1", "type": "login"}])
        pool = account_pool._get_pool()
        pool.mark_exhausted(pool.accts[0])

        account_pool.invalidate("acct1")

        assert "cooldown_until" not in pool.state["acct1"]
        assert not os.path.exists(self.flag_path)


# ============================================================================
# Test Credential Rotation and Backoff
# ============================================================================

class TestCredentialRotationBackoff(_TempPaths):
    """Test mark_exhausted() implements exponential backoff."""

    def setup_method(self, method):
        super().setup_method(method)
        os.environ.pop("ORCH_ACCOUNT_COOLDOWN", None)
        os.environ.pop("ORCH_ACCOUNT_COOLDOWN_MAX", None)
        self.write_cfg([{"name": "test", "type": "login"}])

    def test_first_exhaustion_uses_base_cooldown(self):
        """First mark_exhausted() call uses COOLDOWN."""
        pool = account_pool.AccountPool()
        acct = pool.accts[0]

        before = time.time()
        pool.mark_exhausted(acct)
        after = time.time()

        cooldown_until = pool.state["test"]["cooldown_until"]
        assert before + account_pool._COOLDOWN_DEFAULT <= cooldown_until
        assert cooldown_until <= after + account_pool._COOLDOWN_DEFAULT

    def test_second_exhaustion_doubles_cooldown(self):
        """Second mark_exhausted() call doubles backoff."""
        pool = account_pool.AccountPool()
        acct = pool.accts[0]

        sent = time.time()
        pool.mark_exhausted(acct)
        first = pool.state["test"]["cooldown_until"] - sent

        sent = time.time()
        pool.mark_exhausted(acct)
        second = pool.state["test"]["cooldown_until"] - sent

        # Was only "second > first"; the documented contract is a doubling.
        assert abs(second - 2 * first) < 2

    def test_backoff_respects_cooldown_max(self):
        """Backoff never exceeds COOLDOWN_MAX."""
        os.environ["ORCH_ACCOUNT_COOLDOWN_MAX"] = "60"
        pool = account_pool.AccountPool()
        acct = pool.accts[0]

        for _ in range(10):
            pool.mark_exhausted(acct)

        remaining = pool.state["test"]["cooldown_until"] - time.time()
        assert 58 <= remaining <= 60

    def test_mark_ok_resets_backoff_counter(self):
        """mark_ok() clears exh_hits so backoff resets."""
        # Previously read exh_hits out of the machine's real state file, which
        # already carried hits for "test" from earlier runs.
        pool = account_pool.AccountPool()
        acct = pool.accts[0]

        pool.mark_exhausted(acct)
        pool.mark_exhausted(acct)
        assert pool.state["test"]["exh_hits"] == 2

        pool.mark_ok(acct)
        assert pool.state["test"].get("exh_hits", 0) == 0

        # ...and the next hit starts from the base cooldown again.
        sent = time.time()
        pool.mark_exhausted(acct)
        assert pool.state["test"]["cooldown_until"] - sent <= account_pool._COOLDOWN_DEFAULT + 1

    def test_mark_ok_clears_cooldown(self):
        """mark_ok() clears cooldown_until."""
        pool = account_pool.AccountPool()
        acct = pool.accts[0]

        pool.mark_exhausted(acct)
        assert pool.state["test"]["cooldown_until"] > time.time()

        pool.mark_ok(acct)
        assert "cooldown_until" not in pool.state["test"]
        assert pool._healthy(acct)

    def test_mark_ok_preserves_use_count(self):
        """mark_ok() does not reset use_count (cumulative load tracking)."""
        # Same real-state-file contamination: use_count started non-zero.
        pool = account_pool.AccountPool()
        acct = pool.accts[0]

        pool.record_use(acct)
        pool.record_use(acct)
        assert pool.state["test"]["use_count"] == 2

        pool.mark_ok(acct)

        assert pool.state["test"]["use_count"] == 2


# ============================================================================
# Test Exhausted Flag Persistence
# ============================================================================

class TestExhaustedFlagPersistence(_TempPaths):
    """Test exhausted flag file is written/cleared correctly."""

    def setup_method(self, method):
        super().setup_method(method)
        self.write_cfg([{"name": "test", "type": "login"}])

    def test_write_exhausted_flag_when_all_cooling(self):
        """_write_exhausted_flag() creates flag when all accounts cooling."""
        # The assertion targeted a temp path the module never used, so the flag was
        # (and stayed) missing there.
        pool = account_pool.AccountPool()
        pool.mark_exhausted(pool.accts[0])

        assert os.path.exists(self.flag_path)
        with open(self.flag_path) as f:
            flag_data = json.load(f)
        assert flag_data["until"] == pool.state["test"]["cooldown_until"]
        assert flag_data["until"] > time.time()

    def test_clear_exhausted_flag_when_account_recovers(self):
        """_write_exhausted_flag() removes flag when any account healthy."""
        pool = account_pool.AccountPool()
        acct = pool.accts[0]

        pool.mark_exhausted(acct)
        assert os.path.exists(self.flag_path)

        pool.mark_ok(acct)
        assert not os.path.exists(self.flag_path)

    def test_exhausted_flag_contains_valid_until_timestamp(self):
        """Exhausted flag 'until' field is a valid future timestamp."""
        pool = account_pool.AccountPool()
        pool.mark_exhausted(pool.accts[0])

        with open(self.flag_path) as f:
            flag_data = json.load(f)

        until = float(flag_data["until"])
        now = time.time()

        assert until > now
        # Never longer than the documented 6h backoff ceiling.
        assert until <= now + account_pool._COOLDOWN_MAX_DEFAULT


# ============================================================================
# Test API Billing Guard
# ============================================================================

class TestAPIBillingAllowed(_TempPaths):
    """Test _api_billing_allowed() with guard and env fallback."""

    def test_api_billing_default_deny(self):
        """_api_billing_allowed() returns False by default."""
        os.environ.pop("ORCH_ALLOW_API_BILLING", None)
        assert account_pool._api_billing_allowed() is False

    def test_api_billing_follows_subscription_guard(self):
        """_api_billing_allowed() mirrors subscription_guard.is_api_allowed().

        Was test_api_billing_respects_env_var, which set ORCH_ALLOW_API_BILLING and
        expected True. That env var is only the FALLBACK for when subscription_guard
        cannot be imported; subscription_guard is importable here (and reads its own
        switches at import), so the guard's answer is what counts."""
        os.environ["ORCH_ALLOW_API_BILLING"] = "false"
        with patch.object(subscription_guard, "is_api_allowed", lambda: True):
            assert account_pool._api_billing_allowed() is True

        os.environ["ORCH_ALLOW_API_BILLING"] = "true"
        with patch.object(subscription_guard, "is_api_allowed", lambda: False):
            assert account_pool._api_billing_allowed() is False

    def test_api_billing_env_fallback_is_case_insensitive(self):
        """With the guard unavailable, ORCH_ALLOW_API_BILLING decides, any casing.

        Was test_api_billing_case_insensitive, which never made the guard
        unavailable, so the env var it set was ignored."""
        original = sys.modules.get("subscription_guard")
        sys.modules["subscription_guard"] = None   # makes `import` raise ImportError
        try:
            for value, expected in (("TRUE", True), ("True", True), ("true", True),
                                    ("False", False), ("no", False)):
                os.environ["ORCH_ALLOW_API_BILLING"] = value
                assert account_pool._api_billing_allowed() is expected
        finally:
            if original is not None:
                sys.modules["subscription_guard"] = original
            else:
                del sys.modules["subscription_guard"]

    def test_api_billing_fail_soft_on_guard_error(self):
        """A guard that raises is treated as 'not allowed', not propagated."""
        os.environ.pop("ORCH_ALLOW_API_BILLING", None)

        def _boom():
            raise RuntimeError("control_flags unreachable")

        with patch.object(subscription_guard, "is_api_allowed", _boom):
            assert account_pool._api_billing_allowed() is False


# ============================================================================
# Fail-soft behaviour (was TestFailSoftDocstrings)
# ============================================================================

class TestFailSoftBehaviour(_TempPaths):
    """The four functions the old TestFailSoftDocstrings only grepped for the word
    "Fail-soft" in. Asserting on docstring text proves nothing about the code (and
    could be 'fixed' by editing a comment), so each test now drives the failure the
    docstring is about — CLAUDE.md rule 2: I/O errors must not wedge the runner."""

    def test_api_billing_allowed_fails_soft(self):
        """Guard blow-up -> deny (never bill the API on an error path)."""
        os.environ.pop("ORCH_ALLOW_API_BILLING", None)

        def _boom():
            raise RuntimeError("guard exploded")

        with patch.object(subscription_guard, "is_api_allowed", _boom):
            assert account_pool._api_billing_allowed() is False

    def test_claude_exhausted_fails_soft(self):
        """Pool construction blow-up -> False, so pick() keeps using Claude."""
        def _boom():
            raise RuntimeError("config unreadable")

        with patch.object(account_pool, "AccountPool", _boom):
            assert account_pool.claude_exhausted() is False

    def test_save_fails_soft_and_rotation_still_works(self):
        """An unwritable state file must not break the in-memory rotation."""
        blocker = os.path.join(self.temp_dir, "blocker")
        with open(blocker, "w") as f:
            f.write("not a directory")
        account_pool.STATE = os.path.join(blocker, "accounts_state.json")
        self.write_cfg([{"name": "a1", "type": "login"}, {"name": "a2", "type": "login"}])

        pool = account_pool.AccountPool()
        a1 = [a for a in pool.accts if a["name"] == "a1"][0]

        assert pool.mark_exhausted(a1) == "a2"      # rotated despite the failed write
        assert pool.current()["name"] == "a2"

    def test_load_state_fails_soft_on_unreadable_path(self):
        """A directory where the state file should be -> {} instead of IsADirectoryError."""
        os.remove(self.state_path) if os.path.exists(self.state_path) else None
        os.makedirs(self.state_path)

        pool = account_pool.AccountPool()
        assert pool.state == {}


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
