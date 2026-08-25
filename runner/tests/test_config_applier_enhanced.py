#!/usr/bin/env python3
"""
Enhanced testing suite for config_applier — configuration management.

Covers: safe-key edge cases, apply_config outcomes (applied, rejected,
rolled_back, error), state persistence, canary window, rollback heuristics,
and the periodic run() entry point.
"""
import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")

import pytest

import config_applier


@pytest.fixture(autouse=True)
def _fleet_config_stays_out_of_this(monkeypatch):
    """apply_config PERSISTS. Not into the fleet's real configuration table.

    config_applier.apply_config() ends with

        db.insert("fleet_config", {"key": key, "value": str(value), ...},
                  upsert=True)

    and nothing in this file mocked db. These tests were writing their fixtures
    into the live control plane, and four of them are still there:

        ORCH_TEST_ENHANCED_SUITE_TEMP = 42        (2026-07-25, from this file)
        ORCH_TEST_INTEGRATION         = 100
        ORCH_CANARY_TEST              = test123
        ORCH_OLD_VAL_TEST             = modified

    None of the four is read by any code in the repository. They are test
    fixtures that escaped into production configuration and stayed there for a
    month.

    The failures that led here were the second-order effect: with the suite's
    hermetic guard refusing the socket, the write failed, apply_config correctly
    reported "rolled_back", and two tests asserting "applied" went red. The
    product was right both times -- the test was asking a question it had no
    business asking of the real database.

    An in-memory fleet_config keeps the persistence path exercised end to end,
    so the assertions still mean something, without leaving anything behind.
    """
    written = {}

    def fake_insert(table, row, **kw):
        # NO `assert table == "fleet_config"` here. policy_compiler.
        # authorize_config() -- which apply_config calls BEFORE persisting --
        # inserts into its own policy table, so the assertion raised, was caught
        # by config_applier's `except Exception` around the authorize call, and
        # came back as {"outcome": "rejected", "reason": "policy_compiler:..."}.
        # A mock that fails the code under test is indistinguishable from the
        # code under test failing.
        if table == "fleet_config" and isinstance(row, dict) and "key" in row:
            written[row["key"]] = row.get("value")
        return [row]

    # WRITES ONLY. Stubbing select() as well made apply_config return
    # "rejected" instead: policy_compiler.authorize_config() reads through db,
    # and an empty answer fails authorization before the persistence path is
    # reached -- so the test would have "passed" over a code path it never ran.
    # Reads stay as they are; the suite's hermetic guard already keeps them off
    # the network, and every one of them is fail-soft.
    #
    # config_applier does `import db` INSIDE its functions, so there is no
    # config_applier.db attribute to patch; the real module is what the lazy
    # import will find.
    import db as real_db
    monkeypatch.setattr(real_db, "insert", fake_insert)
    monkeypatch.setattr(real_db, "update", lambda *a, **k: None)
    monkeypatch.setattr(real_db, "delete", lambda *a, **k: 0, raising=False)
    yield written


# ---------------------------------------------------------------------------
# _is_safe_key edge cases
# ---------------------------------------------------------------------------

def test_safe_key_case_insensitive_deny():
    """Deny markers are case-insensitive."""
    assert config_applier._is_safe_key("ORCH_my_secret") is False
    assert config_applier._is_safe_key("ORCH_Token_Refresh") is False
    assert config_applier._is_safe_key("DEPLOY_PASSWORD_HASH") is False


def test_safe_key_all_prefixes():
    """Every safe prefix is accepted when no deny marker is present."""
    prefixes = [
        "ORCH_X", "MAX_PARALLEL_5", "PER_TASK_GB_2", "RAM_FLOOR_GB_4",
        "RAM_LIMIT", "RELEASE_TAG", "QUEUE_DEPTH", "CONT_WINDOW",
        "JANITOR_INTERVAL", "REMEDIATION_MAX", "DEFAULT_TEST_CMD_A",
        "TASK_TIMEOUT_S", "ENABLE_CANARY", "SESSION_TTL",
        "ACCOUNT_COOLDOWN_S", "MERGE_BATCH", "DEPLOY_STRATEGY",
        "INTEGRATE_FLAG", "COST_LIMIT",
    ]
    for p in prefixes:
        assert config_applier._is_safe_key(p) is True, f"Expected safe: {p}"


