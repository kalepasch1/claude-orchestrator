"""Tests for account_pool.py rotation, stats, secrets and invalidation.

ISOLATION NOTE (why _isolated_account_pool_paths is autouse)
------------------------------------------------------------
account_pool resolves its file paths ONCE, at import time:

    HOME  = os.environ.get("CLAUDE_ORCH_HOME", ~/.claude-orchestrator)
    CFG / STATE / EXHAUSTED_FLAG = os.path.join(HOME, ...)

_pool() below builds its pool with __new__, so it never reads accounts.json -- but
mark_exhausted(), mark_ok(), record_use() and invalidate() all call _save() /
_write_exhausted_flag() / _load_state(), and those go straight to the module constants.
This file therefore wrote its cooldowns into shared on-disk state: <repo>/.runtime under
pytest (db.py sets CLAUDE_ORCH_HOME there at import), and the operator's real
~/.claude-orchestrator under any entry point that imports account_pool before db, or
with ORCH_CANONICAL_RUNTIME_HOME=false. A test run could park a real account on cooldown.

The pollution also decided results. test_invalidate_clears_specific_account_cooldown
passed only because an earlier test in this same file had persisted a "max-1" row into
that shared file: invalidate() re-reads state from disk, so with a clean machine the row
was absent and the assertion raised KeyError. Isolating the paths is what makes these
tests measure the code rather than the leftovers of the previous run.

The convention is the one used by runner/test_account_pool.py's _TempPaths: rebind the
MODULE CONSTANTS, and restore os.environ afterwards.
"""
import os
import shutil
import sys
import time
import json
import tempfile

import pytest

RUNNER = os.path.dirname(os.path.dirname(__file__))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import account_pool
import subscription_guard


