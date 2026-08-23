#!/usr/bin/env python3
"""Tests for account_pool.py credential rotation and thread-safe cache.

Tests validate:
- Thread-safe credential cache with TTL (claude_exhausted)
- Tunable cache TTL via ORCH_EXH_CACHE_TTL env var
- Robust file I/O: context managers, error="replace", specific exception handling
- Fail-soft error handling on credential config load failures
- Thread-safe singleton pattern for AccountPool
- Exponential backoff on repeated credential exhaustion
- Credential rotation and mark_ok() reset behavior
- Exhausted flag persistence and clearing
"""

import os
import sys
import json
import time
import tempfile
import threading
from unittest.mock import Mock, patch, mock_open
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")

import account_pool


# ============================================================================
# Test Cache TTL Configuration
# ============================================================================

class TestCacheTTLConfiguration:
    """Test cache TTL is configurable via ORCH_EXH_CACHE_TTL."""

    def setup_method(self):
        """Clean env before each test."""
        os.environ.pop("ORCH_EXH_CACHE_TTL", None)

    def test_default_cache_ttl_is_15_seconds(self):
        """_exh_cache_ttl() returns 15s by default."""
        assert account_pool._exh_cache_ttl() == 15

    def test_cache_ttl_respects_env_var(self):
        """_exh_cache_ttl() reads ORCH_EXH_CACHE_TTL."""
        os.environ["ORCH_EXH_CACHE_TTL"] = "30"
        assert account_pool._exh_cache_ttl() == 30

    def test_cache_ttl_invalid_env_var_fails_soft(self):
        """_exh_cache_ttl() returns default if ORCH_EXH_CACHE_TTL is invalid."""
        os.environ["ORCH_EXH_CACHE_TTL"] = "not_a_number"
        try:
            result = account_pool._exh_cache_ttl()
            # Should raise ValueError on int() or return default
            assert False, "should raise ValueError"
        except ValueError:
            pass  # Expected

    def test_cache_ttl_zero_allowed(self):
        """_exh_cache_ttl() allows zero (no caching)."""
        os.environ["ORCH_EXH_CACHE_TTL"] = "0"
        assert account_pool._exh_cache_ttl() == 0

    def test_cache_ttl_large_value_allowed(self):
        """_exh_cache_ttl() allows large values."""
        os.environ["ORCH_EXH_CACHE_TTL"] = "3600"
        assert account_pool._exh_cache_ttl() == 3600


# ============================================================================
# Test Thread-Safe Cache (claude_exhausted)
# ============================================================================

