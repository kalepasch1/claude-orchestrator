#!/usr/bin/env python3
"""
test_account_pool_secret_outcomes.py - Verify secrets are handled safely and outcomes are attested.

Tests validate:
- env_for() does not expose secrets when billing guard is disabled
- Secrets (ANTHROPIC_API_KEY, config dirs) are not logged in errors
- Account rotation outcomes (current, exhaustion) are observable without secret leaks
- API billing guard enforcement across all code paths
- mark_exhausted/mark_ok preserve outcome correctness
- Fail-soft behavior on missing/corrupt secret state
- Thread-safety of secret-bearing state
"""

import os
import shutil
import sys
import time
import json
import tempfile
import threading

import pytest

RUNNER = os.path.dirname(os.path.abspath(__file__))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import account_pool
import subscription_guard


@pytest.fixture(autouse=True)
def _isolated_account_pool_paths():
    """Point account_pool's import-time path constants at a fresh temp directory.

    ISOLATION NOTE
    --------------
    account_pool resolves its file paths ONCE, at import time:

        HOME  = os.environ.get("CLAUDE_ORCH_HOME", ~/.claude-orchestrator)
        CFG / STATE / EXHAUSTED_FLAG = os.path.join(HOME, ...)

    Nearly every test below calls account_pool.AccountPool(), which reads CFG and STATE,
    and the mark_exhausted/mark_ok/record_use tests then write STATE and EXHAUSTED_FLAG
    back through those same constants. Nothing here redirected them, so the suite read and
    wrote shared on-disk state: <repo>/.runtime under pytest (db.py sets CLAUDE_ORCH_HOME
    there at import time), or the operator's REAL ~/.claude-orchestrator under any entry
    point that imports account_pool before db -- this file's own __main__ block, a direct
    import, or ORCH_CANONICAL_RUNTIME_HOME=false. In the last case a test run created that
    directory and parked accounts on multi-hour cooldowns.

    Setting CLAUDE_ORCH_HOME from a fixture cannot fix that: the constants are already
    bound. The convention in this repo -- runner/test_account_pool.py's _TempPaths, and
    the monkeypatch.setattr(account_pool, "EXHAUSTED_FLAG", ...) already used piecemeal
    further down this file -- is to rebind the MODULE CONSTANTS and restore os.environ
    afterwards, which is what this does for every test at once.

    _EXH_CACHE is reset alongside the paths: claude_exhausted() memoises its answer on a
    module global for ~15s, so without this a cached True/False from one test decided the
    result of the next one (and of the next file).
    """
    tmpdir = tempfile.mkdtemp(prefix="account-pool-secrets-")
    env_backup = dict(os.environ)
    orig = (account_pool.HOME, account_pool.CFG, account_pool.STATE,
            account_pool.EXHAUSTED_FLAG)
    orig_singleton = account_pool._pool
    orig_cache = dict(account_pool._EXH_CACHE)

    account_pool.HOME = tmpdir
    account_pool.CFG = os.path.join(tmpdir, "accounts.json")
    account_pool.STATE = os.path.join(tmpdir, "accounts_state.json")
    account_pool.EXHAUSTED_FLAG = os.path.join(tmpdir, "claude_exhausted.json")
    account_pool._pool = None          # singleton would otherwise cache the real paths
    account_pool._EXH_CACHE.update({"t": 0.0, "v": False})
    os.environ["CLAUDE_ORCH_HOME"] = tmpdir

    try:
        yield tmpdir
    finally:
        (account_pool.HOME, account_pool.CFG, account_pool.STATE,
         account_pool.EXHAUSTED_FLAG) = orig
        account_pool._pool = orig_singleton
        account_pool._EXH_CACHE.update(orig_cache)
        os.environ.clear()
        os.environ.update(env_backup)
        shutil.rmtree(tmpdir, ignore_errors=True)


