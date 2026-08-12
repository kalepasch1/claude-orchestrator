#!/usr/bin/env python3
"""
test_account_pool_cooldown.py - tests for account pool cooldown and exponential backoff.

Covers:
- _cooldown() and _cooldown_max() module functions (fixes NameError from bug)
- mark_exhausted() exponential backoff calculation
- Cooldown capping at COOLDOWN_MAX
- Multi-hit backoff progression
- State persistence and reload

ISOLATION (fixed 2026-08-12) — read before touching the fixtures.

The previous `pool_with_temp_state` fixture patched the *environment variable*
`CLAUDE_ORCH_HOME` and then constructed an AccountPool. That never isolated anything:
`account_pool.HOME`, `CFG`, `STATE` and `EXHAUSTED_FLAG` are module-level constants
computed once at import time, so patching the env afterwards has no effect. Every test
in this file therefore read and *wrote* the real `~/.claude-orchestrator/accounts_state.json`
and pushed cooldowns to the production Supabase `accounts` table via `mark_exhausted`.

That produced 14 failures (tests saw live accounts like `account-1` with 63 exh_hits
instead of their own fixture state) and, worse, mutated live fleet rotation state on
every test run. The fixture below patches the module constants themselves and stubs the
`db` calls, which is what actually isolates this module.

ENVIRONMENT-DEPENDENT DEFAULTS — the second cause of failures here.

`COOLDOWN` / `COOLDOWN_MAX` are import-time snapshots of `ORCH_ACCOUNT_COOLDOWN` /
`ORCH_ACCOUNT_COOLDOWN_MAX`. Importing `db` (which `conftest.py` does before any test
module loads) populates those vars from fleet config — 300/1800 on this fleet today.
So `assert account_pool.COOLDOWN == 20 * 60` asserts that nobody has tuned the fleet,
which is not a property of the code. The default is now asserted hermetically against
`_cooldown()` with the env cleared, and the backoff tests compare against `_cooldown()`
— the call-time reader that `mark_exhausted` actually uses — rather than the stale
import-time constant.
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


@pytest.fixture
def temp_state_dir():
    """Create a temporary directory for state files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def pool_with_temp_state(temp_state_dir):
    """An AccountPool whose state/config/flag files live in a temp dir.

    Patches the module-level path constants (not the env var — see module docstring)
    and stubs the Supabase reads/writes so no test touches the live accounts table.
    """
    state_path = os.path.join(temp_state_dir, "accounts_state.json")
    cfg_path = os.path.join(temp_state_dir, "accounts.json")
    flag_path = os.path.join(temp_state_dir, "claude_exhausted.json")
    with patch.object(account_pool, "HOME", temp_state_dir), \
         patch.object(account_pool, "STATE", state_path), \
         patch.object(account_pool, "CFG", cfg_path), \
         patch.object(account_pool, "EXHAUSTED_FLAG", flag_path), \
         patch.dict(os.environ, {"CLAUDE_ORCH_HOME": temp_state_dir}), \
         patch("db.select", return_value=[]), \
         patch("db.update", return_value=None):
        pool = account_pool.AccountPool()
        # _load_cfg falls back to the implicit single account when the DB returns
        # nothing and no local accounts.json exists.
        assert pool.state == {}, "fixture did not isolate state"
        yield pool


class TestCooldownFunctions:
    """Test module-level _cooldown() and _cooldown_max() functions."""

    def test_cooldown_function_returns_constant(self):
        """_cooldown() returns an int cooldown consistent with the current env."""
        result = account_pool._cooldown()
        assert isinstance(result, int)
        assert result > 0

    def test_cooldown_max_function_returns_constant(self):
        """_cooldown_max() exceeds the base cooldown."""
        result = account_pool._cooldown_max()
        assert isinstance(result, int)
        assert result > account_pool._cooldown()

    def test_cooldown_default_is_1200_seconds(self):
        """With no env override, the cooldown default is 20 minutes.

        Asserted against _cooldown() with the env cleared rather than against the
        import-time COOLDOWN constant, which reflects whatever the fleet has tuned.
        """
        with patch.dict(os.environ, {}, clear=True):
            assert account_pool._cooldown() == 20 * 60
            assert account_pool._COOLDOWN_DEFAULT == 20 * 60

    def test_cooldown_max_default_is_6_hours(self):
        """With no env override, the cooldown ceiling default is 6 hours."""
        with patch.dict(os.environ, {}, clear=True):
            assert account_pool._cooldown_max() == 6 * 3600
            assert account_pool._COOLDOWN_MAX_DEFAULT == 6 * 3600


