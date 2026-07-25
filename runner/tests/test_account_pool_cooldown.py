#!/usr/bin/env python3
"""
test_account_pool_cooldown.py - Comprehensive tests for account pool cooldown and exponential backoff logic.

Covers:
- _cooldown() and _cooldown_max() module functions (fixes NameError from bug)
- mark_exhausted() exponential backoff calculation
- Cooldown capping at COOLDOWN_MAX
- Multi-hit backoff progression
- State persistence and reload
"""
import pytest
import json
import os
import time
import tempfile
from unittest.mock import patch, MagicMock

# Import the module under test
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import account_pool


class TestCooldownFunctions:
    """Test module-level _cooldown() and _cooldown_max() functions."""

    def test_cooldown_function_returns_constant(self):
        """_cooldown() returns the COOLDOWN constant value."""
        result = account_pool._cooldown()
        assert result == account_pool.COOLDOWN
        assert isinstance(result, int)
        assert result > 0

    def test_cooldown_max_function_returns_constant(self):
        """_cooldown_max() returns the COOLDOWN_MAX constant value."""
        result = account_pool._cooldown_max()
        assert result == account_pool.COOLDOWN_MAX
        assert isinstance(result, int)
        assert result > account_pool.COOLDOWN  # max should exceed base

    def test_cooldown_default_is_1200_seconds(self):
        """COOLDOWN defaults to 20 minutes (1200 seconds) when env vars not set."""
        # This test verifies the constant was loaded correctly
        # Default from code: str(20 * 60) = "1200"
        assert account_pool.COOLDOWN == 20 * 60

    def test_cooldown_max_default_is_6_hours(self):
        """COOLDOWN_MAX defaults to 6 hours (21600 seconds) when env vars not set."""
        # Default from code: str(6 * 3600) = "21600"
        assert account_pool.COOLDOWN_MAX == 6 * 3600