class TestEnvForSecretExposure:
    """Verify env_for() respects billing guard and does not leak secrets."""

    def test_env_for_none_account_returns_empty_dict(self):
        """env_for(None) returns empty dict without error."""
        result = account_pool.AccountPool().env_for(None)
        assert result == {}, f"Expected empty dict, got {result}"

    def test_env_for_api_with_guard_disabled_withholds_key(self, monkeypatch):
        """env_for() withholds ANTHROPIC_API_KEY when billing guard disables API."""
        # Was patching account_pool._api_billing_allowed, which env_for() never calls --
        # env_for consults subscription_guard.is_api_allowed() directly
        # (account_pool.py:277-283). _api_billing_allowed is the seam for
        # _usable_accounts()/all_exhausted(). This test passed only because the ambient
        # guard denies by default, so it would have kept passing even if env_for's guard
        # were deleted. Patch the seam env_for really reads, and pin the
        # ORCH_ALLOW_API_BILLING fallback off so the except branch cannot re-open the key.
        monkeypatch.setattr(subscription_guard, "is_api_allowed", lambda: False)
        monkeypatch.setenv("ORCH_ALLOW_API_BILLING", "false")
        monkeypatch.setenv("TEST_API_KEY", "sk-test-secret-1234567890abcdef")

        pool = account_pool.AccountPool()
        acct = {"name": "api-test", "type": "api", "api_key_env": "TEST_API_KEY"}

        env = pool.env_for(acct)

        assert "ANTHROPIC_API_KEY" not in env, "Billing guard should prevent API key injection"
        assert env == {}, f"Expected empty env when guard disabled, got {env}"

    def test_env_for_api_with_guard_enabled_injects_key(self, monkeypatch):
        """env_for() injects ANTHROPIC_API_KEY only when billing guard enables API."""
        # Seam fix (see test_env_for_api_with_guard_disabled_withholds_key): patching
        # account_pool._api_billing_allowed did nothing, the real guard denied, and no key
        # was ever injected -- this test failed with KeyError: 'ANTHROPIC_API_KEY'.
        test_key = "sk-test-secret-1234567890abcdef"
        monkeypatch.setattr(subscription_guard, "is_api_allowed", lambda: True)
        monkeypatch.setenv("MY_API_KEY_ENV", test_key)

        pool = account_pool.AccountPool()
        acct = {"name": "api-test", "type": "api", "api_key_env": "MY_API_KEY_ENV"}

        env = pool.env_for(acct)

        assert env["ANTHROPIC_API_KEY"] == test_key
        assert env["ORCH_ANTHROPIC_API_ACCOUNT"] == "1"

    def test_env_for_api_missing_key_returns_empty(self, monkeypatch):
        """env_for() returns empty dict when API key env var is not set."""
        # Seam fix (see above): with the wrong seam the guard denied first, so the test
        # never reached the "key env var is unset" path it is named for.
        monkeypatch.setattr(subscription_guard, "is_api_allowed", lambda: True)
        monkeypatch.delenv("MISSING_API_KEY", raising=False)

        pool = account_pool.AccountPool()
        acct = {"name": "api-test", "type": "api", "api_key_env": "MISSING_API_KEY"}

        env = pool.env_for(acct)

        assert env == {}, f"Missing key should yield empty env, got {env}"

    def test_env_for_login_type_sets_config_dir(self, monkeypatch):
        """env_for() sets CLAUDE_CONFIG_DIR for login-type accounts."""
        pool = account_pool.AccountPool()
        acct = {
            "name": "personal-max",
            "type": "login",
            "config_dir": "~/.claude-personal",
        }

        env = pool.env_for(acct)

        assert "CLAUDE_CONFIG_DIR" in env
        assert env["CLAUDE_CONFIG_DIR"] == os.path.expanduser("~/.claude-personal")
        assert "ANTHROPIC_API_KEY" not in env, "Login type should not inject API key"

    def test_env_for_subscription_type_returns_empty(self):
        """env_for() returns empty dict for subscription-type accounts (use default login)."""
        pool = account_pool.AccountPool()
        acct = {"name": "subscription-1", "type": "subscription"}

        env = pool.env_for(acct)

        assert env == {}, f"Subscription type should return empty env, got {env}"

    def test_env_for_api_guard_exception_defaults_to_deny(self, monkeypatch):
        """env_for() denies API injection if billing guard raises exception."""
        # Was making account_pool._api_billing_allowed raise. env_for() never calls it, so
        # no exception ever reached env_for's `except` branch and the assertion passed for
        # the wrong reason -- the ordinary deny path returned {} first. Raise from the
        # function env_for actually calls, so the fail-soft branch is the one under test.
        def guard_error():
            raise RuntimeError("subscription_guard blew up")
        monkeypatch.setattr(subscription_guard, "is_api_allowed", guard_error)
        monkeypatch.delenv("ORCH_ALLOW_API_BILLING", raising=False)

        pool = account_pool.AccountPool()
        acct = {"name": "api-test", "type": "api", "api_key_env": "SOME_KEY"}

        env = pool.env_for(acct)

        assert env == {}, "Guard exception should fail-soft to deny"

    def test_env_for_api_guard_exception_with_env_override(self, monkeypatch):
        """env_for() allows API when guard errors but ORCH_ALLOW_API_BILLING=true."""
        # Same seam fix: _api_billing_allowed is not on env_for's path, so the guard never
        # raised, env_for took the normal deny return, and this test failed with
        # `assert 'ANTHROPIC_API_KEY' in {}`.
        def guard_error():
            raise RuntimeError("subscription_guard blew up")
        monkeypatch.setattr(subscription_guard, "is_api_allowed", guard_error)
        monkeypatch.setenv("ORCH_ALLOW_API_BILLING", "true")
        monkeypatch.setenv("FALLBACK_KEY_ENV", "sk-fallback-key")

        pool = account_pool.AccountPool()
        acct = {"name": "api-test", "type": "api", "api_key_env": "FALLBACK_KEY_ENV"}

        env = pool.env_for(acct)

        assert "ANTHROPIC_API_KEY" in env


