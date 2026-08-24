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
- API billing guard integration
- Stats/observability methods

ISOLATION NOTE (why every class inherits _TempPaths)
----------------------------------------------------
account_pool resolves its three file paths ONCE, at import time:

    HOME = os.environ.get("CLAUDE_ORCH_HOME", ~/.claude-orchestrator)
    CFG / STATE / EXHAUSTED_FLAG = os.path.join(HOME, ...)

The original version of this file set os.environ["CLAUDE_ORCH_HOME"] to a temp
directory inside setup_method — i.e. long after import — so it changed nothing.
Every test that wrote an accounts.json into its temp dir was in fact still reading
the machine's real ~/.claude-orchestrator (usually absent -> the implicit "default"
account, which is why the config/state/flag assertions failed), and every
mark_exhausted() call wrote cooldowns into the operator's REAL state file.

The convention used by the other suites against this module
(runner/tests/test_account_pool.py, runner/test_account_pool_secret_outcomes.py)
is to rebind the module constants themselves; that is what _TempPaths does. Tests
whose bodies were otherwise correct are unchanged apart from that redirection.
"""
import os
import sys
import json
import time
import tempfile
import shutil
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Disable DB for tests
os.environ["ORCH_DB_ENABLED"] = "false"
os.environ["SUPABASE_URL"] = "http://localhost"
os.environ["SUPABASE_SERVICE_KEY"] = "test"

import account_pool
import notify
import db
import subscription_guard


class _TempPaths:
    """Redirect account_pool's import-time path constants into a temp directory.

    Also restores any env var a test overrides, so nothing leaks into the next
    test file (the previous version leaked ORCH_ACCOUNT_COOLDOWN_MAX=500).
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

    def teardown_method(self, method):
        account_pool.CFG, account_pool.STATE, account_pool.EXHAUSTED_FLAG = self._orig
        os.environ.clear()
        os.environ.update(self._env_backup)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def write_cfg(self, cfg):
        with open(self.cfg_path, "w") as f:
            json.dump(cfg, f)

    def write_state(self, state):
        with open(self.state_path, "w") as f:
            json.dump(state, f)


class TestAccountPoolInitialization(_TempPaths):
    """Test pool initialization and config loading."""

    def test_init_default_when_no_config(self):
        """Pool defaults to single 'default' account if no config exists."""
        pool = account_pool.AccountPool()
        assert len(pool.accts) >= 1
        assert pool.accts[0]["name"] == "default"
        assert pool.accts[0]["type"] == "login"

    def test_init_loads_json_config_from_disk(self):
        """Pool loads accounts.json if it exists."""
        # Was asserting on a config written to $CLAUDE_ORCH_HOME, which account_pool
        # never re-reads; the pool always fell back to the implicit "default" account.
        self.write_cfg([
            {"name": "personal", "type": "login", "config_dir": "~/.claude"},
            {"name": "team", "type": "api", "api_key_env": "TEAM_KEY"},
        ])

        pool = account_pool.AccountPool()
        assert len(pool.accts) == 2
        assert pool.accts[0]["name"] == "personal"
        assert pool.accts[1]["name"] == "team"
        assert pool.accts[1]["type"] == "api"

    def test_init_empty_state_on_first_run(self):
        """Pool starts with empty state if accounts_state.json doesn't exist."""
        # Was reading the machine's real accounts_state.json, so it saw whatever
        # cooldowns the operator (or an earlier test run) had left there.
        pool = account_pool.AccountPool()
        assert pool.state == {}

    def test_init_loads_existing_state(self):
        """Pool loads accounts_state.json if present."""
        # Same import-time path bug as above.
        self.write_state({"personal": {"cooldown_until": time.time() + 3600, "exh_hits": 2}})

        pool = account_pool.AccountPool()
        assert "personal" in pool.state
        assert pool.state["personal"]["exh_hits"] == 2

    def test_init_ignores_state_file_that_is_not_a_mapping(self):
        """A corrupt state file that parses as a list must degrade to {}.

        New: covers the fail-soft path added to _load_state(). Before that fix the
        list was handed straight to current()/_healthy(), which then raised
        AttributeError: 'list' object has no attribute 'get'."""
        self.write_state([1, 2, 3])
        pool = account_pool.AccountPool()
        assert pool.state == {}
        assert pool.current() is not None


