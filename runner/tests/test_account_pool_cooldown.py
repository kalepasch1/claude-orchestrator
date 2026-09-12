#!/usr/bin/env python3
"""
test_account_pool_cooldown.py - Comprehensive tests for account pool cooldown and exponential backoff logic.

Covers:
- _cooldown() and _cooldown_max() module functions (fixes NameError from bug)
- mark_exhausted() exponential backoff calculation
- Cooldown capping at COOLDOWN_MAX
- Multi-hit backoff progression
- State persistence and reload

ISOLATION NOTE (why _isolated_account_pool_paths is autouse)
------------------------------------------------------------
account_pool resolves its file paths ONCE, at import time:

    HOME  = os.environ.get("CLAUDE_ORCH_HOME", ~/.claude-orchestrator)
    CFG / STATE / EXHAUSTED_FLAG = os.path.join(HOME, ...)

The previous version of this file set CLAUDE_ORCH_HOME inside a fixture, i.e. long
after import, so it changed nothing at all. Every mark_exhausted()/mark_ok()/
record_use() call in this file wrote its cooldowns into whatever HOME had resolved
to for the process:

  * under pytest, runner/tests/conftest.py imports db, and db.py sets
    CLAUDE_ORCH_HOME=<repo>/.runtime at import time -- so the suite wrote the
    FLEET's live runtime state, shared with the running orchestrator and with every
    other test process on the machine;
  * with ORCH_CANONICAL_RUNTIME_HOME=false, or under any entry point that imports
    account_pool before db (this file's own __main__ block, `python -m unittest`,
    a direct import), HOME falls back to the operator's REAL ~/.claude-orchestrator
    and the tests created it and parked accounts named "test-account"/"account-1"
    on hours-long cooldowns.

Either way the state file survived the run, so exh_hits kept climbing across runs and
the backoff assertions failed with "assert 2 == 1", "assert 3 == 1", ... -- results
that depended on machine state rather than on the code under test.

The convention used by the other suites against this module (runner/test_account_pool.py's
_TempPaths, runner/tests/test_account_pool.py) is to rebind the MODULE CONSTANTS
themselves and to restore os.environ afterwards. That is what the autouse fixture below
does; the tests' bodies are otherwise unchanged apart from that redirection and the
assertion fixes noted individually.
"""
import pytest
import json
import os
import shutil
import time
import tempfile
from unittest.mock import patch, MagicMock

# Import the module under test
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import account_pool


# Env vars that change what _cooldown()/_cooldown_max() return. They are cleared for
# every test in this file so the backoff arithmetic below is a property of the code and
# not of whatever a fleet machine (or an earlier test file) happens to export.
_COOLDOWN_ENV_VARS = ("ORCH_ACCOUNT_COOLDOWN", "ACCOUNT_COOLDOWN", "ORCH_ACCOUNT_COOLDOWN_MAX")


@pytest.fixture(autouse=True)
def _isolated_account_pool_paths():
    """Point account_pool's import-time path constants at a fresh temp directory.

    Rebinding the constants is the only thing that works: setting CLAUDE_ORCH_HOME here
    would be too late, because HOME/CFG/STATE/EXHAUSTED_FLAG were already computed when
    the module was imported. CLAUDE_ORCH_HOME is set as well so that anything which
    re-derives a path from it (or a module reloaded downstream) lands in the temp dir too.
    """
    tmpdir = tempfile.mkdtemp(prefix="account-pool-cooldown-")
    env_backup = dict(os.environ)
    orig = (account_pool.HOME, account_pool.CFG, account_pool.STATE,
            account_pool.EXHAUSTED_FLAG)
    orig_singleton = account_pool._pool

    account_pool.HOME = tmpdir
    account_pool.CFG = os.path.join(tmpdir, "accounts.json")
    account_pool.STATE = os.path.join(tmpdir, "accounts_state.json")
    account_pool.EXHAUSTED_FLAG = os.path.join(tmpdir, "claude_exhausted.json")
    account_pool._pool = None          # singleton would otherwise cache the real paths
    os.environ["CLAUDE_ORCH_HOME"] = tmpdir
    for var in _COOLDOWN_ENV_VARS:
        os.environ.pop(var, None)

    try:
        yield tmpdir
    finally:
        (account_pool.HOME, account_pool.CFG, account_pool.STATE,
         account_pool.EXHAUSTED_FLAG) = orig
        account_pool._pool = orig_singleton
        os.environ.clear()
        os.environ.update(env_backup)
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def temp_state_dir(_isolated_account_pool_paths):
    """The temp directory account_pool's path constants are currently bound to."""
    return _isolated_account_pool_paths