class TestMarkExhaustedOutcomes:
    """Verify mark_exhausted() correctly updates state and attests outcome without leaking secrets."""

    def test_mark_exhausted_none_account_returns_none(self):
        """mark_exhausted(None) returns None and does not error."""
        pool = account_pool.AccountPool()
        pool.accts = [{"name": "acct1", "type": "login"}]
        pool.state = {}
        pool._cfg_ts = time.time()
        pool._state_ts = time.time()

        result = pool.mark_exhausted(None)

        assert result is None

    def test_mark_exhausted_sets_cooldown_until(self):
        """mark_exhausted() sets cooldown_until to current_time + _cooldown()."""
        before = time.time()
        pool = account_pool.AccountPool()
        pool.accts = [{"name": "acct1", "type": "login"}]
        pool.state = {}
        pool._cfg_ts = time.time()
        pool._state_ts = time.time()
        acct = pool.accts[0]

        pool.mark_exhausted(acct)

        after = time.time()
        cooldown_until = pool.state["acct1"]["cooldown_until"]
        expected_min = before + account_pool._cooldown()
        expected_max = after + account_pool._cooldown()
        assert expected_min <= cooldown_until <= expected_max, \
            f"Cooldown {cooldown_until} not in range [{expected_min}, {expected_max}]"

    def test_mark_exhausted_increments_exh_hits(self):
        """mark_exhausted() increments exh_hits for exponential backoff."""
        pool = account_pool.AccountPool()
        pool.accts = [
            {"name": "acct1", "type": "login"},
            {"name": "acct2", "type": "login"},
        ]
        pool.state = {}
        pool._cfg_ts = time.time()
        pool._state_ts = time.time()

        pool.mark_exhausted(pool.accts[0])
        assert pool.state["acct1"]["exh_hits"] == 1

        pool.mark_exhausted(pool.accts[0])
        assert pool.state["acct1"]["exh_hits"] == 2

    def test_mark_exhausted_exponential_backoff_caps_at_max(self):
        """mark_exhausted() exponential backoff doubles but never exceeds COOLDOWN_MAX."""
        pool = account_pool.AccountPool()
        pool.accts = [{"name": "acct1", "type": "login"}]
        pool.state = {"acct1": {"exh_hits": 99}}  # Simulate many prior hits
        pool._cfg_ts = time.time()
        pool._state_ts = time.time()

        before = time.time()
        pool.mark_exhausted(pool.accts[0])
        after = time.time()

        cooldown_until = pool.state["acct1"]["cooldown_until"]
        max_allowed = after + account_pool._cooldown_max()
        assert cooldown_until <= max_allowed, \
            f"Backoff {cooldown_until} exceeds COOLDOWN_MAX {max_allowed}"

    def test_mark_exhausted_returns_next_account_name(self):
        """mark_exhausted() returns the name of the next healthy account."""
        pool = account_pool.AccountPool()
        pool.accts = [
            {"name": "acct1", "type": "login"},
            {"name": "acct2", "type": "login"},
        ]
        pool.state = {}
        pool._cfg_ts = time.time()
        pool._state_ts = time.time()

        result = pool.mark_exhausted(pool.accts[0])

        assert result == "acct2", f"Expected next account name, got {result}"

    def test_mark_exhausted_sole_account_returns_its_own_name(self, monkeypatch):
        """Exhausting the only account hands its own name back: no rotation is available."""
        # Was: `assert result is None`. mark_exhausted() returns current()["name"], and
        # current() is documented to return "the one that frees up soonest" when everything
        # is cooling (account_pool.py:226-229); it returns None only for an EMPTY pool, so
        # None was unreachable here and the test asserted a contract the product does not
        # have. The real caller uses the actual one: runner.py:2001 is
        # `if nxt and nxt != (acct or {}).get("name"): attempt -= 1` -- it detects "no
        # rotation" by comparing names, which is also why account_pool.py:317-320 insists on
        # comparing names rather than a name against a dict. Assert that, plus the
        # all_exhausted() signal that is what actually means "no capacity left".
        sent = []
        import notify
        monkeypatch.setattr(notify, "send", lambda msg, *a, **kw: sent.append(msg))

        pool = account_pool.AccountPool()
        pool.accts = [{"name": "acct1", "type": "login"}]
        pool.state = {}
        pool._cfg_ts = time.time()
        pool._state_ts = time.time()

        result = pool.mark_exhausted(pool.accts[0])

        assert result == "acct1", f"Sole account should be handed back, got {result}"
        assert pool.all_exhausted() is True
        assert any("ALL accounts exhausted" in m for m in sent)

    def test_mark_exhausted_does_not_expose_config_in_state(self):
        """mark_exhausted() updates state without storing config_dir or secrets."""
        pool = account_pool.AccountPool()
        pool.accts = [
            {
                "name": "acct1",
                "type": "login",
                "config_dir": "~/.claude-secret",
                "api_key_env": "MY_SECRET_KEY",
            }
        ]
        pool.state = {}
        pool._cfg_ts = time.time()
        pool._state_ts = time.time()

        pool.mark_exhausted(pool.accts[0])

        acct_state = pool.state["acct1"]
        for key in ["config_dir", "api_key_env", "ANTHROPIC_API_KEY", "CLAUDE_CONFIG_DIR"]:
            assert key not in acct_state, f"Secret {key} should not be in state"
            assert key not in str(acct_state), f"Secret {key} should not appear in state string"