class TestMarkExhaustedBackoff:
    """Test mark_exhausted() exponential backoff calculation."""

    def test_first_exhaustion_sets_base_cooldown(self, pool_with_temp_state):
        """First exhaustion (hits=1) sets cooldown to the base cooldown value."""
        pool = pool_with_temp_state
        acct = {"name": "test-account", "type": "login"}
        now = time.time()

        pool.mark_exhausted(acct)

        state = pool.state[acct["name"]]
        elapsed = state["cooldown_until"] - now

        # First hit: no backoff, should be close to the base cooldown
        assert state["exh_hits"] == 1
        assert abs(elapsed - account_pool._cooldown()) < 1  # within 1 second

    def test_second_exhaustion_doubles_cooldown(self, pool_with_temp_state):
        """Second exhaustion (hits=2) doubles the cooldown."""
        pool = pool_with_temp_state
        acct = {"name": "test-account", "type": "login"}

        pool.mark_exhausted(acct)
        first_cooldown_until = pool.state[acct["name"]]["cooldown_until"]

        pool.mark_exhausted(acct)
        second_cooldown_until = pool.state[acct["name"]]["cooldown_until"]

        assert pool.state[acct["name"]]["exh_hits"] == 2
        assert abs((second_cooldown_until - first_cooldown_until)
                   - account_pool._cooldown()) < 1

    def test_exponential_backoff_progression(self, pool_with_temp_state):
        """Multiple exhaustions follow exponential backoff: base, 2x, 4x, 8x, ..."""
        pool = pool_with_temp_state
        acct = {"name": "test-account", "type": "login"}
        base = account_pool._cooldown()
        max_cd = account_pool._cooldown_max()

        for i in range(1, 6):
            now = time.time()
            pool.mark_exhausted(acct)
            # The implementation caps each step at the ceiling; mirror that here so the
            # test stays correct when the fleet tunes the base/ceiling ratio.
            expected = min(base * (2 ** (i - 1)), max_cd)
            actual = pool.state[acct["name"]]["cooldown_until"] - now
            assert abs(actual - expected) < 2, f"Hit {i}: expected {expected}, got {actual}"

    def test_cooldown_capped_at_max(self, pool_with_temp_state):
        """Exponential backoff is capped at the cooldown ceiling."""
        pool = pool_with_temp_state
        acct = {"name": "test-account", "type": "login"}
        max_cd = account_pool._cooldown_max()

        for i in range(1, 8):
            now = time.time()
            pool.mark_exhausted(acct)
            elapsed = pool.state[acct["name"]]["cooldown_until"] - now

            assert elapsed <= max_cd + 1  # +1s tolerance
            assert pool.state[acct["name"]]["exh_hits"] == i

    def test_mark_ok_resets_backoff_counter(self, pool_with_temp_state):
        """mark_ok() resets exh_hits so the next limit starts at the base cooldown."""
        pool = pool_with_temp_state
        acct = {"name": "test-account", "type": "login"}

        pool.mark_exhausted(acct)
        pool.mark_exhausted(acct)
        assert pool.state[acct["name"]]["exh_hits"] == 2

        pool.mark_ok(acct)
        assert "exh_hits" not in pool.state[acct["name"]]

        now = time.time()
        pool.mark_exhausted(acct)
        elapsed = pool.state[acct["name"]]["cooldown_until"] - now
        assert pool.state[acct["name"]]["exh_hits"] == 1
        assert abs(elapsed - account_pool._cooldown()) < 1

    def test_mark_exhausted_with_none_account_is_safe(self, pool_with_temp_state):
        """mark_exhausted(None) does not crash (fail-soft)."""
        pool = pool_with_temp_state
        result = pool.mark_exhausted(None)
        assert result is None

    def test_mark_exhausted_saves_state(self, pool_with_temp_state, temp_state_dir):
        """mark_exhausted() persists state to disk."""
        pool = pool_with_temp_state
        acct = {"name": "test-account", "type": "login"}

        pool.mark_exhausted(acct)

        # Read the temp state file back directly — constructing a second AccountPool
        # here would re-enter _load_cfg and hit the live DB.
        with open(os.path.join(temp_state_dir, "accounts_state.json")) as fh:
            saved = json.load(fh)
        assert acct["name"] in saved
        assert saved[acct["name"]]["exh_hits"] == 1
        assert "cooldown_until" in saved[acct["name"]]