def test_safe_key_deny_overrides_prefix():
    """A key with both a safe prefix and a deny marker is rejected."""
    assert config_applier._is_safe_key("ORCH_API_KEY") is False
    assert config_applier._is_safe_key("DEPLOY_CREDENTIAL_STORE") is False
    assert config_applier._is_safe_key("MERGE_SECRET_FLAG") is False


def test_safe_key_numeric_only():
    """Pure numeric string is not safe."""
    assert config_applier._is_safe_key("12345") is False


def test_safe_key_whitespace():
    """Whitespace-only is not safe."""
    assert config_applier._is_safe_key("   ") is False


# ---------------------------------------------------------------------------
# _load_state / _save_state round-trip
# ---------------------------------------------------------------------------

def test_state_round_trip():
    """State serialises and deserialises without loss."""
    orig = config_applier.STATE_FILE
    try:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            config_applier.STATE_FILE = f.name
        state = {"applied": {"ORCH_A": {"value": "1"}}, "rollbacks": [{"key": "ORCH_B"}]}
        config_applier._save_state(state)
        loaded = config_applier._load_state()
        assert loaded["applied"]["ORCH_A"]["value"] == "1"
        assert len(loaded["rollbacks"]) == 1
    finally:
        config_applier.STATE_FILE = orig


def test_load_state_corrupt_file():
    """Corrupt state file returns safe default."""
    orig = config_applier.STATE_FILE
    try:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            f.write("{bad json!!")
            config_applier.STATE_FILE = f.name
        state = config_applier._load_state()
        assert isinstance(state, dict)
        assert "applied" in state or state == {"applied": {}, "rollbacks": []}
    finally:
        config_applier.STATE_FILE = orig


# ---------------------------------------------------------------------------
# apply_config outcomes
# ---------------------------------------------------------------------------

def test_apply_config_rejects_unsafe_key():
    """Unsafe key is rejected without side effects."""
    result = config_applier.apply_config("MY_SECRET", "val123")
    assert result["outcome"] == "rejected"
    assert "unsafe" in result.get("reason", "")


def test_apply_config_applies_safe_key():
    """Safe key with canary=False is applied immediately."""
    key = "ORCH_TEST_ENHANCED_SUITE_TEMP"
    old = os.environ.get(key)
    try:
        result = config_applier.apply_config(key, "42", canary=False)
        assert result["outcome"] == "applied"
        assert os.environ.get(key) == "42"
    finally:
        if old is not None:
            os.environ[key] = old
        else:
            os.environ.pop(key, None)


def test_apply_config_restores_old_value_on_reject():
    """Rejecting an unsafe key does not change env."""
    key = "ORCH_PASSWORD_FIELD"
    os.environ.pop(key, None)
    config_applier.apply_config(key, "sneaky")
    assert os.environ.get(key) is None


def test_apply_config_value_coerced_to_string():
    """Numeric values are stored as strings in env."""
    key = "ORCH_TEST_NUM_COERCE"
    old = os.environ.get(key)
    try:
        result = config_applier.apply_config(key, 99, canary=False)
        assert result["outcome"] == "applied"
        assert os.environ.get(key) == "99"
    finally:
        if old is not None:
            os.environ[key] = old
        else:
            os.environ.pop(key, None)


# ---------------------------------------------------------------------------
# run() periodic entry
# ---------------------------------------------------------------------------

def test_run_returns_dict():
    """run() returns a dict even when db is unavailable."""
    result = config_applier.run()
    assert isinstance(result, dict)
    assert "checked" in result


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
                passed += 1
            except Exception as e:
                print(f"  FAIL  {name}: {e}")
                failed += 1
    print(f"\nconfig_applier enhanced tests: {passed} passed, {failed} failed")