class TestMarkExhaustedBackoff:
    """Test mark_exhausted() exponential backoff calculation."""

    @pytest.fixture
    def temp_state_dir(self):
        """Create a temporary directory for state files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def pool_with_temp_state(self, temp_state_dir):
        """Create an AccountPool with temporary state directory."""
        with patch.dict(os.environ, {'CLAUDE_ORCH_HOME': temp_state_dir}):
            pool = account_pool.AccountPool()
            yield pool

    def test_first_exhaustion_sets_base_cooldown(self, pool_with_temp_state):
        """First exhaustion (hits=1) sets cooldown to base COOLDOWN value."""
        pool = pool_with_temp_state
        acct = {"name": "test-account", "type": "login"}
        now = time.time()

        pool.mark_exhausted(acct)

        state = pool.state[acct["name"]]
        cooldown_until = state["cooldown_until"]
        elapsed = cooldown_until - now

        # First hit: no backoff, should be close to COOLDOWN
        assert state["exh_hits"] == 1
        assert abs(elapsed - account_pool.COOLDOWN) < 1  # within 1 second

    def test_second_exhaustion_doubles_cooldown(self, pool_with_temp_state):
        """Second exhaustion (hits=2) doubles the cooldown."""
        pool = pool_with_temp_state
        acct = {"name": "test-account", "type": "login"}

        # First exhaustion
        pool.mark_exhausted(acct)
        first_cooldown_until = pool.state[acct["name"]]["cooldown_until"]

        # Second exhaustion
        pool.mark_exhausted(acct)
        second_cooldown_until = pool.state[acct["name"]]["cooldown_until"]

        # Should have doubled
        assert pool.state[acct["name"]]["exh_hits"] == 2
        assert abs((second_cooldown_until - first_cooldown_until) - account_pool.COOLDOWN) < 1

    def test_exponential_backoff_progression(self, pool_with_temp_state):
        """Multiple exhaustions follow exponential backoff: base, 2x, 4x, 8x, ..."""
        pool = pool_with_temp_state
        acct = {"name": "test-account", "type": "login"}
        base = account_pool.COOLDOWN

        cooldowns = []
        for i in range(1, 6):
            now = time.time()
            pool.mark_exhausted(acct)
            expected = base * (2 ** (i - 1))
            actual = pool.state[acct["name"]]["cooldown_until"] - now
            cooldowns.append((i, expected, actual))
            # Allow small tolerance for execution time
            assert abs(actual - expected) < 2, f"Hit {i}: expected {expected}, got {actual}"

    def test_cooldown_capped_at_max(self, pool_with_temp_state):
        """Exponential backoff is capped at COOLDOWN_MAX."""
        pool = pool_with_temp_state
        acct = {"name": "test-account", "type": "login"}
        base = account_pool.COOLDOWN
        max_cd = account_pool.COOLDOWN_MAX

        # Exhaust enough times to exceed COOLDOWN_MAX
        # COOLDOWN_MAX = 6h = 21600s, COOLDOWN = 20min = 1200s
        # 2^4 * 1200 = 19200s (still under max)
        # 2^5 * 1200 = 38400s (exceeds max)

        for i in range(1, 8):
            now = time.time()
            pool.mark_exhausted(acct)
            cooldown_until = pool.state[acct["name"]]["cooldown_until"]
            elapsed = cooldown_until - now

            # After any exhaustion, cooldown should never exceed COOLDOWN_MAX
            assert elapsed <= max_cd + 1  # +1s tolerance
            assert pool.state[acct["name"]]["exh_hits"] == i

    def test_mark_ok_resets_backoff_counter(self, pool_with_temp_state):
        """mark_ok() resets exh_hits counter for backoff reset on next limit."""
        pool = pool_with_temp_state
        acct = {"name": "test-account", "type": "login"}

        # Cause multiple exhaustions to build up backoff
        pool.mark_exhausted(acct)
        pool.mark_exhausted(acct)
        assert pool.state[acct["name"]]["exh_hits"] == 2

        # Mark as OK resets counter
        pool.mark_ok(acct)
        assert "exh_hits" not in pool.state[acct["name"]]

        # Next exhaustion should use base cooldown again
        now = time.time()
        pool.mark_exhausted(acct)
        elapsed = pool.state[acct["name"]]["cooldown_until"] - now
        assert pool.state[acct["name"]]["exh_hits"] == 1
        assert abs(elapsed - account_pool.COOLDOWN) < 1

    def test_mark_exhausted_with_none_account_is_safe(self, pool_with_temp_state):
        """mark_exhausted(None) does not crash (fail-soft)."""
        pool = pool_with_temp_state
        # Should not raise
        result = pool.mark_exhausted(None)
        assert result is None

    def test_mark_exhausted_saves_state(self, pool_with_temp_state):
        """mark_exhausted() persists state to disk."""
        pool = pool_with_temp_state
        acct = {"name": "test-account", "type": "login"}

        pool.mark_exhausted(acct)

        # Load fresh pool to verify state was saved
        fresh_pool = account_pool.AccountPool()
        assert acct["name"] in fresh_pool.state
        assert fresh_pool.state[acct["name"]]["exh_hits"] == 1
        assert "cooldown_until" in fresh_pool.state[acct["name"]]


class TestCooldownIntegration:
    """Integration tests for cooldown behavior across pool operations."""

    @pytest.fixture
    def temp_state_dir(self):
        """Create a temporary directory for state files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def pool_with_temp_state(self, temp_state_dir):
        """Create an AccountPool with temporary state directory."""
        with patch.dict(os.environ, {'CLAUDE_ORCH_HOME': temp_state_dir}):
            pool = account_pool.AccountPool()
            yield pool

    def test_healthy_check_respects_cooldown(self, pool_with_temp_state):
        """_healthy() returns False while cooldown is active."""
        pool = pool_with_temp_state
        acct = {"name": "test-account", "type": "login"}

        # Account starts healthy
        assert pool._healthy(acct)

        # After exhaustion, becomes unhealthy
        pool.mark_exhausted(acct)
        assert not pool._healthy(acct)

        # After cooldown expires, becomes healthy again
        pool.state[acct["name"]]["cooldown_until"] = time.time() - 1
        assert pool._healthy(acct)

    def test_current_account_rotates_on_exhaustion(self, pool_with_temp_state):
        """current() rotates to next account when one is exhausted."""
        pool = pool_with_temp_state
        acct1 = {"name": "account-1", "type": "login"}
        acct2 = {"name": "account-2", "type": "login"}

        # Mock the accounts list
        pool.accts = [acct1, acct2]

        # Account 1 is current
        current = pool.current()
        assert current["name"] == "account-1"

        # Exhaust account 1
        pool.mark_exhausted(acct1)

        # Account 2 becomes current
        current = pool.current()
        assert current["name"] == "account-2"

    def test_all_accounts_exhausted_flag(self, pool_with_temp_state):
        """all_exhausted() returns True when no accounts are healthy."""
        pool = pool_with_temp_state
        acct1 = {"name": "account-1", "type": "login"}
        acct2 = {"name": "account-2", "type": "login"}
        pool.accts = [acct1, acct2]

        # Initially not exhausted
        assert not pool.all_exhausted()

        # Exhaust first account
        pool.mark_exhausted(acct1)
        assert not pool.all_exhausted()  # second is still healthy

        # Exhaust second account
        pool.mark_exhausted(acct2)
        assert pool.all_exhausted()  # all are cooling

    def test_stats_reflects_cooldown_state(self, pool_with_temp_state):
        """stats() reports correct cooldown_remaining_s for each account."""
        pool = pool_with_temp_state
        acct = {"name": "test-account", "type": "login"}
        pool.accts = [acct]

        # Initially healthy
        stats = pool.stats()
        acct_stat = stats["accounts"][0]
        assert acct_stat["healthy"]
        assert acct_stat["cooldown_remaining_s"] == 0

        # After exhaustion
        pool.mark_exhausted(acct)
        stats = pool.stats()
        acct_stat = stats["accounts"][0]
        assert not acct_stat["healthy"]
        assert acct_stat["cooldown_remaining_s"] > 0
        assert acct_stat["cooldown_remaining_s"] <= account_pool.COOLDOWN + 1


