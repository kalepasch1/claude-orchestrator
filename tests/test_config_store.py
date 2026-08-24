"""ConfigStore seam: the adapter must forward faithfully and stay fail-closed.

The point of this slice is indirection with no behaviour change, so the tests
assert forwarding rather than storage semantics -- plus the one behaviour the
adapter does add: a bulk batch is guard-checked in full before any row is
written.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))
import config_store


class FakeDao:
    """Stands in for fleet_config_dao, recording every call."""

    def __init__(self):
        self.rows = {}
        self.calls = []

    def get(self, key):
        self.calls.append(("get", key))
        return self.rows.get(key)

    def get_all(self):
        self.calls.append(("get_all",))
        return list(self.rows.values())

    def set_value(self, key, value, note=None, updated_by=None):
        self.calls.append(("set_value", key, value, note, updated_by))
        old = self.rows.get(key)
        new = {"key": key, "value": str(value), "note": note, "updated_by": updated_by}
        self.rows[key] = new
        return old, new


@pytest.fixture()
def store():
    config_store.invalidate()
    yield config_store.FleetConfigStore(dao=FakeDao())
    config_store.invalidate()


def test_adapter_satisfies_the_protocol(store):
    assert isinstance(store, config_store.ConfigStore)


def test_get_config_forwards_and_returns_the_row(store):
    store.update_config("MERGE_TRAIN_ENABLED", "1")
    assert store.get_config("MERGE_TRAIN_ENABLED")["value"] == "1"
    assert ("get", "MERGE_TRAIN_ENABLED") in store._dao.calls


def test_get_config_returns_none_for_absent_key(store):
    assert store.get_config("NOPE") is None


def test_update_config_returns_old_and_new(store):
    old, new = store.update_config("BATCH_SIZE", 5)
    assert old is None and new["value"] == "5"
    old, new = store.update_config("BATCH_SIZE", 9, note="tuned")
    assert old["value"] == "5"
    assert new["value"] == "9" and new["note"] == "tuned"


def test_update_config_passes_through_note_and_updated_by(store):
    store.update_config("K", "v", note="n", updated_by="operator")
    assert store._dao.calls[-1] == ("set_value", "K", "v", "n", "operator")


def test_bulk_insert_writes_every_item_in_order(store):
    results = store.bulk_insert([
        {"key": "A", "value": 1},
        {"key": "B", "value": 2, "note": "second"},
    ])
    assert len(results) == 2
    assert store.get_config("A")["value"] == "1"
    assert store.get_config("B")["note"] == "second"


def test_bulk_insert_rejects_a_credential(store):
    with pytest.raises(ValueError, match="fleet-config-guard"):
        store.bulk_insert([{"key": "GITHUB_PAT", "value": "x"}])


def test_bulk_insert_writes_nothing_when_a_later_item_is_a_credential(store):
    """Fail-closed and all-or-nothing: row 1 must not land if row 2 is rejected."""
    with pytest.raises(ValueError):
        store.bulk_insert([
            {"key": "SAFE_SETTING", "value": "ok"},
            {"key": "VERCEL_TOKEN", "value": "x"},
        ])
    assert store.get_config("SAFE_SETTING") is None
    assert not [c for c in store._dao.calls if c[0] == "set_value"]


def test_bulk_insert_rejects_an_item_with_no_key(store):
    with pytest.raises(ValueError, match="missing 'key'"):
        store.bulk_insert([{"value": "orphan"}])


def test_bulk_insert_of_nothing_is_a_no_op(store):
    assert store.bulk_insert([]) == []


def test_get_store_is_a_singleton():
    config_store.invalidate()
    assert config_store.get_store() is config_store.get_store()
    config_store.invalidate()


# --- integration: the seam must not need the module it replaces ------------
#
# A seam that imports the old owner module at import time is not a seam: the
# swap it exists to enable is impossible until fleet_config_dao is importable.
# These tests pin the decoupling and the one wired call site.

def test_importing_config_store_does_not_import_the_old_owner_module():
    import subprocess
    runner_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
    code = (
        "import sys; sys.path.insert(0, %r);"
        "import config_store;"
        "print('fleet_config_dao' in sys.modules)" % runner_dir
    )
    out = subprocess.run([sys.executable, "-c", code],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False", (
        "config_store pulled in fleet_config_dao at import time: " + out.stdout)


def test_an_injected_backend_is_used_without_the_old_module_being_touched():
    dao = FakeDao()
    store = config_store.FleetConfigStore(dao=dao)

    store.update_config("ORCH_X", "1")

    assert dao.calls == [("set_value", "ORCH_X", "1", None, None)]


def test_set_store_installs_the_store_every_caller_receives():
    config_store.invalidate()
    injected = config_store.FleetConfigStore(dao=FakeDao())
    try:
        config_store.set_store(injected)
        assert config_store.get_store() is injected
    finally:
        config_store.invalidate()


def test_set_store_refuses_something_that_is_not_a_config_store():
    config_store.invalidate()
    try:
        with pytest.raises(TypeError):
            config_store.set_store(object())
    finally:
        config_store.invalidate()


def test_set_store_none_restores_the_default():
    config_store.invalidate()
    try:
        config_store.set_store(config_store.FleetConfigStore(dao=FakeDao()))
        config_store.set_store(None)
        assert isinstance(config_store.get_store(), config_store.FleetConfigStore)
    finally:
        config_store.invalidate()


def test_fleet_control_writes_config_through_the_seam():
    """The wired call site: update_fleet_config must go through the store."""
    import fleet_control

    dao = FakeDao()
    config_store.invalidate()
    try:
        config_store.set_store(config_store.FleetConfigStore(dao=dao))
        row = fleet_control.update_fleet_config("ORCH_AUTO_PULL", "true")
    finally:
        config_store.invalidate()

    assert [c[0] for c in dao.calls] == ["set_value"], (
        "the separate 'what was it before?' read should be gone — the store "
        "returns (old, new) from the one write")
    assert dao.calls[0][1:3] == ("ORCH_AUTO_PULL", "true")
    assert row["key"] == "ORCH_AUTO_PULL" and row["value"] == "true"


def test_fleet_control_still_refuses_an_unsafe_key_before_reaching_the_store():
    import fleet_control

    dao = FakeDao()
    config_store.invalidate()
    try:
        config_store.set_store(config_store.FleetConfigStore(dao=dao))
        with pytest.raises(ValueError):
            fleet_control.update_fleet_config("OPENAI_API_KEY", "sk-abc")
    finally:
        config_store.invalidate()

    assert dao.calls == [], "a refused key must never reach the store"
