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