class TestCooldownIntegration:
    """Integration tests for cooldown behavior across pool operations."""

    def test_healthy_check_respects_cooldown(self, pool_with_temp_state):
        """_healthy() returns False while cooldown is active."""
        pool = pool_with_temp_state
        acct = {"name": "test-account", "type": "login"}

        assert pool._healthy(acct)

        pool.mark_exhausted(acct)
        assert not pool._healthy(acct)

        pool.state[acct["name"]]["cooldown_until"] = time.time() - 1
        assert pool._healthy(acct)

    def test_current_account_rotates_on_exhaustion(self, pool_with_temp_state):
        """current() rotates to next account when one is exhausted."""
        pool = pool_with_temp_state
        acct1 = {"name": "account-1", "type": "login"}
        acct2 = {"name": "account-2", "type": "login"}

        pool.accts = [acct1, acct2]

        current = pool.current()
        assert current["name"] == "account-1"

        pool.mark_exhausted(acct1)

        current = pool.current()
        assert current["name"] == "account-2"

    def test_all_accounts_exhausted_flag(self, pool_with_temp_state):
        """all_exhausted() returns True when no accounts are healthy."""
        pool = pool_with_temp_state
        acct1 = {"name": "account-1", "type": "login"}
        acct2 = {"name": "account-2", "type": "login"}
        pool.accts = [acct1, acct2]

        assert not pool.all_exhausted()

        pool.mark_exhausted(acct1)
        assert not pool.all_exhausted()  # second is still healthy

        pool.mark_exhausted(acct2)
        assert pool.all_exhausted()  # all are cooling

    def test_stats_reflects_cooldown_state(self, pool_with_temp_state):
        """stats() reports correct cooldown_remaining_s for each account."""
        pool = pool_with_temp_state
        acct = {"name": "test-account", "type": "login"}
        pool.accts = [acct]

        stats = pool.stats()
        acct_stat = stats["accounts"][0]
        assert acct_stat["healthy"]
        assert acct_stat["cooldown_remaining_s"] == 0

        pool.mark_exhausted(acct)
        stats = pool.stats()
        acct_stat = stats["accounts"][0]
        assert not acct_stat["healthy"]
        assert acct_stat["cooldown_remaining_s"] > 0
        assert acct_stat["cooldown_remaining_s"] <= account_pool._cooldown() + 1


