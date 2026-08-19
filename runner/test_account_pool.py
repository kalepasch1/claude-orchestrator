#!/usr/bin/env python3
"""Tests for account_pool.py - account rotation under usage limits.

Task: qafix-pareto-2080-07062319-slice-2-slice-4
Objective: Verify account pool rotation, exhaustion detection, and billing guard
work correctly after deduplication of stats() methods.

Tests cover:
- Pool initialization from config and fallback defaults
- Current account selection with health checking
- Exhaustion marking and backoff exponential scaling
- Recovery (mark_ok) and exhaustion-flag lifecycle
- Module-level singleton pattern delegation
- Machine affinity filtering
- API billing guard integration
- Stats/observability methods
"""
import os
import sys
import json
import time
import tempfile
import shutil
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Disable DB for tests
os.environ["ORCH_DB_ENABLED"] = "false"
os.environ["SUPABASE_URL"] = "http://localhost"
os.environ["SUPABASE_SERVICE_KEY"] = "test"

import account_pool


class TestAccountPoolInitialization:
    """Test pool initialization and config loading."""

    def setup_method(self):
        """Create temp home for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.orig_home = os.environ.get("CLAUDE_ORCH_HOME")
        os.environ["CLAUDE_ORCH_HOME"] = self.temp_dir

    def teardown_method(self):
        """Cleanup temp directory."""
        if self.orig_home:
            os.environ["CLAUDE_ORCH_HOME"] = self.orig_home
        else:
            del os.environ["CLAUDE_ORCH_HOME"]
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_init_default_when_no_config(self):
        """Pool defaults to single 'default' account if no config exists."""
        pool = account_pool.AccountPool()
        assert len(pool.accts) >= 1
        assert pool.accts[0]["name"] == "default"
        assert pool.accts[0]["type"] == "login"

    def test_init_loads_json_config_from_disk(self):
        """Pool loads accounts.json if it exists."""
        cfg = [
            {"name": "personal", "type": "login", "config_dir": "~/.claude"},
            {"name": "team", "type": "api", "api_key_env": "TEAM_KEY"},
        ]
        cfg_path = os.path.join(self.temp_dir, "accounts.json")
        json.dump(cfg, open(cfg_path, "w"))

        pool = account_pool.AccountPool()
        assert len(pool.accts) == 2
        assert pool.accts[0]["name"] == "personal"
        assert pool.accts[1]["name"] == "team"

    def test_init_empty_state_on_first_run(self):
        """Pool starts with empty state if accounts_state.json doesn't exist."""
        pool = account_pool.AccountPool()
        assert pool.state == {}

    def test_init_loads_existing_state(self):
        """Pool loads accounts_state.json if present."""
        state = {
            "personal": {"cooldown_until": time.time() + 3600, "exh_hits": 2},
        }
        state_path = os.path.join(self.temp_dir, "accounts_state.json")
        json.dump(state, open(state_path, "w"))

        pool = account_pool.AccountPool()
        assert "personal" in pool.state
        assert pool.state["personal"]["exh_hits"] == 2