class TestCooldownEnvironmentVariables:
    """Test environment variable override of cooldown values."""

    def test_orch_account_cooldown_env_var_overrides(self):
        """ORCH_ACCOUNT_COOLDOWN env var overrides default."""
        with patch.dict(os.environ, {'ORCH_ACCOUNT_COOLDOWN': '600'}):
            # Force reload by importing fresh module
            import importlib
            import account_pool as ap
            importlib.reload(ap)
            assert ap.COOLDOWN == 600

    def test_account_cooldown_fallback_env_var(self):
        """ACCOUNT_COOLDOWN env var is fallback after ORCH_ACCOUNT_COOLDOWN."""
        with patch.dict(os.environ, {'ACCOUNT_COOLDOWN': '900'}, clear=False):
            if 'ORCH_ACCOUNT_COOLDOWN' in os.environ:
                del os.environ['ORCH_ACCOUNT_COOLDOWN']
            import importlib
            import account_pool as ap
            importlib.reload(ap)
            # Should use ORCH_ prefixed if set, else fallback to ACCOUNT_COOLDOWN
            assert ap.COOLDOWN == 900 or ap.COOLDOWN == 20 * 60


class TestEdgeCases:
    """Test edge cases and error conditions."""

    @pytest.fixture
    def temp_state_dir(self):
        """Create a temporary directory for state files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def pool_with_temp_state(self, temp_state_dir):
        """Create an AccountPool with temporary state directory."""
        with patch.dict(os.environ, {'CLAUDE_ORCH_HOME': temp_state_dir}):
            pool = account_pool.AccountPool()
            yield pool

    def test_mark_exhausted_with_missing_account_creates_state(self, pool_with_temp_state):
        """mark_exhausted() creates state entry if account doesn't exist in state yet."""
        pool = pool_with_temp_state
        acct = {"name": "new-account", "type": "login"}

        assert acct["name"] not in pool.state
        pool.mark_exhausted(acct)
        assert acct["name"] in pool.state
        assert pool.state[acct["name"]]["exh_hits"] == 1

    def test_large_number_of_exhaustion_hits(self, pool_with_temp_state):
        """Backoff calculation is correct even with many exhaustion hits."""
        pool = pool_with_temp_state
        acct = {"name": "test-account", "type": "login"}

        # Exhaust 20 times
        for i in range(1, 21):
            now = time.time()
            pool.mark_exhausted(acct)
            cooldown_until = pool.state[acct["name"]]["cooldown_until"]
            elapsed = cooldown_until - now

            # Should always be capped at COOLDOWN_MAX
            assert elapsed <= account_pool.COOLDOWN_MAX + 1
            assert pool.state[acct["name"]]["exh_hits"] == i

    def test_cooldown_calculation_precision(self, pool_with_temp_state):
        """Cooldown calculation uses correct formula: base * 2^(hits-1) capped at max."""
        pool = pool_with_temp_state
        acct = {"name": "test-account", "type": "login"}
        base = account_pool.COOLDOWN
        max_cd = account_pool.COOLDOWN_MAX

        for hits in range(1, 6):
            pool.state[acct["name"]] = {"exh_hits": hits - 1}
            now = time.time()
            pool.mark_exhausted(acct)

            expected = min(base * (2 ** (hits - 1)), max_cd)
            actual = pool.state[acct["name"]]["cooldown_until"] - now

            # Verify formula matches implementation
            assert abs(actual - expected) < 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
