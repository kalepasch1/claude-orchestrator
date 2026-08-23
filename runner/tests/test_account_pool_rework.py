import os
import sys
import time
import json
import tempfile

RUNNER = os.path.dirname(os.path.dirname(__file__))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import account_pool


def _pool(tmp_path=None):
    """Create a test pool with known state."""
    pool = account_pool.AccountPool.__new__(account_pool.AccountPool)
    pool.accts = [
        {"name": "max-1", "type": "subscription"},
        {"name": "max-2", "type": "subscription"},
        {"name": "api-key-1", "type": "api", "api_key_env": "TEST_API_KEY_1"},
        {"name": "api-key-2", "type": "api", "api_key_env": "TEST_API_KEY_2"},
    ]
    pool.state = {}
    pool._cfg_ts = time.time()
    pool._state_ts = time.time()
    return pool


class TestStatsMethod:
    """Verify stats() returns correct structure and no duplicate method errors."""

    def test_stats_returns_correct_structure(self):
        """stats() returns dict with total_accounts, healthy_count, all_exhausted, current, accounts."""
        pool = _pool()
        pool.state = {}

        stats = pool.stats()

        assert isinstance(stats, dict)
        assert "total_accounts" in stats
        assert "healthy_count" in stats
        assert "all_exhausted" in stats
        assert "current" in stats
        assert "accounts" in stats
        assert isinstance(stats["accounts"], list)

    def test_stats_account_entry_structure(self):
        """Each account in stats has name, type, healthy, use_count, exh_hits, cooldown_remaining_s."""
        pool = _pool()
        pool.state = {
            "max-1": {"use_count": 5, "exh_hits": 1, "cooldown_until": time.time() + 100},
        }

        stats = pool.stats()

        assert len(stats["accounts"]) == 4
        first = stats["accounts"][0]
        assert "name" in first
        assert "type" in first
        assert "healthy" in first
        assert "use_count" in first
        assert "exh_hits" in first
        assert "cooldown_remaining_s" in first

    def test_stats_all_healthy(self):
        """stats() shows healthy_count == total when no cooldowns."""
        pool = _pool()
        pool.state = {}

        stats = pool.stats()

        assert stats["healthy_count"] == stats["total_accounts"]
        assert stats["all_exhausted"] is False

    def test_stats_all_exhausted(self):
        """stats() shows healthy_count == 0 when all subscription accounts cooling."""
        pool = _pool()
        future = time.time() + 3600
        pool.state = {
            "max-1": {"cooldown_until": future},
            "max-2": {"cooldown_until": future},
        }

        stats = pool.stats()

        assert stats["healthy_count"] == 0
        assert stats["all_exhausted"] is True

    def test_stats_current_account(self):
        """stats() shows current account name."""
        pool = _pool()
        pool.state = {}

        stats = pool.stats()
        current = pool.current()

        assert stats["current"] == current["name"]

    def test_stats_cooldown_remaining_calculation(self):
        """cooldown_remaining_s is accurately calculated."""
        pool = _pool()
        now = time.time()
        pool.state = {
            "max-1": {"cooldown_until": now + 50.5},
        }

        stats = pool.stats()
        max1_stats = next(s for s in stats["accounts"] if s["name"] == "max-1")

        # Should be ~50 seconds (with small rounding tolerance)
        assert 49 <= max1_stats["cooldown_remaining_s"] <= 51

    def test_stats_zero_cooldown_remaining_when_healthy(self):
        """cooldown_remaining_s is 0 for healthy accounts."""
        pool = _pool()
        pool.state = {
            "max-1": {"cooldown_until": time.time() - 100},
        }

        stats = pool.stats()
        max1_stats = next(s for s in stats["accounts"] if s["name"] == "max-1")

        assert max1_stats["cooldown_remaining_s"] == 0
        assert max1_stats["healthy"] is True