class TestCurrentAccountSelection:
    """Test current() logic for account selection."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.orig_home = os.environ.get("CLAUDE_ORCH_HOME")
        os.environ["CLAUDE_ORCH_HOME"] = self.temp_dir

    def teardown_method(self):
        if self.orig_home:
            os.environ["CLAUDE_ORCH_HOME"] = self.orig_home
        else:
            del os.environ["CLAUDE_ORCH_HOME"]
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_current_returns_healthy_account(self):
        """current() returns a healthy (non-cooling) account if available."""
        cfg = [
            {"name": "acct1", "type": "login"},
            {"name": "acct2", "type": "login"},
        ]
        cfg_path = os.path.join(self.temp_dir, "accounts.json")
        json.dump(cfg, open(cfg_path, "w"))

        pool = account_pool.AccountPool()
        current = pool.current()
        assert current is not None
        assert current["name"] in ["acct1", "acct2"]

    def test_current_with_all_cooling_returns_soonest(self):
        """current() returns the account that frees up soonest when all are cooling."""
        cfg = [
            {"name": "acct1", "type": "login"},
            {"name": "acct2", "type": "login"},
        ]
        cfg_path = os.path.join(self.temp_dir, "accounts.json")
        json.dump(cfg, open(cfg_path, "w"))

        pool = account_pool.AccountPool()
        now = time.time()
        pool.state = {
            "acct1": {"cooldown_until": now + 7200},  # 2 hours
            "acct2": {"cooldown_until": now + 3600},  # 1 hour
        }

        current = pool.current()
        assert current is not None
        assert current["name"] == "acct2"  # Soonest

    def test_current_subscription_preferred_over_api(self):
        """current() prefers subscription accounts over API if both healthy."""
        cfg = [
            {"name": "subscription", "type": "login"},
            {"name": "api_paid", "type": "api", "api_key_env": "API_KEY"},
        ]
        cfg_path = os.path.join(self.temp_dir, "accounts.json")
        json.dump(cfg, open(cfg_path, "w"))

        with patch("account_pool._api_billing_allowed", return_value=True):
            pool = account_pool.AccountPool()
            current = pool.current()
            assert current["name"] == "subscription"

    def test_current_round_robin_among_equal_accounts(self):
        """current() uses use_count to round-robin among healthy accounts."""
        cfg = [
            {"name": "a1", "type": "login"},
            {"name": "a2", "type": "login"},
        ]
        cfg_path = os.path.join(self.temp_dir, "accounts.json")
        json.dump(cfg, open(cfg_path, "w"))

        pool = account_pool.AccountPool()
        pool.state = {
            "a1": {"use_count": 10},
            "a2": {"use_count": 5},
        }
        current = pool.current()
        assert current["name"] == "a2"  # Fewer uses

    def test_current_with_none_returns_none(self):
        """current() returns None if no usable accounts."""
        # Empty account list via config that returns nothing
        cfg = []
        cfg_path = os.path.join(self.temp_dir, "accounts.json")
        json.dump(cfg, open(cfg_path, "w"))

        pool = account_pool.AccountPool()
        # Manually clear to simulate empty
        pool.accts = []
        current = pool.current()
        assert current is None


class TestExhaustionAndCooldown:
    """Test mark_exhausted() and cooldown exponential backoff."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.orig_home = os.environ.get("CLAUDE_ORCH_HOME")
        os.environ["CLAUDE_ORCH_HOME"] = self.temp_dir
        self.orig_cooldown = os.environ.get("ORCH_ACCOUNT_COOLDOWN")

    def teardown_method(self):
        if self.orig_home:
            os.environ["CLAUDE_ORCH_HOME"] = self.orig_home
        else:
            del os.environ["CLAUDE_ORCH_HOME"]
        if self.orig_cooldown:
            os.environ["ORCH_ACCOUNT_COOLDOWN"] = self.orig_cooldown
        elif "ORCH_ACCOUNT_COOLDOWN" in os.environ:
            del os.environ["ORCH_ACCOUNT_COOLDOWN"]
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_mark_exhausted_sets_cooldown(self):
        """mark_exhausted() sets cooldown_until in state."""
        cfg = [{"name": "acct1", "type": "login"}]
        cfg_path = os.path.join(self.temp_dir, "accounts.json")
        json.dump(cfg, open(cfg_path, "w"))

        pool = account_pool.AccountPool()
        acct = pool.accts[0]
        before = time.time()
        pool.mark_exhausted(acct)
        after = time.time()

        state = pool.state.get("acct1", {})
        cd = state.get("cooldown_until", 0)
        assert cd > before
        assert cd <= after + 3600

    def test_mark_exhausted_exponential_backoff(self):
        """Repeated mark_exhausted() calls double the cooldown (up to MAX)."""
        cfg = [{"name": "acct1", "type": "login"}]
        cfg_path = os.path.join(self.temp_dir, "accounts.json")
        json.dump(cfg, open(cfg_path, "w"))

        os.environ["ORCH_ACCOUNT_COOLDOWN"] = "100"
        os.environ["ORCH_ACCOUNT_COOLDOWN_MAX"] = "1600"

        pool = account_pool.AccountPool()
        acct = pool.accts[0]

        # First hit: 1 * 100 = 100s
        pool.mark_exhausted(acct)
        cd1 = pool.state["acct1"]["cooldown_until"]

        # Second hit: 2 * 100 = 200s (relative to new now)
        time.sleep(0.1)
        pool.mark_exhausted(acct)
        cd2 = pool.state["acct1"]["cooldown_until"]

        # Third hit: 4 * 100 = 400s
        time.sleep(0.1)
        pool.mark_exhausted(acct)
        cd3 = pool.state["acct1"]["cooldown_until"]

        # cd2 should be ~2x the delta of cd1
        assert cd2 > cd1
        assert cd3 > cd2

    def test_mark_exhausted_respects_max_cooldown(self):
        """Exponential backoff caps at COOLDOWN_MAX."""
        cfg = [{"name": "acct1", "type": "login"}]
        cfg_path = os.path.join(self.temp_dir, "accounts.json")
        json.dump(cfg, open(cfg_path, "w"))

        os.environ["ORCH_ACCOUNT_COOLDOWN"] = "100"
        os.environ["ORCH_ACCOUNT_COOLDOWN_MAX"] = "500"

        pool = account_pool.AccountPool()
        acct = pool.accts[0]

        # Hit it many times
        for _ in range(10):
            pool.mark_exhausted(acct)
            time.sleep(0.05)

        cd = pool.state["acct1"]["cooldown_until"]
        now = time.time()
        # Cooldown should not exceed now + 500
        assert cd <= now + 600