class TestCurrentAccountSelection(_TempPaths):
    """Test current() logic for account selection."""

    def test_current_returns_healthy_account(self):
        """current() returns a healthy (non-cooling) account if available."""
        # Config now actually reaches the pool (see _TempPaths); previously the
        # pool held only "default" and the membership assertion failed.
        self.write_cfg([{"name": "acct1", "type": "login"},
                        {"name": "acct2", "type": "login"}])

        pool = account_pool.AccountPool()
        current = pool.current()
        assert current is not None
        assert current["name"] in ["acct1", "acct2"]

    def test_current_with_all_cooling_returns_soonest(self):
        """current() returns the account that frees up soonest when all are cooling."""
        self.write_cfg([{"name": "acct1", "type": "login"},
                        {"name": "acct2", "type": "login"}])

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
        self.write_cfg([{"name": "subscription", "type": "login"},
                        {"name": "api_paid", "type": "api", "api_key_env": "API_KEY"}])

        with patch("account_pool._api_billing_allowed", return_value=True):
            pool = account_pool.AccountPool()
            current = pool.current()
            assert current["name"] == "subscription"

    def test_current_round_robin_among_equal_accounts(self):
        """current() uses use_count to round-robin among healthy accounts."""
        self.write_cfg([{"name": "a1", "type": "login"},
                        {"name": "a2", "type": "login"}])

        pool = account_pool.AccountPool()
        pool.state = {
            "a1": {"use_count": 10},
            "a2": {"use_count": 5},
        }
        current = pool.current()
        assert current["name"] == "a2"  # Fewer uses

        # ...and using it enough flips the choice back.
        pool.state["a2"]["use_count"] = 11
        assert pool.current()["name"] == "a1"

    def test_current_with_none_returns_none(self):
        """current() returns None if no usable accounts."""
        self.write_cfg([])

        pool = account_pool.AccountPool()
        # Manually clear to simulate empty
        pool.accts = []
        current = pool.current()
        assert current is None