class TestCooldownEnvironmentVariables:
    """Test environment variable override of cooldown values.

    These exercise `_cooldown()` under a patched env rather than `importlib.reload`.
    Reloading rebinds the module-level COOLDOWN for the rest of the session — the
    patch.dict context exits but the reloaded constant does not revert — which is a
    cross-test pollution source, and the reload also re-runs module import side effects.
    """

    def test_orch_account_cooldown_env_var_overrides(self):
        """ORCH_ACCOUNT_COOLDOWN overrides the default."""
        with patch.dict(os.environ, {"ORCH_ACCOUNT_COOLDOWN": "600"}):
            assert account_pool._cooldown() == 600

    def test_account_cooldown_fallback_env_var(self):
        """ACCOUNT_COOLDOWN is the fallback when ORCH_ACCOUNT_COOLDOWN is unset."""
        with patch.dict(os.environ, {"ACCOUNT_COOLDOWN": "900"}, clear=True):
            assert account_pool._cooldown() == 900

    def test_orch_prefix_wins_over_bare_name(self):
        """ORCH_-prefixed key takes precedence over the bare fallback."""
        with patch.dict(os.environ,
                        {"ORCH_ACCOUNT_COOLDOWN": "600", "ACCOUNT_COOLDOWN": "900"},
                        clear=True):
            assert account_pool._cooldown() == 600

    def test_cooldown_max_env_var_overrides(self):
        """ORCH_ACCOUNT_COOLDOWN_MAX overrides the ceiling."""
        with patch.dict(os.environ, {"ORCH_ACCOUNT_COOLDOWN_MAX": "7200"}, clear=True):
            assert account_pool._cooldown_max() == 7200


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_mark_exhausted_with_missing_account_creates_state(self, pool_with_temp_state):
        """mark_exhausted() creates a state entry for an unseen account."""
        pool = pool_with_temp_state
        acct = {"name": "new-account", "type": "login"}

        assert acct["name"] not in pool.state
        pool.mark_exhausted(acct)
        assert acct["name"] in pool.state
        assert pool.state[acct["name"]]["exh_hits"] == 1

    def test_large_number_of_exhaustion_hits(self, pool_with_temp_state):
        """Backoff stays capped and the counter stays correct over many hits."""
        pool = pool_with_temp_state
        acct = {"name": "test-account", "type": "login"}
        max_cd = account_pool._cooldown_max()

        for i in range(1, 21):
            now = time.time()
            pool.mark_exhausted(acct)
            elapsed = pool.state[acct["name"]]["cooldown_until"] - now

            assert elapsed <= max_cd + 1
            assert pool.state[acct["name"]]["exh_hits"] == i

    def test_large_hit_count_does_not_overflow(self, pool_with_temp_state):
        """A very large exh_hits does not blow up 2**(hits-1) into an absurd cooldown."""
        pool = pool_with_temp_state
        acct = {"name": "test-account", "type": "login"}
        pool.state[acct["name"]] = {"exh_hits": 500}

        now = time.time()
        pool.mark_exhausted(acct)
        elapsed = pool.state[acct["name"]]["cooldown_until"] - now
        assert elapsed <= account_pool._cooldown_max() + 1

    def test_cooldown_calculation_precision(self, pool_with_temp_state):
        """Cooldown formula is base * 2^(hits-1) capped at max."""
        pool = pool_with_temp_state
        acct = {"name": "test-account", "type": "login"}
        base = account_pool._cooldown()
        max_cd = account_pool._cooldown_max()

        for hits in range(1, 6):
            pool.state[acct["name"]] = {"exh_hits": hits - 1}
            now = time.time()
            pool.mark_exhausted(acct)

            expected = min(base * (2 ** (hits - 1)), max_cd)
            actual = pool.state[acct["name"]]["cooldown_until"] - now

            assert abs(actual - expected) < 1


class TestStateIsolationRegression:
    """Guard the isolation defect this file was fixed for (2026-08-12)."""

    def test_fixture_redirects_module_state_path(self, pool_with_temp_state, temp_state_dir):
        """The pool must write to the temp dir, never to the real orchestrator home."""
        assert account_pool.STATE.startswith(temp_state_dir)
        assert account_pool.CFG.startswith(temp_state_dir)
        assert account_pool.EXHAUSTED_FLAG.startswith(temp_state_dir)

        real_home = os.path.expanduser("~/.claude-orchestrator")
        assert not account_pool.STATE.startswith(real_home)

        pool_with_temp_state.mark_exhausted({"name": "isolation-probe", "type": "login"})
        assert os.path.isfile(os.path.join(temp_state_dir, "accounts_state.json"))

    def test_module_constants_restored_after_fixture(self):
        """Patches unwind — the real paths are back once the fixture exits."""
        assert account_pool.STATE.endswith("accounts_state.json")
        assert tempfile.gettempdir() not in account_pool.STATE


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