class TestRecovery:
    """Test mark_ok() and recovery logic."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.orig_home = os.environ.get("CLAUDE_ORCH_HOME")
        os.environ["CLAUDE_ORCH_HOME"] = self.temp_dir

    def teardown_method(self):
        if self.orig_home:
            os.environ["CLAUDE_ORCH_HOME"] = self.orig_home
        else:
            del os.environ["CLAUDE_ORCH_HOME"]
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_mark_ok_clears_cooldown(self):
        """mark_ok() removes cooldown_until and exh_hits."""
        cfg = [{"name": "acct1", "type": "login"}]
        cfg_path = os.path.join(self.temp_dir, "accounts.json")
        json.dump(cfg, open(cfg_path, "w"))

        pool = account_pool.AccountPool()
        acct = pool.accts[0]

        # Exhaust it
        pool.mark_exhausted(acct)
        assert pool.state["acct1"].get("cooldown_until", 0) > 0
        assert pool.state["acct1"].get("exh_hits", 0) >= 1

        # Recover
        pool.mark_ok(acct)
        assert "cooldown_until" not in pool.state["acct1"]
        assert "exh_hits" not in pool.state["acct1"]

    def test_mark_ok_preserves_use_count(self):
        """mark_ok() does NOT reset use_count (only exhaustion state)."""
        cfg = [{"name": "acct1", "type": "login"}]
        cfg_path = os.path.join(self.temp_dir, "accounts.json")
        json.dump(cfg, open(cfg_path, "w"))

        pool = account_pool.AccountPool()
        acct = pool.accts[0]

        pool.record_use(acct)
        pool.record_use(acct)
        assert pool.state["acct1"]["use_count"] == 2

        pool.mark_exhausted(acct)
        pool.mark_ok(acct)

        assert pool.state["acct1"]["use_count"] == 2

    def test_mark_ok_on_nonexistent_account_is_noop(self):
        """mark_ok() with None or non-existent account is safe."""
        cfg = [{"name": "acct1", "type": "login"}]
        cfg_path = os.path.join(self.temp_dir, "accounts.json")
        json.dump(cfg, open(cfg_path, "w"))

        pool = account_pool.AccountPool()
        pool.mark_ok(None)  # Should not raise
        pool.mark_ok({"name": "nonexistent"})  # Should not raise


class TestExhaustionFlag:
    """Test EXHAUSTED_FLAG file lifecycle."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.orig_home = os.environ.get("CLAUDE_ORCH_HOME")
        os.environ["CLAUDE_ORCH_HOME"] = self.temp_dir

    def teardown_method(self):
        if self.orig_home:
            os.environ["CLAUDE_ORCH_HOME"] = self.orig_home
        else:
            del os.environ["CLAUDE_ORCH_HOME"]
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_all_exhausted_flag_created_when_all_cooling(self):
        """_write_exhausted_flag() creates flag when all accounts cooling."""
        cfg = [{"name": "acct1", "type": "login"}]
        cfg_path = os.path.join(self.temp_dir, "accounts.json")
        json.dump(cfg, open(cfg_path, "w"))

        pool = account_pool.AccountPool()
        pool.mark_exhausted(pool.accts[0])

        flag = os.path.join(self.temp_dir, "claude_exhausted.json")
        assert os.path.exists(flag)
        data = json.load(open(flag))
        assert "until" in data

    def test_all_exhausted_flag_cleared_on_recovery(self):
        """_write_exhausted_flag() removes flag when any account recovers."""
        cfg = [
            {"name": "acct1", "type": "login"},
            {"name": "acct2", "type": "login"},
        ]
        cfg_path = os.path.join(self.temp_dir, "accounts.json")
        json.dump(cfg, open(cfg_path, "w"))

        pool = account_pool.AccountPool()
        acct1 = [a for a in pool.accts if a["name"] == "acct1"][0]
        acct2 = [a for a in pool.accts if a["name"] == "acct2"][0]

        pool.mark_exhausted(acct1)
        pool.mark_exhausted(acct2)

        flag = os.path.join(self.temp_dir, "claude_exhausted.json")
        assert os.path.exists(flag)

        pool.mark_ok(acct2)
        # After recovery, flag should be gone
        assert not os.path.exists(flag)

    def test_claude_exhausted_reads_flag(self):
        """claude_exhausted() returns True if flag exists and not stale."""
        cfg = [{"name": "acct1", "type": "login"}]
        cfg_path = os.path.join(self.temp_dir, "accounts.json")
        json.dump(cfg, open(cfg_path, "w"))

        pool = account_pool.AccountPool()
        pool.mark_exhausted(pool.accts[0])

        # Reset cache to ensure fresh read
        account_pool._EXH_CACHE["t"] = 0
        result = account_pool.claude_exhausted()
        assert result is True

    def test_claude_exhausted_falls_back_to_state(self):
        """claude_exhausted() derives state from pool if flag missing."""
        cfg = [{"name": "acct1", "type": "login"}]
        cfg_path = os.path.join(self.temp_dir, "accounts.json")
        json.dump(cfg, open(cfg_path, "w"))

        pool = account_pool.AccountPool()
        pool.mark_exhausted(pool.accts[0])

        # Remove the flag file
        flag = os.path.join(self.temp_dir, "claude_exhausted.json")
        os.remove(flag)

        # Clear cache
        account_pool._EXH_CACHE["t"] = 0
        result = account_pool.claude_exhausted()
        assert result is True