class TestMarkOkOutcomes:
    """Verify mark_ok() correctly clears exhaustion without exposing secrets."""

    def test_mark_ok_none_account_returns_none(self):
        """mark_ok(None) returns None and does not error."""
        pool = account_pool.AccountPool()
        pool.state = {}

        pool.mark_ok(None)  # Should not raise

    def test_mark_ok_missing_account_returns_none(self):
        """mark_ok() on unknown account returns None and does not error."""
        pool = account_pool.AccountPool()
        pool.state = {}

        acct = {"name": "unknown", "type": "login"}
        pool.mark_ok(acct)  # Should not raise

    def test_mark_ok_clears_cooldown_until(self):
        """mark_ok() removes cooldown_until from state."""
        pool = account_pool.AccountPool()
        pool.accts = [{"name": "acct1", "type": "login"}]
        pool.state = {"acct1": {"cooldown_until": time.time() + 3600}}
        pool._cfg_ts = time.time()
        pool._state_ts = time.time()
        acct = pool.accts[0]

        pool.mark_ok(acct)

        assert "cooldown_until" not in pool.state["acct1"]

    def test_mark_ok_clears_exh_hits(self):
        """mark_ok() removes exh_hits to reset backoff counter."""
        pool = account_pool.AccountPool()
        pool.accts = [{"name": "acct1", "type": "login"}]
        pool.state = {"acct1": {"exh_hits": 5}}
        pool._cfg_ts = time.time()
        pool._state_ts = time.time()
        acct = pool.accts[0]

        pool.mark_ok(acct)

        assert "exh_hits" not in pool.state["acct1"]

    def test_mark_ok_preserves_use_count(self):
        """mark_ok() does not reset use_count (used for round-robin)."""
        pool = account_pool.AccountPool()
        pool.accts = [{"name": "acct1", "type": "login"}]
        pool.state = {"acct1": {"use_count": 42}}
        pool._cfg_ts = time.time()
        pool._state_ts = time.time()
        acct = pool.accts[0]

        pool.mark_ok(acct)

        assert pool.state["acct1"]["use_count"] == 42