@pytest.fixture
def pool_with_temp_state(temp_state_dir):
    """An AccountPool whose config/state/flag files live in the temp directory.

    Was three identical class-local copies of `with patch.dict(os.environ,
    {'CLAUDE_ORCH_HOME': temp_state_dir}): pool = AccountPool()`, which did nothing --
    account_pool had already resolved CFG/STATE/EXHAUSTED_FLAG at import time, so every
    pool read and wrote the shared on-disk state (see the module docstring). The
    redirection now happens on the module constants themselves, in the autouse fixture.
    """
    return account_pool.AccountPool()


class TestCooldownFunctions:
    """Test module-level _cooldown() and _cooldown_max() functions."""

    def test_cooldown_function_returns_module_default(self):
        """_cooldown() returns the module's declared default when nothing overrides it."""
        # Was: `assert result == account_pool.COOLDOWN`. COOLDOWN is a snapshot taken once
        # at import (account_pool.py:55-57) and documented there as read-only for external
        # readers; the write path calls _cooldown(), which re-reads the env on every call.
        # The two disagree whenever anything exported ORCH_ACCOUNT_COOLDOWN before
        # account_pool was first imported -- and this file used to cause exactly that
        # itself, by reloading the module inside a patch.dict (see
        # TestCooldownEnvironmentVariables). So the old assertion measured the suite's
        # import order, not the function. Compare against the declared default instead.
        result = account_pool._cooldown()
        assert isinstance(result, int)
        assert result > 0
        assert result == account_pool._COOLDOWN_DEFAULT

    def test_cooldown_max_function_returns_module_default(self):
        """_cooldown_max() returns the module's declared ceiling, above the base cooldown."""
        # Same reason as above: was asserting against the frozen COOLDOWN_MAX/COOLDOWN pair.
        result = account_pool._cooldown_max()
        assert isinstance(result, int)
        assert result == account_pool._COOLDOWN_MAX_DEFAULT
        assert result > account_pool._cooldown()  # ceiling must exceed the base cooldown

    def test_cooldown_default_is_1200_seconds(self):
        """_cooldown() falls back to 20 minutes (1200 seconds) when env vars not set."""
        # _cooldown() reads env at call time, so clear the overrides a fleet
        # machine may export (patch.dict restores them on exit).
        with patch.dict(os.environ):
            os.environ.pop("ORCH_ACCOUNT_COOLDOWN", None)
            os.environ.pop("ACCOUNT_COOLDOWN", None)
            assert account_pool._cooldown() == 20 * 60

    def test_cooldown_max_default_is_6_hours(self):
        """_cooldown_max() falls back to 6 hours (21600 seconds) when env vars not set."""
        with patch.dict(os.environ):
            os.environ.pop("ORCH_ACCOUNT_COOLDOWN_MAX", None)
            assert account_pool._cooldown_max() == 6 * 3600


class TestMarkExhaustedBackoff:
    """Test mark_exhausted() exponential backoff calculation."""

    def test_first_exhaustion_sets_base_cooldown(self, pool_with_temp_state):
        """First exhaustion (hits=1) sets cooldown to base COOLDOWN value."""
        pool = pool_with_temp_state
        acct = {"name": "test-account", "type": "login"}
        now = time.time()

        pool.mark_exhausted(acct)

        state = pool.state[acct["name"]]
        cooldown_until = state["cooldown_until"]
        elapsed = cooldown_until - now

        # First hit: no backoff, should be close to the base cooldown.
        # Was comparing against account_pool.COOLDOWN, the import-time snapshot.
        # mark_exhausted() computes its cooldown from _cooldown() (account_pool.py:301),
        # which re-reads the env, so that is the value the assertion has to use; the two
        # silently diverge once anything sets ORCH_ACCOUNT_COOLDOWN mid-session.
        assert state["exh_hits"] == 1
        assert abs(elapsed - account_pool._cooldown()) < 1  # within 1 second

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

        # Should have doubled (see the note in test_first_exhaustion_sets_base_cooldown
        # for why this is _cooldown() and not the frozen COOLDOWN constant).
        assert pool.state[acct["name"]]["exh_hits"] == 2
        assert abs((second_cooldown_until - first_cooldown_until) - account_pool._cooldown()) < 1

    def test_exponential_backoff_progression(self, pool_with_temp_state):
        """Multiple exhaustions follow exponential backoff: base, 2x, 4x, 8x, ..."""
        pool = pool_with_temp_state
        acct = {"name": "test-account", "type": "login"}
        base = account_pool._cooldown()

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
        base = account_pool._cooldown()
        max_cd = account_pool._cooldown_max()

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
        assert abs(elapsed - account_pool._cooldown()) < 1

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
        assert acct_stat["cooldown_remaining_s"] <= account_pool._cooldown() + 1