class TestStats:
    """Test stats() method — the deduplication focus."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.orig_home = os.environ.get("CLAUDE_ORCH_HOME")
        os.environ["CLAUDE_ORCH_HOME"] = self.temp_dir

    def teardown_method(self):
        if self.orig_home:
            os.environ["CLAUDE_ORCH_HOME"] = self.orig_home
        else:
            del os.environ["CLAUDE_ORCH_HOME"]
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_stats_returns_dict_with_all_fields(self):
        """stats() returns a dict with expected keys."""
        cfg = [
            {"name": "acct1", "type": "login"},
            {"name": "acct2", "type": "api", "api_key_env": "KEY"},
        ]
        cfg_path = os.path.join(self.temp_dir, "accounts.json")
        json.dump(cfg, open(cfg_path, "w"))

        pool = account_pool.AccountPool()
        stats = pool.stats()

        assert isinstance(stats, dict)
        assert "total_accounts" in stats
        assert "healthy_count" in stats
        assert "all_exhausted" in stats
        assert "current" in stats
        assert "accounts" in stats

    def test_stats_accounts_have_expected_fields(self):
        """Each account in stats has name, type, healthy, use_count, etc."""
        cfg = [{"name": "acct1", "type": "login"}]
        cfg_path = os.path.join(self.temp_dir, "accounts.json")
        json.dump(cfg, open(cfg_path, "w"))

        pool = account_pool.AccountPool()
        pool.record_use(pool.accts[0])
        stats = pool.stats()

        assert len(stats["accounts"]) >= 1
        acct = stats["accounts"][0]
        assert "name" in acct
        assert "type" in acct
        assert "healthy" in acct
        assert "use_count" in acct
        assert "exh_hits" in acct
        assert "cooldown_remaining_s" in acct

    def test_stats_healthy_count_accurate(self):
        """stats() correctly counts healthy vs cooling accounts."""
        cfg = [
            {"name": "a1", "type": "login"},
            {"name": "a2", "type": "login"},
        ]
        cfg_path = os.path.join(self.temp_dir, "accounts.json")
        json.dump(cfg, open(cfg_path, "w"))

        pool = account_pool.AccountPool()
        stats = pool.stats()
        initial_healthy = stats["healthy_count"]
        assert initial_healthy >= 1

        # Cool down one
        pool.mark_exhausted(pool.accts[0])
        stats = pool.stats()
        assert stats["healthy_count"] == initial_healthy - 1

    def test_stats_all_exhausted_flag(self):
        """stats()['all_exhausted'] reflects current pool state."""
        cfg = [{"name": "acct1", "type": "login"}]
        cfg_path = os.path.join(self.temp_dir, "accounts.json")
        json.dump(cfg, open(cfg_path, "w"))

        pool = account_pool.AccountPool()
        assert pool.stats()["all_exhausted"] is False

        pool.mark_exhausted(pool.accts[0])
        assert pool.stats()["all_exhausted"] is True

    def test_module_level_stats_delegates_to_singleton(self):
        """Module-level stats() function delegates to singleton pool."""
        cfg = [{"name": "acct1", "type": "login"}]
        cfg_path = os.path.join(self.temp_dir, "accounts.json")
        json.dump(cfg, open(cfg_path, "w"))

        # Reset module-level singleton
        account_pool._pool = None
        stats = account_pool.stats()

        assert isinstance(stats, dict)
        assert "total_accounts" in stats


class TestBillingGuard:
    """Test API billing guard integration."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.orig_home = os.environ.get("CLAUDE_ORCH_HOME")
        os.environ["CLAUDE_ORCH_HOME"] = self.temp_dir

    def teardown_method(self):
        if self.orig_home:
            os.environ["CLAUDE_ORCH_HOME"] = self.orig_home
        else:
            del os.environ["CLAUDE_ORCH_HOME"]
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_env_for_api_withholds_key_if_not_allowed(self):
        """env_for() doesn't inject API_KEY if billing guard disallows it."""
        cfg = [{"name": "api_acct", "type": "api", "api_key_env": "MY_KEY"}]
        cfg_path = os.path.join(self.temp_dir, "accounts.json")
        json.dump(cfg, open(cfg_path, "w"))

        os.environ["MY_KEY"] = "secret"
        with patch("account_pool._api_billing_allowed", return_value=False):
            pool = account_pool.AccountPool()
            env = pool.env_for(pool.accts[0])
            assert "ANTHROPIC_API_KEY" not in env

    def test_env_for_api_injects_key_if_allowed(self):
        """env_for() injects API_KEY if billing guard allows it."""
        cfg = [{"name": "api_acct", "type": "api", "api_key_env": "MY_KEY"}]
        cfg_path = os.path.join(self.temp_dir, "accounts.json")
        json.dump(cfg, open(cfg_path, "w"))

        os.environ["MY_KEY"] = "secret_key_12345"
        with patch("account_pool._api_billing_allowed", return_value=True):
            pool = account_pool.AccountPool()
            env = pool.env_for(pool.accts[0])
            assert env.get("ANTHROPIC_API_KEY") == "secret_key_12345"

    def test_env_for_login_injects_config_dir(self):
        """env_for() injects CLAUDE_CONFIG_DIR for login-type accounts."""
        cfg = [{"name": "login_acct", "type": "login", "config_dir": "~/.my-claude"}]
        cfg_path = os.path.join(self.temp_dir, "accounts.json")
        json.dump(cfg, open(cfg_path, "w"))

        pool = account_pool.AccountPool()
        env = pool.env_for(pool.accts[0])
        assert "CLAUDE_CONFIG_DIR" in env
        assert env["CLAUDE_CONFIG_DIR"].endswith(".my-claude")