class TestCurrentAccountSelection:
    """Verify current() selects accounts correctly without exposing secrets in outcomes."""

    def test_current_returns_dict_with_name_and_type(self):
        """current() returns account dict, not a secret-bearing string."""
        pool = account_pool.AccountPool()
        pool.accts = [{"name": "acct1", "type": "login"}]
        pool.state = {}
        pool._cfg_ts = time.time()
        pool._state_ts = time.time()

        result = pool.current()

        assert isinstance(result, dict)
        assert "name" in result
        assert "type" in result

    def test_current_all_cooling_returns_soonest_recovery(self):
        """current() when all accounts cooling returns the one recovering soonest."""
        future_far = time.time() + 3600
        future_soon = time.time() + 60

        pool = account_pool.AccountPool()
        pool.accts = [
            {"name": "acct1", "type": "login"},
            {"name": "acct2", "type": "login"},
        ]
        pool.state = {
            "acct1": {"cooldown_until": future_far},
            "acct2": {"cooldown_until": future_soon},
        }
        pool._cfg_ts = time.time()
        pool._state_ts = time.time()

        result = pool.current()

        assert result["name"] == "acct2", "Should return account with soonest recovery"

    def test_current_returns_none_when_no_accounts(self):
        """current() returns None when account pool is empty."""
        pool = account_pool.AccountPool()
        pool.accts = []
        pool.state = {}
        pool._cfg_ts = time.time()
        pool._state_ts = time.time()

        result = pool.current()

        assert result is None

    def test_current_no_secrets_in_outcome(self):
        """current() outcome dict does not include secrets even if in config."""
        pool = account_pool.AccountPool()
        pool.accts = [
            {
                "name": "acct1",
                "type": "api",
                "api_key_env": "SECRET_KEY_VAR",
                "config_dir": "~/.hidden",
            }
        ]
        pool.state = {}
        pool._cfg_ts = time.time()
        pool._state_ts = time.time()

        result = pool.current()

        # API key and config dir should not be leaked in outcome
        assert "SECRET_KEY_VAR" not in str(result)
        assert "ANTHROPIC_API_KEY" not in str(result)