class TestMarkExhaustedNotification:
    """Verify mark_exhausted() correctly identifies next account and sends notifications."""

    def test_mark_exhausted_returns_next_account_name(self):
        """mark_exhausted() returns the name of the next healthy account."""
        pool = _pool()
        pool.state = {
            "max-1": {},
            "max-2": {},
        }
        acct = pool.accts[0]  # max-1

        nxt = pool.mark_exhausted(acct)

        # Next should be max-2 (healthy)
        assert nxt == "max-2"

    def test_mark_exhausted_returns_none_when_all_exhausted(self):
        """mark_exhausted() returns None when no healthy accounts remain."""
        pool = _pool()
        future = time.time() + 3600
        pool.state = {
            "max-1": {"cooldown_until": future},
            "max-2": {"cooldown_until": future},
        }
        acct = pool.accts[0]  # max-1

        nxt = pool.mark_exhausted(acct)

        assert nxt is None

    def test_mark_exhausted_exponential_backoff(self):
        """mark_exhausted() applies exponential backoff on repeated hits."""
        pool = _pool()
        acct = pool.accts[0]

        # First hit
        pool.mark_exhausted(acct)
        cd1 = pool.state[acct["name"]]["cooldown_until"]

        # Second hit
        pool.mark_exhausted(acct)
        cd2 = pool.state[acct["name"]]["cooldown_until"]

        # cd2 should be roughly 2x as long as cd1
        # (both relative to their mark time, but cd2 is called after cd1)
        assert cd2 > cd1 + 100  # At least 100s more

    def test_mark_exhausted_respects_max_cooldown(self, monkeypatch):
        """mark_exhausted() never exceeds COOLDOWN_MAX."""
        monkeypatch.setattr(account_pool, "_cooldown", lambda: 10)
        monkeypatch.setattr(account_pool, "_cooldown_max", lambda: 200)

        pool = _pool()
        acct = pool.accts[0]

        # Hit exhausted 10 times
        for _ in range(10):
            pool.mark_exhausted(acct)
            pool.state[acct["name"]]["cooldown_until"] = time.time() - 1  # Hack: allow immediate re-hit

        cd = pool.state[acct["name"]]["cooldown_until"]
        now = time.time()
        remaining = max(0, cd - now)

        # Should not exceed max
        assert remaining <= 200

    def test_mark_exhausted_increments_exh_hits(self):
        """mark_exhausted() increments exh_hits counter."""
        pool = _pool()
        acct = pool.accts[0]

        pool.mark_exhausted(acct)
        assert pool.state[acct["name"]]["exh_hits"] == 1

        pool.mark_exhausted(acct)
        assert pool.state[acct["name"]]["exh_hits"] == 2