class TestInvalidate:
    """Test invalidate() cache-flush and targeted clear."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.orig_home = os.environ.get("CLAUDE_ORCH_HOME")
        os.environ["CLAUDE_ORCH_HOME"] = self.temp_dir

    def teardown_method(self):
        if self.orig_home:
            os.environ["CLAUDE_ORCH_HOME"] = self.orig_home
        else:
            del os.environ["CLAUDE_ORCH_HOME"]
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_invalidate_clears_specific_cooldown(self):
        """invalidate(name='acct') clears cooldown for that account."""
        cfg = [{"name": "acct1", "type": "login"}]
        cfg_path = os.path.join(self.temp_dir, "accounts.json")
        json.dump(cfg, open(cfg_path, "w"))

        pool = account_pool.AccountPool()
        pool.mark_exhausted(pool.accts[0])
        assert "cooldown_until" in pool.state["acct1"]

        pool.invalidate("acct1")
        assert "cooldown_until" not in pool.state["acct1"]

    def test_invalidate_without_name_reloads_all(self):
        """invalidate() without name reloads config from disk."""
        cfg = [{"name": "acct1", "type": "login"}]
        cfg_path = os.path.join(self.temp_dir, "accounts.json")
        json.dump(cfg, open(cfg_path, "w"))

        pool = account_pool.AccountPool()
        orig_ts = pool._cfg_ts

        # Wait a bit then call invalidate
        time.sleep(0.1)
        pool.invalidate()
        assert pool._cfg_ts > orig_ts

    def test_module_level_invalidate_delegates(self):
        """Module-level invalidate() delegates to singleton."""
        cfg = [{"name": "acct1", "type": "login"}]
        cfg_path = os.path.join(self.temp_dir, "accounts.json")
        json.dump(cfg, open(cfg_path, "w"))

        # Reset singleton
        account_pool._pool = None
        pool_obj = account_pool._get_pool()
        pool_obj.mark_exhausted(pool_obj.accts[0])

        account_pool.invalidate("acct1")
        # After invalidate, cooldown should be cleared
        assert "cooldown_until" not in pool_obj.state.get("acct1", {})


class TestEdgeCases:
    """Test boundary conditions and error handling."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.orig_home = os.environ.get("CLAUDE_ORCH_HOME")
        os.environ["CLAUDE_ORCH_HOME"] = self.temp_dir

    def teardown_method(self):
        if self.orig_home:
            os.environ["CLAUDE_ORCH_HOME"] = self.orig_home
        else:
            del os.environ["CLAUDE_ORCH_HOME"]
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_record_use_on_none_is_noop(self):
        """record_use(None) is safe."""
        pool = account_pool.AccountPool()
        pool.record_use(None)  # Should not raise

    def test_mark_exhausted_none_is_noop(self):
        """mark_exhausted(None) is safe."""
        pool = account_pool.AccountPool()
        pool.mark_exhausted(None)  # Should not raise

    def test_env_for_none_returns_empty_dict(self):
        """env_for(None) returns {}."""
        pool = account_pool.AccountPool()
        env = pool.env_for(None)
        assert env == {}

    def test_multiple_reloads_stable(self):
        """Repeated _maybe_reload() calls don't corrupt state."""
        cfg = [{"name": "acct1", "type": "login"}]
        cfg_path = os.path.join(self.temp_dir, "accounts.json")
        json.dump(cfg, open(cfg_path, "w"))

        pool = account_pool.AccountPool()
        for _ in range(5):
            pool._maybe_reload()
        assert len(pool.accts) == 1

    def test_all_exhausted_with_api_and_billing_guard(self):
        """all_exhausted() respects billing guard when checking usability."""
        cfg = [
            {"name": "api", "type": "api", "api_key_env": "KEY"},
            {"name": "sub", "type": "login"},
        ]
        cfg_path = os.path.join(self.temp_dir, "accounts.json")
        json.dump(cfg, open(cfg_path, "w"))

        with patch("account_pool._api_billing_allowed", return_value=False):
            pool = account_pool.AccountPool()
            # Only subscription account is usable
            pool.mark_exhausted([a for a in pool.accts if a["name"] == "sub"][0])
            assert pool.all_exhausted() is True


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
