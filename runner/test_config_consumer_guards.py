#!/usr/bin/env python3
"""Tests for orch-config-consumption — the direct-read fallback must honour the gateway.

`config_consumer.load_config()` falls back to a direct `fleet_config` read when the
fleet_control gateway is absent or returns nothing. `fleet_control.load_config()` never
applies a row that `_classify_key` rejects (credential-marker key, unsafe key, key with an
open approval card, key pinned to the host's local .env), but the fallback here read the
same table with none of those checks — so a declined key was still handed to callers, and
then cached for the TTL.

These tests pin the guard: a declined row is dropped and the caller falls back to env,
an allowed row is still consumed, and an unreachable classifier fails CLOSED.
"""

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")

import config_consumer


class _StubFleetControl:
    """Only the surface `_consumable_from_db` uses, with fleet_control's real semantics."""

    def __init__(self, pins=None):
        self._pins = pins or set()

    def _env_pins(self):
        return self._pins

    def _classify_key(self, key, value, blocked, pins):
        if not key or value is None:
            return "empty"
        ku = key.upper()
        if any(m in ku for m in ("TOKEN", "SECRET", "KEY", "PASSWORD", "PAT")):
            return "credential"
        if not ku.startswith("ORCH_"):
            return "unsafe-key"
        if key in blocked:
            return "approval-blocked"
        if ku in pins:
            return "pinned"
        return None

    # the gateway read must miss so load_config reaches the direct-read fallback
    def get_fleet_config(self, key, default=""):
        return default


class _Harness:
    """Patch the module seams `load_config` uses, and restore them afterwards."""

    def __init__(self, db_value, fleet=None, blocked=None):
        self.db_value = db_value
        self.fleet = fleet if fleet is not None else _StubFleetControl()
        self.blocked = blocked or set()
        self._saved_fleet = None
        self._saved_db = None
        self._saved_approval = None

    def __enter__(self):
        self._saved_fleet = config_consumer.fleet_control
        config_consumer.fleet_control = self.fleet

        db_value = self.db_value
        db_stub = types.ModuleType("db")
        db_stub.select = lambda table, params=None: (
            [{"value": db_value}] if db_value is not None else []
        )
        self._saved_db = sys.modules.get("db")
        sys.modules["db"] = db_stub

        blocked = set(self.blocked)
        approval_stub = types.ModuleType("config_approval")
        approval_stub.blocked_keys = lambda: set(blocked)
        self._saved_approval = sys.modules.get("config_approval")
        sys.modules["config_approval"] = approval_stub

        config_consumer.invalidate_cache()
        return self

    def __exit__(self, *exc):
        config_consumer.fleet_control = self._saved_fleet
        for name, saved in (("db", self._saved_db), ("config_approval", self._saved_approval)):
            if saved is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = saved
        config_consumer.invalidate_cache()
        return False


def _clear_env(*names):
    for n in names:
        os.environ.pop(n, None)


class TestDirectReadHonoursGateway:
    """The fallback consumes only what fleet_control.load_config() would have applied."""

    def test_allowed_key_is_still_consumed(self):
        """Behaviour preserved: an ordinary safe key still comes from the DB."""
        _clear_env("ORCH_MAX_PARALLEL")
        with _Harness(db_value="12"):
            assert config_consumer.load_config("ORCH_MAX_PARALLEL", "4") == "12"

    def test_credential_marker_key_is_refused(self):
        """The 2026-08-02 incident class: a token-shaped key never reaches a caller."""
        _clear_env("ORCH_GITHUB_PAT")
        with _Harness(db_value="a-live-credential"):
            assert config_consumer.load_config("ORCH_GITHUB_PAT", "unset") == "unset"

    def test_unsafe_key_falls_back_to_env(self):
        """A key outside the safe prefix set is dropped; env still answers."""
        os.environ["ORCH_HOME_DIR"] = "/local/value"
        try:
            with _Harness(db_value="/fleet/value"):
                assert config_consumer.load_config("HOME_DIR", "default") == "/local/value"
        finally:
            _clear_env("ORCH_HOME_DIR")

    def test_approval_blocked_key_is_refused(self):
        """An open approval card blocks the value here exactly as it does in the gateway."""
        _clear_env("ORCH_MAX_PARALLEL")
        with _Harness(db_value="0", blocked={"ORCH_MAX_PARALLEL"}):
            assert config_consumer.load_config("ORCH_MAX_PARALLEL", "4") == "4"

    def test_pinned_key_never_takes_the_fleet_value(self):
        """A host that pinned the key wins over fleet_config, as documented precedence.

        Asserted on the fleet value specifically, not on the env fallback: `get()` reads
        env as ORCH_{key}, so an already-prefixed key resolves to its default here. The
        contract under test is that the pinned row is refused, not which default answers.
        """
        _clear_env("ORCH_RAM_FLOOR_GB")
        fleet = _StubFleetControl(pins={"ORCH_RAM_FLOOR_GB"})
        with _Harness(db_value="2", fleet=fleet):
            assert config_consumer._consumable_from_db("ORCH_RAM_FLOOR_GB", "2") is False
            assert config_consumer.load_config("ORCH_RAM_FLOOR_GB", "8") == "8"

    def test_refused_value_is_not_served_later(self):
        """A refused row must not reappear from cache on a second read."""
        _clear_env("ORCH_API_SECRET")
        with _Harness(db_value="a-secret-value"):
            first = config_consumer.load_config("ORCH_API_SECRET", "unset")
            second = config_consumer.load_config("ORCH_API_SECRET", "unset")
            assert first == "unset" and second == "unset"


class TestFailClosed:
    """When the classifier is unreachable the raw row is not consumable."""

    def test_missing_fleet_control_refuses_db_value(self):
        _clear_env("ORCH_MAX_PARALLEL")
        with _Harness(db_value="99"):
            config_consumer.fleet_control = None
            assert config_consumer.load_config("ORCH_MAX_PARALLEL", "4") == "4"

    def test_raising_classifier_refuses_db_value(self):
        class _Exploding(_StubFleetControl):
            def _classify_key(self, *a, **k):
                raise RuntimeError("classifier down")

        _clear_env("ORCH_MAX_PARALLEL")
        with _Harness(db_value="99", fleet=_Exploding()):
            assert config_consumer.load_config("ORCH_MAX_PARALLEL", "4") == "4"

    def test_predicate_never_raises_on_garbage(self):
        """`_consumable_from_db` is on the fail-soft config path; it must not raise."""
        assert config_consumer._consumable_from_db(None, None) is False
        assert config_consumer._consumable_from_db("", "") is False


def run_all_tests():
    fail_count, errors = 0, []
    for cls in (TestDirectReadHonoursGateway, TestFailClosed):
        instance = cls()
        for name in sorted(n for n in dir(instance) if n.startswith("test_")):
            try:
                getattr(instance, name)()
                print(f"  PASS {cls.__name__}.{name}")
            except Exception as exc:  # noqa: BLE001 - report, do not abort the suite
                fail_count += 1
                errors.append(f"{cls.__name__}.{name}: {exc}")
                print(f"  FAIL {cls.__name__}.{name}: {exc}")
    print(f"Failures: {fail_count}")
    for error in errors:
        print(f"  - {error}")
    return fail_count == 0


if __name__ == "__main__":
    sys.exit(0 if run_all_tests() else 1)