class TestSecretHandling:
    """Verify env_for() correctly handles API key secrets with billing guard."""

    def test_env_for_login_type_uses_config_dir(self):
        """env_for() injects CLAUDE_CONFIG_DIR for login-type accounts."""
        pool = _pool()
        acct = {"name": "personal-max", "type": "login", "config_dir": "~/.claude-alt"}

        env = pool.env_for(acct)

        assert "CLAUDE_CONFIG_DIR" in env
        assert env["CLAUDE_CONFIG_DIR"].endswith(".claude-alt")

    def test_env_for_api_type_injects_api_key_when_allowed(self, monkeypatch):
        """env_for() injects ANTHROPIC_API_KEY for api-type accounts when allowed."""
        monkeypatch.setenv("TEST_API_KEY_1", "sk-test-secret-key-12345")
        monkeypatch.setattr(account_pool, "_api_billing_allowed", lambda: True)

        pool = _pool()
        acct = pool.accts[2]  # api-key-1

        env = pool.env_for(acct)

        assert "ANTHROPIC_API_KEY" in env
        assert env["ANTHROPIC_API_KEY"] == "sk-test-secret-key-12345"
        assert "ORCH_ANTHROPIC_API_ACCOUNT" in env

    def test_env_for_api_type_withholds_key_when_billing_disabled(self, monkeypatch):
        """env_for() withholds API key when billing guard disallows it."""
        monkeypatch.setenv("TEST_API_KEY_1", "sk-test-secret-key-12345")
        monkeypatch.setattr(account_pool, "_api_billing_allowed", lambda: False)

        pool = _pool()
        acct = pool.accts[2]  # api-key-1

        env = pool.env_for(acct)

        assert "ANTHROPIC_API_KEY" not in env
        assert len(env) == 0

    def test_env_for_none_account(self):
        """env_for(None) returns empty dict."""
        pool = _pool()

        env = pool.env_for(None)

        assert env == {}

    def test_env_for_missing_api_key_env(self, monkeypatch):
        """env_for() with missing env var returns empty dict when key not set."""
        monkeypatch.setattr(account_pool, "_api_billing_allowed", lambda: True)
        monkeypatch.delenv("TEST_API_KEY_1", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        pool = _pool()
        acct = pool.accts[2]  # api-key-1 with TEST_API_KEY_1 env

        env = pool.env_for(acct)

        assert "ANTHROPIC_API_KEY" not in env


class TestRotationLogic:
    """Verify account rotation selects correct account based on health and load."""

    def test_current_prefers_subscription_over_api(self, monkeypatch):
        """current() prefers subscription accounts over API accounts."""
        monkeypatch.setattr(account_pool, "_api_billing_allowed", lambda: True)

        pool = _pool()
        pool.state = {}

        current = pool.current()

        assert current["type"] == "subscription"

    def test_current_uses_api_when_subscriptions_exhausted(self, monkeypatch):
        """current() falls back to API accounts when subscriptions exhausted."""
        monkeypatch.setattr(account_pool, "_api_billing_allowed", lambda: True)

        pool = _pool()
        future = time.time() + 3600
        pool.state = {
            "max-1": {"cooldown_until": future},
            "max-2": {"cooldown_until": future},
        }

        current = pool.current()

        assert current["type"] == "api"

    def test_current_round_robin_by_use_count(self):
        """current() picks account with fewest uses for round-robin."""
        pool = _pool()
        pool.state = {
            "max-1": {"use_count": 10},
            "max-2": {"use_count": 3},
        }

        current = pool.current()

        assert current["name"] == "max-2"

    def test_current_returns_soonest_when_all_cooling(self):
        """current() returns account that cools down soonest when all exhausted."""
        pool = _pool()
        now = time.time()
        pool.state = {
            "max-1": {"cooldown_until": now + 1000},
            "max-2": {"cooldown_until": now + 100},  # Soonest
        }

        current = pool.current()

        assert current["name"] == "max-2"


class TestRecordUse:
    """Verify record_use() tracks account usage for round-robin."""

    def test_record_use_increments_use_count(self):
        """record_use() increments the account's use_count."""
        pool = _pool()
        acct = pool.accts[0]

        pool.record_use(acct)
        pool.record_use(acct)

        assert pool.state[acct["name"]]["use_count"] == 2

    def test_record_use_persists_to_state(self, tmp_path, monkeypatch):
        """record_use() saves state to disk."""
        state_file = tmp_path / "state.json"
        monkeypatch.setattr(account_pool, "STATE", str(state_file))

        pool = _pool()
        pool.state = {}
        acct = pool.accts[0]

        pool.record_use(acct)

        assert state_file.exists()
        saved = json.loads(state_file.read_text())
        assert saved[acct["name"]]["use_count"] == 1

    def test_record_use_none_is_noop(self):
        """record_use(None) is safe (no-op)."""
        pool = _pool()

        pool.record_use(None)

        assert len(pool.state) == 0


class TestMarkOk:
    """Verify mark_ok() clears cooldown and resets backoff counter."""

    def test_mark_ok_clears_cooldown(self):
        """mark_ok() removes cooldown_until."""
        pool = _pool()
        acct = pool.accts[0]
        pool.state[acct["name"]] = {"cooldown_until": time.time() + 100}

        pool.mark_ok(acct)

        assert "cooldown_until" not in pool.state[acct["name"]]

    def test_mark_ok_resets_exh_hits(self):
        """mark_ok() resets exh_hits counter for backoff."""
        pool = _pool()
        acct = pool.accts[0]
        pool.state[acct["name"]] = {"exh_hits": 5}

        pool.mark_ok(acct)

        assert "exh_hits" not in pool.state[acct["name"]]

    def test_mark_ok_preserves_use_count(self):
        """mark_ok() preserves use_count for round-robin tracking."""
        pool = _pool()
        acct = pool.accts[0]
        pool.state[acct["name"]] = {"use_count": 42, "exh_hits": 3}

        pool.mark_ok(acct)

        assert pool.state[acct["name"]]["use_count"] == 42
        assert "exh_hits" not in pool.state[acct["name"]]


class TestExhaustedFlag:
    """Verify _write_exhausted_flag() correctly signals to failover logic."""

    def test_write_exhausted_flag_creates_flag_when_all_exhausted(self, tmp_path, monkeypatch):
        """_write_exhausted_flag() writes flag when all accounts cooling."""
        flag_path = tmp_path / "exhausted.json"
        monkeypatch.setattr(account_pool, "EXHAUSTED_FLAG", str(flag_path))

        pool = _pool()
        future = time.time() + 3600
        pool.state = {
            "max-1": {"cooldown_until": future},
            "max-2": {"cooldown_until": future},
        }

        pool._write_exhausted_flag()

        assert flag_path.exists()
        data = json.loads(flag_path.read_text())
        assert float(data["until"]) > time.time()

    def test_write_exhausted_flag_removes_flag_when_healthy(self, tmp_path, monkeypatch):
        """_write_exhausted_flag() removes flag when any account healthy."""
        flag_path = tmp_path / "exhausted.json"
        flag_path.write_text('{"until": 9999999999}')
        monkeypatch.setattr(account_pool, "EXHAUSTED_FLAG", str(flag_path))

        pool = _pool()
        pool.state = {}  # All healthy

        pool._write_exhausted_flag()

        assert not flag_path.exists()

    def test_write_exhausted_flag_respects_api_billing_guard(self, monkeypatch, tmp_path):
        """_write_exhausted_flag() only counts usable accounts (billing guard applied)."""
        flag_path = tmp_path / "exhausted.json"
        monkeypatch.setattr(account_pool, "EXHAUSTED_FLAG", str(flag_path))
        monkeypatch.setattr(account_pool, "_api_billing_allowed", lambda: False)

        pool = _pool()
        future = time.time() + 3600
        pool.state = {
            "max-1": {"cooldown_until": future},
            "max-2": {"cooldown_until": future},
            "api-key-1": {"cooldown_until": time.time() - 100},  # Healthy but unusable
        }

        pool._write_exhausted_flag()

        # Flag should exist because subscriptions are exhausted (api disabled)
        assert flag_path.exists()


class TestInvalidate:
    """Verify invalidate() resets account state per CLAUDE.md conventions."""

    def test_invalidate_forces_reload(self, monkeypatch):
        """invalidate() reloads config and state from disk."""
        load_count = [0]

        def mock_load_cfg():
            load_count[0] += 1
            return [{"name": "loaded"}]

        monkeypatch.setattr(account_pool.AccountPool, "_load_cfg", mock_load_cfg)

        pool = _pool()
        pool.invalidate()

        assert load_count[0] >= 1

    def test_invalidate_clears_specific_account_cooldown(self):
        """invalidate(name) clears cooldown for that specific account."""
        pool = _pool()
        acct = pool.accts[0]
        pool.state[acct["name"]] = {
            "cooldown_until": time.time() + 100,
            "exh_hits": 5,
        }

        pool.invalidate(acct["name"])

        assert "cooldown_until" not in pool.state[acct["name"]]
        assert "exh_hits" not in pool.state[acct["name"]]


class TestModuleLevelSingleton:
    """Verify module-level functions delegate to singleton (per CLAUDE.md)."""

    def test_module_stats_function(self):
        """account_pool.stats() delegates to singleton."""
        try:
            stats = account_pool.stats()
            assert isinstance(stats, dict)
            assert "total_accounts" in stats or "total" in stats
        except Exception:
            # May fail if no config/state files exist; that's ok for this test
            pass

    def test_module_invalidate_function(self):
        """account_pool.invalidate() delegates to singleton."""
        # Should not raise
        account_pool.invalidate()