class TestClaudeExhaustedSignal:
    """Verify claude_exhausted() correctly signals exhaustion without exposing secrets."""

    def test_claude_exhausted_flag_file_missing_falls_through(self, monkeypatch, tmp_path):
        """claude_exhausted() falls back to the live pool check if the flag file is missing."""
        # Was `assert isinstance(result, bool)` -- true of every return value the function
        # could possibly produce, so the test could not fail. It was written that way
        # because the answer genuinely was not knowable: claude_exhausted() builds an
        # AccountPool from the module's CFG/STATE constants, which pointed at shared
        # on-disk state, so the result depended on whatever cooldowns happened to be
        # sitting on the machine. With the paths isolated there is no config, _load_cfg()
        # falls back to the implicit healthy "default" account (account_pool.py:171-172),
        # and the expected answer is exactly False.
        flag_path = tmp_path / "claude_exhausted.json"
        monkeypatch.setattr(account_pool, "EXHAUSTED_FLAG", str(flag_path))

        result = account_pool.claude_exhausted()

        assert result is False

    def test_claude_exhausted_flag_file_expired_falls_through(self, monkeypatch, tmp_path):
        """claude_exhausted() ignores an expired flag file."""
        # Was `assert isinstance(result, bool)`, a tautology (see
        # test_claude_exhausted_flag_file_missing_falls_through for why it was unavoidable
        # before the paths were isolated). An expired flag must NOT keep the fail-over
        # latched on, so with a healthy pool behind it the answer is False.
        flag_path = tmp_path / "claude_exhausted.json"
        flag_path.write_text(json.dumps({"until": time.time() - 100}))
        monkeypatch.setattr(account_pool, "EXHAUSTED_FLAG", str(flag_path))

        result = account_pool.claude_exhausted()

        assert result is False

    def test_claude_exhausted_flag_file_valid_returns_true(self, monkeypatch, tmp_path):
        """claude_exhausted() returns True when valid flag file exists."""
        flag_path = tmp_path / "claude_exhausted.json"
        flag_path.write_text(json.dumps({"until": time.time() + 3600}))
        monkeypatch.setattr(account_pool, "EXHAUSTED_FLAG", str(flag_path))

        result = account_pool.claude_exhausted()

        assert result is True

    def test_claude_exhausted_corrupt_flag_file_falls_through(self, monkeypatch, tmp_path):
        """claude_exhausted() ignores a corrupt/malformed flag file."""
        # Was `assert isinstance(result, bool)`, a tautology (see
        # test_claude_exhausted_flag_file_missing_falls_through). An unparseable flag must
        # fail soft to the live pool check rather than raise or latch on, so the answer for
        # a healthy pool is False.
        flag_path = tmp_path / "claude_exhausted.json"
        flag_path.write_text("{invalid json")
        monkeypatch.setattr(account_pool, "EXHAUSTED_FLAG", str(flag_path))

        result = account_pool.claude_exhausted()

        assert result is False

    def test_claude_exhausted_cache_behavior(self, monkeypatch, tmp_path):
        """claude_exhausted() caches result for ~15s to avoid repeated pool checks."""
        flag_path = tmp_path / "claude_exhausted.json"
        monkeypatch.setattr(account_pool, "EXHAUSTED_FLAG", str(flag_path))

        # Reset cache
        account_pool._EXH_CACHE["t"] = 0.0
        account_pool._EXH_CACHE["v"] = False

        result1 = account_pool.claude_exhausted()
        # Result should be cached
        initial_cache_time = account_pool._EXH_CACHE["t"]

        result2 = account_pool.claude_exhausted()
        # Cache time should not have advanced (still using cached value)
        assert account_pool._EXH_CACHE["t"] == initial_cache_time
        # ...and the cached value is what the second call returns. `result2` was computed
        # and then never asserted on, so the test proved the timestamp was reused without
        # ever checking the answer was.
        assert result2 == result1 == account_pool._EXH_CACHE["v"]

    def test_claude_exhausted_fail_soft_on_exception(self, monkeypatch):
        """claude_exhausted() returns False (fail-soft) on any exception."""
        def failing_pool():
            raise RuntimeError("Pool check failed")

        monkeypatch.setattr(account_pool, "AccountPool", failing_pool)

        result = account_pool.claude_exhausted()

        assert result is False, "Should fail-soft to False on exception"