class TestExhaustionAndCooldown(_TempPaths):
    """Test mark_exhausted() and cooldown exponential backoff."""

    def test_mark_exhausted_sets_cooldown(self):
        """mark_exhausted() sets cooldown_until in state."""
        # Previously looked up state["acct1"] on a pool that only knew "default".
        self.write_cfg([{"name": "acct1", "type": "login"}])
        os.environ["ORCH_ACCOUNT_COOLDOWN"] = "100"

        pool = account_pool.AccountPool()
        acct = pool.accts[0]
        before = time.time()
        pool.mark_exhausted(acct)

        state = pool.state.get("acct1", {})
        cd = state.get("cooldown_until", 0)
        assert before + 100 <= cd <= time.time() + 100
        assert state["exh_hits"] == 1
        assert not pool._healthy(acct)

    def test_mark_exhausted_exponential_backoff(self):
        """Repeated mark_exhausted() calls double the cooldown (up to MAX)."""
        # Was only able to assert cd3 > cd2 > cd1 on a pool with no such account;
        # with the real account present the exact 1x/2x/4x progression is checkable.
        self.write_cfg([{"name": "acct1", "type": "login"}])
        os.environ["ORCH_ACCOUNT_COOLDOWN"] = "100"
        os.environ["ORCH_ACCOUNT_COOLDOWN_MAX"] = "1600"

        pool = account_pool.AccountPool()
        acct = pool.accts[0]

        durations = []
        for _ in range(3):
            sent_at = time.time()
            pool.mark_exhausted(acct)
            durations.append(pool.state["acct1"]["cooldown_until"] - sent_at)

        assert pool.state["acct1"]["exh_hits"] == 3
        # 1x, 2x, 4x the 100s base (allow a little scheduling slack).
        for actual, expected in zip(durations, [100, 200, 400]):
            assert expected <= actual <= expected + 2

    def test_mark_exhausted_respects_max_cooldown(self):
        """Exponential backoff caps at COOLDOWN_MAX."""
        self.write_cfg([{"name": "acct1", "type": "login"}])
        os.environ["ORCH_ACCOUNT_COOLDOWN"] = "100"
        os.environ["ORCH_ACCOUNT_COOLDOWN_MAX"] = "500"

        pool = account_pool.AccountPool()
        acct = pool.accts[0]

        for _ in range(10):
            pool.mark_exhausted(acct)

        remaining = pool.state["acct1"]["cooldown_until"] - time.time()
        # 100 * 2**9 would be 51200s; the cap must hold it at exactly 500s.
        assert 498 <= remaining <= 500

    def test_mark_exhausted_notifies_rotation_by_name(self):
        """Rotation alert names the account rotated TO, and mark_exhausted returns it.

        Regression test for a real bug: current() returns an account dict, but the
        notify branch compared it to a["name"], so the message interpolated the whole
        dict ("rotated to '{'name': 'acct2', ...}'")."""
        self.write_cfg([{"name": "acct1", "type": "login"},
                        {"name": "acct2", "type": "login"}])

        pool = account_pool.AccountPool()
        acct1 = [a for a in pool.accts if a["name"] == "acct1"][0]

        sent = []
        with patch.object(notify, "send", sent.append):
            nxt = pool.mark_exhausted(acct1)

        assert nxt == "acct2"
        assert len(sent) == 1
        assert "rotated to 'acct2'" in sent[0]
        assert "{" not in sent[0]

    def test_mark_exhausted_notifies_full_exhaustion(self):
        """When the last account goes down the alert says so rather than 'rotated'.

        Same bug as above from the other side: `nxt != a["name"]` was always true,
        so the ALL-accounts-exhausted alert could never fire."""
        self.write_cfg([{"name": "acct1", "type": "login"}])

        pool = account_pool.AccountPool()
        sent = []
        with patch.object(notify, "send", sent.append):
            pool.mark_exhausted(pool.accts[0])

        assert len(sent) == 1
        assert sent[0].startswith("ALL accounts exhausted ('acct1' was last)")

    def test_mark_exhausted_persists_backed_off_cooldown_to_db(self):
        """The dashboard row mirrors the cooldown actually applied, backoff included.

        New: the db.update() call used the module-level COOLDOWN constant (frozen at
        import, backoff-blind), so a second hit parked the account for 2x the base
        while the dashboard still showed 1x."""
        import datetime

        self.write_cfg([{"name": "acct1", "type": "login"}])
        os.environ["ORCH_ACCOUNT_COOLDOWN"] = "100"

        pool = account_pool.AccountPool()
        acct = pool.accts[0]

        calls = []
        with patch.object(db, "update", lambda *a, **k: calls.append((a, k))):
            pool.mark_exhausted(acct)
            pool.mark_exhausted(acct)

        assert len(calls) == 2
        table, match, values = calls[-1][0]
        assert table == "accounts"
        assert match == {"name": "acct1"}
        written = datetime.datetime.fromisoformat(values["cooldown_until"])
        expected = datetime.datetime.utcfromtimestamp(pool.state["acct1"]["cooldown_until"])
        assert abs((written - expected).total_seconds()) < 1