class TestCooldownEnvironmentVariables:
    """Test environment variable override of cooldown values."""

    def test_orch_account_cooldown_env_var_overrides(self, pool_with_temp_state):
        """ORCH_ACCOUNT_COOLDOWN is honoured by the cooldown mark_exhausted writes."""
        # Was: importlib.reload(account_pool) inside the patch.dict, then asserting on the
        # reloaded module constant COOLDOWN. Three things were wrong with that.
        #   1. reload() mutates the module object shared through sys.modules, so it
        #      re-derived HOME/CFG/STATE/EXHAUSTED_FLAG from the env live at that moment
        #      and silently undid this file's path isolation -- for every test after it,
        #      in this file and in every later file of the session.
        #   2. patch.dict restores os.environ on exit but cannot un-reload a module, so
        #      COOLDOWN stayed pinned at the override for the rest of the run. That leak is
        #      what made TestEdgeCases::test_cooldown_calculation_precision compare an
        #      actual 1200 against a base of 900 left behind by the test below.
        #      (It is the same class of leak as the ORCH_ACCOUNT_COOLDOWN_MAX=500 one
        #      called out in runner/test_account_pool.py's _TempPaths.)
        #   3. COOLDOWN is not what the override is for: mark_exhausted() calls _cooldown()
        #      (account_pool.py:301) precisely so a hot_reload of the fleet config takes
        #      effect without a restart. Assert on that live path instead.
        pool = pool_with_temp_state
        acct = {"name": "test-account", "type": "login"}

        with patch.dict(os.environ, {'ORCH_ACCOUNT_COOLDOWN': '600'}):
            assert account_pool._cooldown() == 600
            now = time.time()
            pool.mark_exhausted(acct)
            elapsed = pool.state[acct["name"]]["cooldown_until"] - now
            assert abs(elapsed - 600) < 1

    def test_account_cooldown_fallback_env_var(self):
        """ACCOUNT_COOLDOWN is the fallback; ORCH_ACCOUNT_COOLDOWN takes precedence."""
        # Was: reload the module (see above) and then
        #     assert ap.COOLDOWN == 900 or ap.COOLDOWN == 20 * 60
        # -- an assertion that accepted both the override and the untouched default, so it
        # held no matter what the code did. The precedence it claims to test is now
        # asserted directly, one branch at a time.
        with patch.dict(os.environ):
            os.environ.pop('ORCH_ACCOUNT_COOLDOWN', None)
            os.environ['ACCOUNT_COOLDOWN'] = '900'
            assert account_pool._cooldown() == 900

            # ORCH_-prefixed name wins when both are set (account_pool.py:47-48).
            os.environ['ORCH_ACCOUNT_COOLDOWN'] = '300'
            assert account_pool._cooldown() == 300

    def test_write_path_ignores_frozen_module_constant(self, pool_with_temp_state):
        """mark_exhausted() follows the live env, not the import-time COOLDOWN snapshot.

        New test. account_pool.py:305-307 records that using the frozen COOLDOWN on the
        write path was a real bug (the dashboard showed a 20-minute reset for an account
        actually parked for hours). Nothing covered that, and the reload-based tests this
        class used to contain actively hid it by keeping COOLDOWN in sync with the env.
        """
        pool = pool_with_temp_state
        acct = {"name": "test-account", "type": "login"}
        frozen = account_pool.COOLDOWN

        with patch.dict(os.environ, {'ORCH_ACCOUNT_COOLDOWN': str(frozen + 777)}):
            now = time.time()
            pool.mark_exhausted(acct)
            elapsed = pool.state[acct["name"]]["cooldown_until"] - now

        assert abs(elapsed - (frozen + 777)) < 1
        assert account_pool.COOLDOWN == frozen, "COOLDOWN must stay a read-only snapshot"


class TestEdgeCases:
    """Test edge cases and error conditions."""

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
            assert elapsed <= account_pool._cooldown_max() + 1
            assert pool.state[acct["name"]]["exh_hits"] == i

    def test_cooldown_calculation_precision(self, pool_with_temp_state):
        """Cooldown calculation uses correct formula: base * 2^(hits-1) capped at max."""
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

            # Verify formula matches implementation
            assert abs(actual - expected) < 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