class TestWriteExhaustedFlag:
    """Verify _write_exhausted_flag() handles secrets safely in persistence."""

    def test_write_exhausted_flag_only_stores_until_time(self, monkeypatch, tmp_path):
        """_write_exhausted_flag() persists only 'until' timestamp, no secrets."""
        # The pool used to hold a single api-type row. _write_exhausted_flag() goes through
        # all_exhausted() -> _usable_accounts(), which drops api rows while the billing
        # guard denies (account_pool.py:209-212) -- leaving zero usable accounts, so
        # all_exhausted() was False, no flag was written, and the test died on
        # FileNotFoundError before reaching its actual subject. The subject is "the flag
        # file carries a timestamp and nothing else", so give the pool a subscription row
        # that really is cooling (and keep secret-bearing fields on it, which is the part
        # the assertions below check for).
        flag_path = tmp_path / "claude_exhausted.json"
        monkeypatch.setattr(account_pool, "EXHAUSTED_FLAG", str(flag_path))

        pool = account_pool.AccountPool()
        pool.accts = [
            {
                "name": "acct1",
                "type": "login",
                "api_key_env": "SECRET_API_KEY",
                "config_dir": "~/.secret",
            }
        ]
        future = time.time() + 3600
        pool.state = {"acct1": {"cooldown_until": future}}
        pool._cfg_ts = time.time()
        pool._state_ts = time.time()

        pool._write_exhausted_flag()

        flag_data = json.loads(flag_path.read_text())
        assert "until" in flag_data
        assert isinstance(flag_data["until"], (int, float))
        # Verify no secret keys appear anywhere
        flag_str = json.dumps(flag_data)
        for secret in ["SECRET_API_KEY", "SECRET_KEY", ".secret", "api_key_env"]:
            assert secret not in flag_str, f"Secret {secret} should not be in flag file"

    def test_write_exhausted_flag_clears_when_healthy(self, monkeypatch, tmp_path):
        """_write_exhausted_flag() removes flag file when accounts recover."""
        flag_path = tmp_path / "claude_exhausted.json"
        flag_path.write_text('{"until": 99999}')
        monkeypatch.setattr(account_pool, "EXHAUSTED_FLAG", str(flag_path))

        pool = account_pool.AccountPool()
        pool.accts = [{"name": "acct1", "type": "login"}]
        pool.state = {}
        pool._cfg_ts = time.time()
        pool._state_ts = time.time()

        pool._write_exhausted_flag()

        assert not flag_path.exists(), "Flag should be removed when pool is healthy"

    def test_write_exhausted_flag_fail_soft_on_write_error(self, monkeypatch):
        """_write_exhausted_flag() does not raise on write permission error."""
        monkeypatch.setattr(account_pool, "EXHAUSTED_FLAG", "/invalid/path/flag.json")

        pool = account_pool.AccountPool()
        pool.accts = [
            {"name": "acct1", "type": "login"},
            {"name": "acct2", "type": "login"},
        ]
        future = time.time() + 3600
        pool.state = {
            "acct1": {"cooldown_until": future},
            "acct2": {"cooldown_until": future},
        }
        pool._cfg_ts = time.time()
        pool._state_ts = time.time()

        # Should not raise
        pool._write_exhausted_flag()