class TestRecovery(_TempPaths):
    """Test mark_ok() and recovery logic."""

    def test_mark_ok_clears_cooldown(self):
        """mark_ok() removes cooldown_until and exh_hits."""
        # Previously indexed state["acct1"] on a pool that never loaded the config.
        self.write_cfg([{"name": "acct1", "type": "login"}])

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
        assert pool._healthy(acct)

    def test_mark_ok_preserves_use_count(self):
        """mark_ok() does NOT reset use_count (only exhaustion state)."""
        # Same path bug: use_count was read from the real state file, where earlier
        # runs of this very test had already left a non-zero count.
        self.write_cfg([{"name": "acct1", "type": "login"}])

        pool = account_pool.AccountPool()
        acct = pool.accts[0]

        pool.record_use(acct)
        pool.record_use(acct)
        assert pool.state["acct1"]["use_count"] == 2

        pool.mark_exhausted(acct)
        pool.mark_ok(acct)

        assert pool.state["acct1"]["use_count"] == 2

    def test_mark_ok_on_nonexistent_account_is_noop(self):
        """mark_ok() with None or non-existent account leaves state untouched."""
        self.write_cfg([{"name": "acct1", "type": "login"}])

        pool = account_pool.AccountPool()
        pool.record_use(pool.accts[0])

        pool.mark_ok(None)
        pool.mark_ok({"name": "nonexistent"})

        assert pool.state == {"acct1": {"use_count": 1}}


class TestExhaustionFlag(_TempPaths):
    """Test EXHAUSTED_FLAG file lifecycle."""

    def test_all_exhausted_flag_created_when_all_cooling(self):
        """_write_exhausted_flag() creates flag when all accounts cooling."""
        # The flag was being written to (and asserted against) different paths:
        # account_pool.EXHAUSTED_FLAG is fixed at import, so the temp-dir path the
        # test looked at never existed.
        self.write_cfg([{"name": "acct1", "type": "login"}])

        pool = account_pool.AccountPool()
        pool.mark_exhausted(pool.accts[0])

        assert os.path.exists(self.flag_path)
        data = json.load(open(self.flag_path))
        assert data["until"] == pool.state["acct1"]["cooldown_until"]

    def test_all_exhausted_flag_cleared_on_recovery(self):
        """_write_exhausted_flag() removes flag when any account recovers."""
        self.write_cfg([{"name": "acct1", "type": "login"},
                        {"name": "acct2", "type": "login"}])

        pool = account_pool.AccountPool()
        acct1 = [a for a in pool.accts if a["name"] == "acct1"][0]
        acct2 = [a for a in pool.accts if a["name"] == "acct2"][0]

        pool.mark_exhausted(acct1)
        assert not os.path.exists(self.flag_path)  # acct2 still healthy
        pool.mark_exhausted(acct2)
        assert os.path.exists(self.flag_path)

        pool.mark_ok(acct2)
        # After recovery, flag should be gone
        assert not os.path.exists(self.flag_path)

    def test_claude_exhausted_reads_flag(self):
        """claude_exhausted() returns True if flag exists and not stale."""
        self.write_cfg([{"name": "acct1", "type": "login"}])

        pool = account_pool.AccountPool()
        pool.mark_exhausted(pool.accts[0])

        # Reset cache to ensure fresh read
        account_pool._EXH_CACHE["t"] = 0
        assert account_pool.claude_exhausted() is True

    def test_claude_exhausted_falls_back_to_state(self):
        """claude_exhausted() derives state from pool if flag missing."""
        # Used to try to remove a flag file that was never created in the temp dir.
        self.write_cfg([{"name": "acct1", "type": "login"}])

        pool = account_pool.AccountPool()
        pool.mark_exhausted(pool.accts[0])

        os.remove(self.flag_path)

        account_pool._EXH_CACHE["t"] = 0
        assert account_pool.claude_exhausted() is True

    def test_claude_exhausted_false_while_capacity_remains(self):
        """No flag and a healthy account -> the Codex fail-over stays disengaged."""
        self.write_cfg([{"name": "acct1", "type": "login"},
                        {"name": "acct2", "type": "login"}])

        pool = account_pool.AccountPool()
        pool.mark_exhausted([a for a in pool.accts if a["name"] == "acct1"][0])

        account_pool._EXH_CACHE["t"] = 0
        assert account_pool.claude_exhausted() is False


