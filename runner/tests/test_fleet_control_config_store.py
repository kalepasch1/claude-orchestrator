"""fleet_control writes config through the storage seam, not around it.

config_store.py was added as "the storage-neutral seam for fleet configuration" so a
later slice can swap the backing store without any caller learning about it. It shipped
with zero callers: fleet_control.update_fleet_config still read with db.select and wrote
with db.insert("fleet_config", ..., upsert=True), straight past the seam.

That is not only an unused abstraction. config_store routes writes through
fleet_config_dao._write, which is where fleet_config_guard is enforced fail-closed after
the 2026-08-02 incident that found four live credentials in plaintext in this table.
_safe_key() in fleet_control is a prefix allowlist, not that guard — so the direct write
skipped the credential check entirely.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fleet_control  # noqa: E402


class RecordingStore:
    """Minimal ConfigStore double. Records writes; never touches a database."""

    def __init__(self, existing=None):
        self.existing = dict(existing or {})
        self.writes = []

    def get_config(self, key):
        value = self.existing.get(key)
        return {"key": key, "value": value} if value is not None else None

    def update_config(self, key, value, note=None, updated_by=None):
        old = self.get_config(key)
        self.writes.append({"key": key, "value": value, "updated_by": updated_by})
        self.existing[key] = value
        return old, {"key": key, "value": value, "updated_by": updated_by}

    def bulk_insert(self, items):
        return [self.update_config(i["key"], i.get("value")) for i in items]


class GuardedStore(RecordingStore):
    """Store whose write path rejects, standing in for fleet_config_guard."""

    def update_config(self, key, value, note=None, updated_by=None):
        raise ValueError("[fleet-config-guard] refusing credential-shaped value")


@pytest.fixture(autouse=True)
def _reset_store():
    yield
    fleet_control.set_config_store(None)
    fleet_control.set_websocket_server(None)


class TestWritesGoThroughTheSeam:
    def test_the_store_receives_the_write(self):
        store = RecordingStore()
        fleet_control.set_config_store(store)
        fleet_control.update_fleet_config("ORCH_MAX_PARALLEL", 8)
        assert store.writes == [{"key": "ORCH_MAX_PARALLEL", "value": "8",
                                 "updated_by": fleet_control.HOST}]

    def test_the_value_is_stringified_as_before(self):
        store = RecordingStore()
        fleet_control.set_config_store(store)
        row = fleet_control.update_fleet_config("ORCH_X", 3)
        assert row["value"] == "3"

    def test_the_returned_row_still_carries_key_and_value(self):
        store = RecordingStore()
        fleet_control.set_config_store(store)
        row = fleet_control.update_fleet_config("ORCH_X", "on")
        assert row["key"] == "ORCH_X"
        assert row["value"] == "on"

    def test_a_guard_rejection_is_not_swallowed(self):
        """The whole point of routing through the seam: the guard must be able to stop it."""
        fleet_control.set_config_store(GuardedStore())
        with pytest.raises(ValueError):
            fleet_control.update_fleet_config("ORCH_SOMETHING", "secret-looking")

    def test_an_unsafe_key_is_still_refused_before_any_write(self):
        store = RecordingStore()
        fleet_control.set_config_store(store)
        with pytest.raises(ValueError):
            fleet_control.update_fleet_config("SUPABASE_SERVICE_KEY", "x")
        assert store.writes == []


class TestChangeEventPreserved:
    class WS:
        def __init__(self):
            self.events = []

        def publish_event(self, topic, payload):
            self.events.append((topic, payload))

    def test_a_changed_orch_key_still_publishes_old_and_new(self):
        store = RecordingStore({"ORCH_X": "1"})
        ws = self.WS()
        fleet_control.set_config_store(store)
        fleet_control.set_websocket_server(ws)
        fleet_control.update_fleet_config("ORCH_X", "2")
        assert len(ws.events) == 1
        topic, payload = ws.events[0]
        assert topic == "config/*"
        assert payload["old_value"] == "1"
        assert payload["new_value"] == "2"

    def test_an_unchanged_value_publishes_nothing(self):
        store = RecordingStore({"ORCH_X": "1"})
        ws = self.WS()
        fleet_control.set_config_store(store)
        fleet_control.set_websocket_server(ws)
        fleet_control.update_fleet_config("ORCH_X", "1")
        assert ws.events == []

    def test_a_non_orch_key_publishes_nothing(self):
        store = RecordingStore()
        ws = self.WS()
        fleet_control.set_config_store(store)
        fleet_control.set_websocket_server(ws)
        fleet_control.update_fleet_config("MAX_PARALLEL", "4")
        assert ws.events == []


class TestNoDependencyOnTheOldPath:
    def test_update_fleet_config_no_longer_writes_fleet_config_via_db(self):
        """`no dependencies on the old owner module` — asserted on the source."""
        src = open(fleet_control.__file__, encoding="utf-8").read()
        body = src.split("def update_fleet_config", 1)[1].split("\ndef ", 1)[0]
        # Comments describing the old path are the record of WHY it changed; only the
        # executable lines are the claim under test.
        code = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("#"))
        assert 'db.insert("fleet_config"' not in code
        assert 'db.select("fleet_config"' not in code

    def test_the_seam_is_injectable_and_resets(self):
        store = RecordingStore()
        fleet_control.set_config_store(store)
        assert fleet_control._config_store() is store
        fleet_control.set_config_store(None)
        assert fleet_control._config_store() is not store