class TestRecordUseOutcomes:
    """Verify record_use() tracks usage without exposing account secrets."""

    def test_record_use_increments_count(self):
        """record_use() increments use_count for account selection balancing."""
        pool = account_pool.AccountPool()
        pool.accts = [{"name": "acct1", "type": "login"}]
        pool.state = {}
        pool._cfg_ts = time.time()
        pool._state_ts = time.time()
        acct = pool.accts[0]

        pool.record_use(acct)
        assert pool.state["acct1"]["use_count"] == 1

        pool.record_use(acct)
        assert pool.state["acct1"]["use_count"] == 2

    def test_record_use_none_account_does_not_error(self):
        """record_use(None) returns without error."""
        pool = account_pool.AccountPool()
        pool.state = {}

        pool.record_use(None)  # Should not raise


class TestThreadSafetySecrets:
    """Verify thread-safety of secret-bearing state operations."""

    def test_multiple_threads_reading_exhausted_cache(self):
        """claude_exhausted() cache lock prevents race conditions."""
        results = []

        def reader():
            for _ in range(50):
                results.append(account_pool.claude_exhausted())

        threads = [threading.Thread(target=reader) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 250
        assert all(isinstance(r, bool) for r in results)

    def test_multiple_threads_marking_exhausted(self):
        """mark_exhausted() concurrent calls don't corrupt state."""
        pool = account_pool.AccountPool()
        pool.accts = [
            {"name": "acct1", "type": "login"},
            {"name": "acct2", "type": "login"},
            {"name": "acct3", "type": "login"},
        ]
        pool.state = {}
        pool._cfg_ts = time.time()
        pool._state_ts = time.time()

        def exhaust_acct(acct):
            for _ in range(3):
                pool.mark_exhausted(acct)

        threads = [
            threading.Thread(target=exhaust_acct, args=(pool.accts[0],)),
            threading.Thread(target=exhaust_acct, args=(pool.accts[1],)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify state is coherent (no partial writes)
        for acct_name in ["acct1", "acct2"]:
            assert "cooldown_until" in pool.state[acct_name]
            assert isinstance(pool.state[acct_name]["exh_hits"], int)
            assert pool.state[acct_name]["exh_hits"] >= 3


class TestInvalidateMethod:
    """Verify invalidate() clears state safely and reloads config without exposing secrets."""

    def test_invalidate_resets_cooldowns(self):
        """invalidate(name) re-reads state from disk, then clears that account's cooldown."""
        # Was: set the cooldowns on pool.state only. invalidate() starts by replacing
        # self.state with _load_state() (account_pool.py:372), so the in-memory rows were
        # discarded before anything could be cleared; the assertions held only because
        # earlier tests in this file had persisted acct1/acct2 rows into the shared state
        # file that _load_state() read back. On a clean machine the reload returned {} and
        # the test raised KeyError. Persist the cooldowns to the (now temp) state file --
        # that is the state invalidate() operates on.
        future = time.time() + 3600
        with open(account_pool.STATE, "w") as f:
            json.dump({
                "acct1": {"cooldown_until": future, "exh_hits": 2},
                "acct2": {"cooldown_until": future, "exh_hits": 1},
            }, f)

        pool = account_pool.AccountPool()
        pool.accts = [
            {"name": "acct1", "type": "login"},
            {"name": "acct2", "type": "login"},
        ]
        pool._cfg_ts = time.time()
        pool._state_ts = time.time()

        pool.invalidate("acct1")

        assert "cooldown_until" not in pool.state["acct1"]
        assert "exh_hits" not in pool.state["acct1"]
        assert "cooldown_until" in pool.state["acct2"], "Other accounts unchanged"

    def test_invalidate_none_name_reloads_all(self):
        """invalidate() with no name reloads config and state."""
        pool = account_pool.AccountPool()
        pool.accts = [{"name": "acct1", "type": "login"}]
        pool.state = {"stale": True}
        pool._cfg_ts = 0.0
        pool._state_ts = 0.0

        pool.invalidate()

        # Timestamps should be updated
        assert pool._cfg_ts > 0
        assert pool._state_ts > 0


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