class TestStats(_TempPaths):
    """Test stats() method — the deduplication focus."""

    def test_stats_returns_dict_with_all_fields(self):
        """stats() returns a dict with expected keys."""
        self.write_cfg([{"name": "acct1", "type": "login"},
                        {"name": "acct2", "type": "api", "api_key_env": "KEY"}])

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
        self.write_cfg([{"name": "acct1", "type": "login"}])

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
        # Previously ran against the real state file, where "default" was already
        # cooling from earlier runs, so initial_healthy was 0.
        self.write_cfg([{"name": "a1", "type": "login"},
                        {"name": "a2", "type": "login"}])

        pool = account_pool.AccountPool()
        stats = pool.stats()
        assert stats["total_accounts"] == 2
        assert stats["healthy_count"] == 2

        # Cool down one
        pool.mark_exhausted(pool.accts[0])
        stats = pool.stats()
        assert stats["healthy_count"] == 1
        assert stats["current"] == "a2"
        cooling = [s for s in stats["accounts"] if s["name"] == "a1"][0]
        assert cooling["healthy"] is False
        assert cooling["cooldown_remaining_s"] > 0

    def test_stats_all_exhausted_flag(self):
        """stats()['all_exhausted'] reflects current pool state."""
        # Same real-state-file contamination as above.
        self.write_cfg([{"name": "acct1", "type": "login"}])

        pool = account_pool.AccountPool()
        assert pool.stats()["all_exhausted"] is False

        pool.mark_exhausted(pool.accts[0])
        assert pool.stats()["all_exhausted"] is True

    def test_module_level_stats_delegates_to_singleton(self):
        """Module-level stats() function delegates to singleton pool."""
        self.write_cfg([{"name": "acct1", "type": "login"}])

        # Reset module-level singleton
        account_pool._pool = None
        try:
            stats = account_pool.stats()
            assert stats["total_accounts"] == 1
            assert stats["accounts"][0]["name"] == "acct1"
        finally:
            account_pool._pool = None


class TestBillingGuard(_TempPaths):
    """Test API billing guard integration."""

    # Synthetic placeholder only — never a real credential (see SECURITY.md).
    FAKE_KEY = "sk-test-not-a-real-key"

    # NOTE: env_for() consults subscription_guard.is_api_allowed() directly — it does
    # NOT go through account_pool._api_billing_allowed() (that helper gates capacity
    # accounting in _usable_accounts). Patching the helper, as these tests used to,
    # left the real guard in charge and made the "allowed" case unreachable.
    def test_env_for_api_withholds_key_if_not_allowed(self):
        """env_for() doesn't inject API_KEY if billing guard disallows it."""
        self.write_cfg([{"name": "api_acct", "type": "api", "api_key_env": "MY_KEY"}])

        os.environ["MY_KEY"] = self.FAKE_KEY
        with patch.object(subscription_guard, "is_api_allowed", lambda: False):
            pool = account_pool.AccountPool()
            env = pool.env_for(pool.accts[0])
            assert env == {}

    def test_env_for_api_injects_key_if_allowed(self):
        """env_for() injects API_KEY if billing guard allows it."""
        # env_for() looks up a["api_key_env"]; without the config the pool held the
        # implicit login-type "default" account, so no key was ever injected.
        self.write_cfg([{"name": "api_acct", "type": "api", "api_key_env": "MY_KEY"}])

        os.environ["MY_KEY"] = self.FAKE_KEY
        with patch.object(subscription_guard, "is_api_allowed", lambda: True):
            pool = account_pool.AccountPool()
            env = pool.env_for(pool.accts[0])
            assert env["ANTHROPIC_API_KEY"] == self.FAKE_KEY
            assert env["ORCH_ANTHROPIC_API_ACCOUNT"] == "1"

    def test_env_for_login_injects_config_dir(self):
        """env_for() injects CLAUDE_CONFIG_DIR for login-type accounts."""
        # Same cause: config_dir only exists on the configured account.
        self.write_cfg([{"name": "login_acct", "type": "login", "config_dir": "~/.my-claude"}])

        pool = account_pool.AccountPool()
        env = pool.env_for(pool.accts[0])
        assert "CLAUDE_CONFIG_DIR" in env
        assert env["CLAUDE_CONFIG_DIR"] == os.path.expanduser("~/.my-claude")
        assert "ANTHROPIC_API_KEY" not in env