@pytest.fixture(autouse=True)
def _isolated_account_pool_paths():
    """Point account_pool's import-time path constants at a fresh temp directory."""
    tmpdir = tempfile.mkdtemp(prefix="account-pool-rework-")
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

    try:
        yield tmpdir
    finally:
        (account_pool.HOME, account_pool.CFG, account_pool.STATE,
         account_pool.EXHAUSTED_FLAG) = orig
        account_pool._pool = orig_singleton
        os.environ.clear()
        os.environ.update(env_backup)
        shutil.rmtree(tmpdir, ignore_errors=True)


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

    def test_stats_all_exhausted(self, monkeypatch):
        """stats(): all_exhausted applies the billing guard, healthy_count does not."""
        # Was: `assert stats["healthy_count"] == 0` for a pool of two cooling subscription
        # rows AND two api rows with no cooldown at all. healthy_count is a per-row
        # observability field -- stats() walks self.accts and reports `now >= cooldown_until`
        # for each (account_pool.py:347-357) -- so the two api rows are genuinely healthy
        # rows and the count is 2, not 0. The old expectation asserted a number the code
        # never produces for this fixture, and it hid the distinction that actually matters:
        # all_exhausted() filters through _usable_accounts(), so an api row that the billing
        # guard disables cannot mask exhausted subscription capacity (account_pool.py:250-253,
        # and the _api_billing_allowed docstring). Both halves are now asserted explicitly.
        monkeypatch.setattr(account_pool, "_api_billing_allowed", lambda: False)

        pool = _pool()
        future = time.time() + 3600
        pool.state = {
            "max-1": {"cooldown_until": future},
            "max-2": {"cooldown_until": future},
        }

        stats = pool.stats()
        by_name = {s["name"]: s for s in stats["accounts"]}

        # Both subscription rows are cooling; the two api rows carry no cooldown.
        assert by_name["max-1"]["healthy"] is False
        assert by_name["max-2"]["healthy"] is False
        assert stats["healthy_count"] == 2

        # ...but with API billing disabled they provide no Claude capacity, so the pool
        # really is exhausted and the Codex fail-over signal must fire.
        assert stats["all_exhausted"] is True

    def test_stats_healthy_count_zero_when_every_row_cools(self):
        """healthy_count reaches 0 only when every configured row is cooling."""
        # New test: pins down the reading of healthy_count that the assertion above used
        # to claim, so the field still has direct coverage.
        pool = _pool()
        future = time.time() + 3600
        pool.state = {a["name"]: {"cooldown_until": future} for a in pool.accts}

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

    def test_mark_exhausted_returns_same_account_when_all_exhausted(self, monkeypatch):
        """With nothing healthy left, mark_exhausted() hands back the soonest-recovering
        account -- which is the one just exhausted, so the caller can see no rotation
        happened."""
        # Was: `assert nxt is None`. mark_exhausted() returns current()["name"], and
        # current() is documented to return "the one that frees up soonest" when everything
        # is cooling (account_pool.py:226-229); it returns None only for an EMPTY pool. So
        # None was never reachable here and the test asserted a contract the product does
        # not have. The real caller relies on the actual contract: runner.py:2001 does
        # `if nxt and nxt != (acct or {}).get("name"): attempt -= 1`, i.e. it detects
        # "no rotation" by comparing names, and account_pool.py:317-320 records that
        # comparing a name against a dict is exactly the bug that kept the "ALL accounts
        # exhausted" alert from ever firing. Assert that contract instead.
        sent = []
        import notify
        monkeypatch.setattr(notify, "send", lambda msg, *a, **kw: sent.append(msg))

        pool = _pool()
        future = time.time() + 3600
        pool.state = {
            "max-1": {"cooldown_until": future},
            "max-2": {"cooldown_until": future},
        }
        monkeypatch.setattr(account_pool, "_api_billing_allowed", lambda: False)
        acct = pool.accts[0]  # max-1

        nxt = pool.mark_exhausted(acct)

        assert pool.all_exhausted() is True
        assert nxt == acct["name"], "same name back == no rotation available"
        assert any("ALL accounts exhausted" in m for m in sent)

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
        # Was patching account_pool._api_billing_allowed, which env_for() never calls:
        # env_for consults subscription_guard.is_api_allowed() directly
        # (account_pool.py:277-283). The patch therefore did nothing, the real guard denied
        # (it requires explicit purchased-credit intent), and the key was never injected.
        # _api_billing_allowed is the seam for _usable_accounts()/all_exhausted(), not for
        # env_for. Patch the guard env_for actually reads.
        monkeypatch.setenv("TEST_API_KEY_1", "sk-test-secret-key-12345")
        monkeypatch.setattr(subscription_guard, "is_api_allowed", lambda: True)

        pool = _pool()
        acct = pool.accts[2]  # api-key-1

        env = pool.env_for(acct)

        assert "ANTHROPIC_API_KEY" in env
        assert env["ANTHROPIC_API_KEY"] == "sk-test-secret-key-12345"
        assert "ORCH_ANTHROPIC_API_ACCOUNT" in env

    def test_env_for_api_type_withholds_key_when_billing_disabled(self, monkeypatch):
        """env_for() withholds API key when billing guard disallows it."""
        # Was patching account_pool._api_billing_allowed (see the test above): env_for()
        # never reads it, so this test passed only because the ambient guard happened to
        # deny as well -- it would have kept passing had the guard check been deleted
        # outright. Patch the seam env_for really uses, and pin ORCH_ALLOW_API_BILLING off
        # so the env fallback in the except branch cannot re-open the key either.
        monkeypatch.setenv("TEST_API_KEY_1", "sk-test-secret-key-12345")
        monkeypatch.setenv("ORCH_ALLOW_API_BILLING", "false")
        monkeypatch.setattr(subscription_guard, "is_api_allowed", lambda: False)

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
        # Seam fix, same as the two tests above: env_for() reads
        # subscription_guard.is_api_allowed(), not account_pool._api_billing_allowed. With
        # the wrong seam the guard denied first and the test never reached the "key env var
        # is unset" path it is named for.
        monkeypatch.setattr(subscription_guard, "is_api_allowed", lambda: True)
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
        # Was: the replacement _load_cfg was declared with no parameters and patched onto
        # the CLASS, so `self._load_cfg()` passed self and raised
        # "mock_load_cfg() takes 0 positional arguments but 1 was given" -- the test failed
        # on its own stub before invalidate() was exercised at all. It also only counted
        # calls; assert that the reloaded config is the one the pool ends up holding, and
        # that state is re-read from disk too, which is what "forces reload" means.
        load_count = [0]

        def mock_load_cfg(self):
            load_count[0] += 1
            return [{"name": "loaded", "type": "login"}]

        monkeypatch.setattr(account_pool.AccountPool, "_load_cfg", mock_load_cfg)

        pool = _pool()
        pool.state = {"stale-row": {"use_count": 1}}
        with open(account_pool.STATE, "w") as f:
            json.dump({"loaded": {"use_count": 7}}, f)

        pool.invalidate()

        assert load_count[0] >= 1
        assert [a["name"] for a in pool.accts] == ["loaded"]
        assert pool.state == {"loaded": {"use_count": 7}}, "stale in-memory state dropped"

    def test_invalidate_clears_specific_account_cooldown(self):
        """invalidate(name) re-reads state from disk, then clears that account's cooldown."""
        # Was: set the cooldown on pool.state only, then call invalidate(name). invalidate()
        # starts by replacing self.state with _load_state() (account_pool.py:372), so the
        # in-memory row was discarded before anything could be cleared. The test passed
        # anyway -- but only because an earlier test in this file had persisted a "max-1"
        # row into the shared state file that _load_state() then read back. On a clean
        # machine the reload returned {} and the final assertion raised KeyError. Persist
        # the cooldown to the (now temp) state file, which is the state invalidate() acts on.
        pool = _pool()
        acct = pool.accts[0]
        with open(account_pool.STATE, "w") as f:
            json.dump({
                acct["name"]: {"cooldown_until": time.time() + 100, "exh_hits": 5,
                               "use_count": 4},
                "max-2": {"cooldown_until": time.time() + 100},
            }, f)

        pool.invalidate(acct["name"])

        assert "cooldown_until" not in pool.state[acct["name"]]
        assert "exh_hits" not in pool.state[acct["name"]]
        assert pool.state[acct["name"]]["use_count"] == 4, "usage history kept"
        assert "cooldown_until" in pool.state["max-2"], "other accounts untouched"
        # The cleared cooldown is persisted, not just held in memory.
        with open(account_pool.STATE) as f:
            assert "cooldown_until" not in json.load(f)[acct["name"]]


class TestModuleLevelSingleton:
    """Verify module-level functions delegate to singleton (per CLAUDE.md)."""

    def test_module_stats_function(self):
        """account_pool.stats() delegates to the singleton pool."""
        # Was wrapped in `try: ... except Exception: pass` "in case no config/state files
        # exist", which made every assertion inside optional -- the test could not fail.
        # The missing-config case is not an error: _load_cfg() falls back to the implicit
        # single "default" account (account_pool.py:171-172), so with the paths isolated
        # there is a well-defined answer to assert. Also check the delegation is real by
        # comparing against the singleton's own stats().
        stats = account_pool.stats()

        assert isinstance(stats, dict)
        assert stats["total_accounts"] >= 1
        assert stats["current"] == account_pool._get_pool().stats()["current"]

    def test_module_invalidate_function(self):
        """account_pool.invalidate() delegates to singleton."""
        # Should not raise
        account_pool.invalidate()