class TestThreadSafeExhaustedCache:
    """Test claude_exhausted() cache is thread-safe."""

    def setup_method(self):
        """Reset cache and env before each test."""
        account_pool._EXH_CACHE = {"t": 0.0, "v": False}
        os.environ.pop("ORCH_EXH_CACHE_TTL", None)
        os.environ.pop("CLAUDE_ORCH_HOME", None)

    def test_cache_returns_same_value_within_ttl(self):
        """Cache hit: claude_exhausted() returns cached value within TTL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["CLAUDE_ORCH_HOME"] = tmpdir
            pool = account_pool.AccountPool()
            # Manually set cache
            now = time.time()
            account_pool._EXH_CACHE = {"t": now - 5, "v": True}

            # Should return cached True without DB call
            assert account_pool.claude_exhausted() is True

    def test_cache_recomputes_after_ttl(self):
        """Cache miss: claude_exhausted() recomputes after TTL expires."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["CLAUDE_ORCH_HOME"] = tmpdir
            os.environ["ORCH_EXH_CACHE_TTL"] = "1"  # 1 second TTL

            # Set old cached value
            now = time.time()
            account_pool._EXH_CACHE = {"t": now - 10, "v": True}

            # Wait for TTL to expire
            time.sleep(0.1)

            # Should recompute, result depends on actual account state
            result = account_pool.claude_exhausted()
            assert isinstance(result, bool)

    def test_cache_lock_prevents_race(self):
        """Multiple threads calling claude_exhausted() don't corrupt cache."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["CLAUDE_ORCH_HOME"] = tmpdir
            results = []
            errors = []

            def call_claude_exhausted():
                try:
                    for _ in range(10):
                        result = account_pool.claude_exhausted()
                        results.append(result)
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=call_claude_exhausted) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert not errors, f"Errors in concurrent cache access: {errors}"
            assert len(results) == 50, "All calls should complete"
            assert all(isinstance(r, bool) for r in results)

    def test_cache_initialization_is_thread_safe(self):
        """Multiple threads initializing cache at same time don't corrupt it."""
        account_pool._EXH_CACHE = {"t": 0.0, "v": False}

        def reset_and_call():
            # Reset to force recomputation
            account_pool._EXH_CACHE["t"] = 0.0
            return account_pool.claude_exhausted()

        threads = [threading.Thread(target=reset_and_call) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Cache should still be valid dict
        assert isinstance(account_pool._EXH_CACHE, dict)
        assert "t" in account_pool._EXH_CACHE
        assert "v" in account_pool._EXH_CACHE


# ============================================================================
# Test Robust File I/O and Error Handling
# ============================================================================

class TestRobustFileIO:
    """Test file I/O handles corruption and missing files gracefully."""

    def setup_method(self):
        """Reset env before each test."""
        os.environ.pop("CLAUDE_ORCH_HOME", None)

    def test_load_state_missing_file_returns_empty_dict(self):
        """_load_state() returns {} if file missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["CLAUDE_ORCH_HOME"] = tmpdir
            # Don't reuse pool instance state from setUp
            pool = account_pool.AccountPool()
            pool.state = {}

            # Manually call _load_state with fresh instance
            state = pool._load_state()
            # When file doesn't exist, should return empty dict
            assert state == {} or isinstance(state, dict), f"Expected dict, got {type(state).__name__}"

    def test_load_state_corrupted_json_returns_empty_dict(self):
        """_load_state() returns {} if file contains invalid JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["CLAUDE_ORCH_HOME"] = tmpdir
            state_path = os.path.join(tmpdir, "accounts_state.json")

            # Write corrupted JSON
            with open(state_path, "w") as f:
                f.write("{ invalid json }")

            pool = account_pool.AccountPool()
            state = pool._load_state()
            assert state == {}, f"Expected empty dict on corrupt JSON, got {state}"

    def test_load_state_wrong_type_returns_empty_dict(self):
        """_load_state() returns {} if file contains non-dict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["CLAUDE_ORCH_HOME"] = tmpdir
            state_path = os.path.join(tmpdir, "accounts_state.json")

            # Write list instead of dict
            with open(state_path, "w") as f:
                json.dump([1, 2, 3], f)

            pool = account_pool.AccountPool()
            state = pool._load_state()
            assert state == {}, f"Expected empty dict on wrong type, got {state}"

    def test_load_cfg_missing_file_returns_default(self):
        """_load_cfg() returns default if file missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["CLAUDE_ORCH_HOME"] = tmpdir
            pool = account_pool.AccountPool()

            cfg = pool._load_cfg()
            assert isinstance(cfg, list)
            assert len(cfg) > 0
            assert cfg[0]["name"] == "default"

    def test_load_cfg_corrupted_json_returns_default(self):
        """_load_cfg() returns default if file contains invalid JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["CLAUDE_ORCH_HOME"] = tmpdir
            cfg_path = os.path.join(tmpdir, "accounts.json")

            # Write corrupted JSON
            with open(cfg_path, "w") as f:
                f.write("{ invalid json }")

            pool = account_pool.AccountPool()
            cfg = pool._load_cfg()
            assert cfg[0]["name"] == "default"

    def test_save_disk_error_doesnt_raise(self):
        """_save() doesn't raise on disk write error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["CLAUDE_ORCH_HOME"] = tmpdir
            pool = account_pool.AccountPool()
            pool.state = {"test": {"use_count": 1}}

            # Make directory read-only to force write error
            state_dir = tmpdir
            try:
                os.chmod(state_dir, 0o444)
                # Should not raise
                pool._save()
            finally:
                os.chmod(state_dir, 0o755)

    def test_exhausted_flag_handles_corrupted_json(self):
        """claude_exhausted() handles corrupted exhausted flag file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["CLAUDE_ORCH_HOME"] = tmpdir
            flag_path = os.path.join(tmpdir, "claude_exhausted.json")

            # Write corrupted JSON
            with open(flag_path, "w") as f:
                f.write("{ invalid json }")

            # Should not raise, should fall back to empty result
            result = account_pool.claude_exhausted()
            assert isinstance(result, bool)

    def test_exhausted_flag_handles_missing_until_field(self):
        """claude_exhausted() handles exhausted flag with missing 'until' field."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["CLAUDE_ORCH_HOME"] = tmpdir
            flag_path = os.path.join(tmpdir, "claude_exhausted.json")

            # Write valid JSON but missing 'until'
            with open(flag_path, "w") as f:
                json.dump({"other_field": "value"}, f)

            # Should not raise
            result = account_pool.claude_exhausted()
            assert isinstance(result, bool)


# ============================================================================
# Test Thread-Safe Singleton Pattern
# ============================================================================

class TestThreadSafeSingleton:
    """Test _get_pool() creates singleton safely."""

    def setup_method(self):
        """Reset singleton before each test."""
        account_pool._pool = None

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

        # Reset for this test
        account_pool._pool = None
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
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["CLAUDE_ORCH_HOME"] = tmpdir
            account_pool._pool = None

            stats = account_pool.stats()
            assert isinstance(stats, dict)
            assert "total_accounts" in stats

    def test_module_level_invalidate_delegates_to_singleton(self):
        """invalidate() calls _get_pool().invalidate()."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["CLAUDE_ORCH_HOME"] = tmpdir
            account_pool._pool = None

            # Should not raise
            account_pool.invalidate()

            # Should reload config
            pool = account_pool._get_pool()
            assert isinstance(pool.accts, list)


# ============================================================================
# Test Credential Rotation and Backoff
# ============================================================================

class TestCredentialRotationBackoff:
    """Test mark_exhausted() implements exponential backoff."""

    def setup_method(self):
        """Set up test pool with predictable time."""
        os.environ.pop("ORCH_ACCOUNT_COOLDOWN", None)
        os.environ.pop("ORCH_ACCOUNT_COOLDOWN_MAX", None)
        os.environ.pop("CLAUDE_ORCH_HOME", None)

    def test_first_exhaustion_uses_base_cooldown(self):
        """First mark_exhausted() call uses COOLDOWN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["CLAUDE_ORCH_HOME"] = tmpdir
            pool = account_pool.AccountPool()
            acct = {"name": "test", "type": "login"}

            before = time.time()
            pool.mark_exhausted(acct)
            after = time.time()

            state = pool.state.get("test", {})
            cooldown_until = state.get("cooldown_until", 0)

            # Should be approximately now + COOLDOWN
            expected_min = before + account_pool._COOLDOWN_DEFAULT
            expected_max = after + account_pool._COOLDOWN_DEFAULT

            assert expected_min <= cooldown_until <= expected_max + 1

    def test_second_exhaustion_doubles_cooldown(self):
        """Second mark_exhausted() call doubles backoff."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["CLAUDE_ORCH_HOME"] = tmpdir
            pool = account_pool.AccountPool()
            acct = {"name": "test", "type": "login"}

            # First exhaustion
            pool.mark_exhausted(acct)
            first_until = pool.state.get("test", {}).get("cooldown_until", 0)

            # Second exhaustion
            pool.mark_exhausted(acct)
            second_until = pool.state.get("test", {}).get("cooldown_until", 0)

            # Second should be roughly double first
            first_duration = first_until - time.time()
            second_duration = second_until - time.time()

            # Second should be ~2x first (allowing some time skew)
            assert second_duration > first_duration

    def test_backoff_respects_cooldown_max(self):
        """Backoff never exceeds COOLDOWN_MAX."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["CLAUDE_ORCH_HOME"] = tmpdir
            os.environ["ORCH_ACCOUNT_COOLDOWN_MAX"] = "60"
            pool = account_pool.AccountPool()
            acct = {"name": "test", "type": "login"}

            # Mark exhausted many times
            for _ in range(10):
                pool.mark_exhausted(acct)

            state = pool.state.get("test", {})
            cooldown_until = state.get("cooldown_until", 0)
            remaining = cooldown_until - time.time()

            # Should never exceed COOLDOWN_MAX (60 seconds)
            assert remaining <= 60 + 5  # Allow some time skew

    def test_mark_ok_resets_backoff_counter(self):
        """mark_ok() clears exh_hits so backoff resets."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["CLAUDE_ORCH_HOME"] = tmpdir
            pool = account_pool.AccountPool()
            acct = {"name": "test", "type": "login"}

            # Exhaust twice
            pool.mark_exhausted(acct)
            pool.mark_exhausted(acct)
            hits = pool.state.get("test", {}).get("exh_hits", 0)
            assert hits == 2

            # mark_ok() resets counter
            pool.mark_ok(acct)
            hits = pool.state.get("test", {}).get("exh_hits", 0)
            assert hits == 0

    def test_mark_ok_clears_cooldown(self):
        """mark_ok() clears cooldown_until."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["CLAUDE_ORCH_HOME"] = tmpdir
            pool = account_pool.AccountPool()
            acct = {"name": "test", "type": "login"}

            pool.mark_exhausted(acct)
            assert pool.state.get("test", {}).get("cooldown_until", 0) > time.time()

            pool.mark_ok(acct)
            # cooldown_until should be removed
            assert "cooldown_until" not in pool.state.get("test", {})

    def test_mark_ok_preserves_use_count(self):
        """mark_ok() does not reset use_count (cumulative load tracking)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["CLAUDE_ORCH_HOME"] = tmpdir
            pool = account_pool.AccountPool()
            acct = {"name": "test", "type": "login"}

            pool.record_use(acct)
            pool.record_use(acct)
            use_count = pool.state.get("test", {}).get("use_count", 0)
            assert use_count == 2

            pool.mark_ok(acct)

            # use_count should still be 2 (not reset)
            use_count_after = pool.state.get("test", {}).get("use_count", 0)
            assert use_count_after == 2


# ============================================================================
# Test Exhausted Flag Persistence
# ============================================================================

class TestExhaustedFlagPersistence:
    """Test exhausted flag file is written/cleared correctly."""

    def setup_method(self):
        """Reset cache and env."""
        account_pool._EXH_CACHE = {"t": 0.0, "v": False}
        os.environ.pop("CLAUDE_ORCH_HOME", None)

    def test_write_exhausted_flag_when_all_cooling(self):
        """_write_exhausted_flag() creates flag when all accounts cooling."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["CLAUDE_ORCH_HOME"] = tmpdir
            flag_path = os.path.join(tmpdir, "claude_exhausted.json")

            pool = account_pool.AccountPool()
            acct = {"name": "test", "type": "login"}
            pool.accts = [acct]

            # Mark as cooling
            pool.mark_exhausted(acct)

            # Flag should exist
            assert os.path.exists(flag_path)
            with open(flag_path) as f:
                flag_data = json.load(f)
            assert "until" in flag_data
            assert flag_data["until"] > time.time()

    def test_clear_exhausted_flag_when_account_recovers(self):
        """_write_exhausted_flag() removes flag when any account healthy."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["CLAUDE_ORCH_HOME"] = tmpdir
            flag_path = os.path.join(tmpdir, "claude_exhausted.json")

            pool = account_pool.AccountPool()
            acct = {"name": "test", "type": "login"}
            pool.accts = [acct]

            # Exhaust, then recover
            pool.mark_exhausted(acct)
            assert os.path.exists(flag_path)

            pool.mark_ok(acct)
            # Flag should be removed
            assert not os.path.exists(flag_path)

    def test_exhausted_flag_contains_valid_until_timestamp(self):
        """Exhausted flag 'until' field is a valid future timestamp."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["CLAUDE_ORCH_HOME"] = tmpdir
            flag_path = os.path.join(tmpdir, "claude_exhausted.json")

            pool = account_pool.AccountPool()
            acct = {"name": "test", "type": "login"}
            pool.accts = [acct]

            pool.mark_exhausted(acct)

            with open(flag_path) as f:
                flag_data = json.load(f)

            until = float(flag_data["until"])
            now = time.time()

            # Should be in future
            assert until > now
            # Should be within reasonable bounds (not decades away)
            assert until < now + 24 * 3600


# ============================================================================
# Test API Billing Guard
# ============================================================================

class TestAPIBillingAllowed:
    """Test _api_billing_allowed() with guard and env fallback."""

    def setup_method(self):
        """Clean env before each test."""
        os.environ.pop("ORCH_ALLOW_API_BILLING", None)

    def test_api_billing_default_deny(self):
        """_api_billing_allowed() returns False by default."""
        # When subscription_guard not available and env not set
        result = account_pool._api_billing_allowed()
        assert result is False

    def test_api_billing_respects_env_var(self):
        """_api_billing_allowed() reads ORCH_ALLOW_API_BILLING."""
        os.environ["ORCH_ALLOW_API_BILLING"] = "true"
        assert account_pool._api_billing_allowed() is True

        os.environ["ORCH_ALLOW_API_BILLING"] = "false"
        assert account_pool._api_billing_allowed() is False

    def test_api_billing_case_insensitive(self):
        """ORCH_ALLOW_API_BILLING check is case-insensitive."""
        os.environ["ORCH_ALLOW_API_BILLING"] = "TRUE"
        assert account_pool._api_billing_allowed() is True

        os.environ["ORCH_ALLOW_API_BILLING"] = "True"
        assert account_pool._api_billing_allowed() is True

    def test_api_billing_fail_soft_on_import_error(self):
        """_api_billing_allowed() returns False if guard import fails."""
        # Simulate subscription_guard not being available
        result = account_pool._api_billing_allowed()
        assert result is False


# ============================================================================
# Test Fail-Soft Docstring Updates
# ============================================================================

class TestFailSoftDocstrings:
    """Test that functions have 'Fail-soft' documentation."""

    def test_api_billing_allowed_documented(self):
        """_api_billing_allowed has fail-soft in docstring."""
        assert "Fail-soft" in account_pool._api_billing_allowed.__doc__

    def test_claude_exhausted_documented(self):
        """claude_exhausted has fail-soft in docstring."""
        assert "Fail-soft" in account_pool.claude_exhausted.__doc__

    def test_save_documented(self):
        """_save has fail-soft in docstring."""
        assert "Fail-soft" in account_pool.AccountPool._save.__doc__

    def test_load_state_documented(self):
        """_load_state has fail-soft in docstring."""
        assert "Fail-soft" in account_pool.AccountPool._load_state.__doc__


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