class TestInvalidate(_TempPaths):
    """Test invalidate() cache-flush and targeted clear."""

    def test_invalidate_clears_specific_cooldown(self):
        """invalidate(name='acct') clears cooldown for that account."""
        # Previously indexed pool.state["acct1"] on a pool holding only "default".
        self.write_cfg([{"name": "acct1", "type": "login"}])

        pool = account_pool.AccountPool()
        pool.mark_exhausted(pool.accts[0])
        assert "cooldown_until" in pool.state["acct1"]

        pool.invalidate("acct1")
        assert "cooldown_until" not in pool.state["acct1"]
        assert "exh_hits" not in pool.state["acct1"]
        # The cross-module fail-over signal is cleared with it.
        assert not os.path.exists(self.flag_path)

    def test_invalidate_without_name_reloads_all(self):
        """invalidate() without name reloads config from disk."""
        self.write_cfg([{"name": "acct1", "type": "login"}])

        pool = account_pool.AccountPool()
        orig_ts = pool._cfg_ts

        # A config change made behind the pool's back is picked up immediately.
        self.write_cfg([{"name": "acct1", "type": "login"},
                        {"name": "acct2", "type": "login"}])
        time.sleep(0.05)
        pool.invalidate()
        assert pool._cfg_ts > orig_ts
        assert [a["name"] for a in pool.accts] == ["acct1", "acct2"]

    def test_module_level_invalidate_delegates(self):
        """Module-level invalidate() delegates to singleton."""
        self.write_cfg([{"name": "acct1", "type": "login"}])

        # Reset singleton
        account_pool._pool = None
        try:
            pool_obj = account_pool._get_pool()
            pool_obj.mark_exhausted(pool_obj.accts[0])
            assert "cooldown_until" in pool_obj.state["acct1"]

            account_pool.invalidate("acct1")
            # After invalidate, cooldown should be cleared
            assert "cooldown_until" not in pool_obj.state.get("acct1", {})
        finally:
            account_pool._pool = None


class TestEdgeCases(_TempPaths):
    """Test boundary conditions and error handling."""

    def test_record_use_on_none_is_noop(self):
        """record_use(None) records nothing."""
        pool = account_pool.AccountPool()
        pool.record_use(None)
        assert pool.state == {}

    def test_mark_exhausted_none_is_noop(self):
        """mark_exhausted(None) changes no state and writes no flag."""
        pool = account_pool.AccountPool()
        assert pool.mark_exhausted(None) is None
        assert pool.state == {}
        assert not os.path.exists(self.flag_path)

    def test_env_for_none_returns_empty_dict(self):
        """env_for(None) returns {}."""
        pool = account_pool.AccountPool()
        env = pool.env_for(None)
        assert env == {}

    def test_multiple_reloads_stable(self):
        """Repeated _maybe_reload() calls don't corrupt state."""
        self.write_cfg([{"name": "acct1", "type": "login"}])

        pool = account_pool.AccountPool()
        pool.record_use(pool.accts[0])
        for _ in range(5):
            pool._maybe_reload()
        assert len(pool.accts) == 1
        assert pool.state["acct1"]["use_count"] == 1

    def test_all_exhausted_with_api_and_billing_guard(self):
        """all_exhausted() respects billing guard when checking usability."""
        # Was reaching into pool.accts for a "sub" entry the pool never loaded
        # (IndexError). The point stands: a disabled API row must not count as
        # capacity, so exhausting the only subscription exhausts the pool.
        self.write_cfg([{"name": "api", "type": "api", "api_key_env": "KEY"},
                        {"name": "sub", "type": "login"}])

        with patch("account_pool._api_billing_allowed", return_value=False):
            pool = account_pool.AccountPool()
            # Only subscription account is usable
            pool.mark_exhausted([a for a in pool.accts if a["name"] == "sub"][0])
            assert pool.all_exhausted() is True

        # With API billing enabled the healthy API row is capacity again.
        with patch("account_pool._api_billing_allowed", return_value=True):
            assert pool.all_exhausted() is False


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
