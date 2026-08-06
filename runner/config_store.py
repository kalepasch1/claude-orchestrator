#!/usr/bin/env python3
"""config_store.py - the storage-neutral seam for fleet configuration.

Slice 3 of the high-performance-database work. Config reads and writes are
currently bound directly to `fleet_config_dao`, which is bound to `db.py`,
which is bound to PostgREST. Swapping the backing store means touching every
call site.

This module introduces the seam and nothing else: a `ConfigStore` protocol
naming the three operations callers actually perform, and `FleetConfigStore`,
a thin adapter over the existing `fleet_config_dao`. No new database logic,
no new queries, no behaviour change - a later slice can supply a second
implementation without any caller learning about it.

SECURITY: writes route through fleet_config_dao -> db.upsert, which is where
fleet_config_guard is enforced fail-closed (incident 2026-08-02: four live
credentials found in plaintext in this table). `bulk_insert` additionally
validates the whole batch *before* writing anything, so a credential in the
last row cannot be preceded by seven partial writes.

DECOUPLING: this module must not *require* the old owner module. `import
config_store` no longer imports `fleet_config_dao` — the default backend is
resolved lazily, on the first call that actually needs it, and `set_store()`
lets a caller install a different `ConfigStore` before then. A future backend
can therefore be wired in without `fleet_config_dao` being importable at all,
which is the whole point of having a seam.
"""
from typing import Any, Dict, Iterable, List, Optional, Protocol, Tuple, runtime_checkable

import fleet_config_guard


@runtime_checkable
class ConfigStore(Protocol):
    """Operations any configuration backend must provide."""

    def get_config(self, key: str) -> Optional[Dict[str, Any]]:
        """Return the row for `key`, or None if absent or unreadable."""
        ...

    def update_config(self, key: str, value: Any, note: Optional[str] = None,
                      updated_by: Optional[str] = None) -> Tuple[Optional[dict], Optional[dict]]:
        """Upsert `key`. Returns (old_row_or_None, new_row_or_None)."""
        ...

    def bulk_insert(self, items: Iterable[Dict[str, Any]]) -> List[Tuple[Optional[dict], Optional[dict]]]:
        """Upsert many rows. Returns one (old, new) pair per item, in order."""
        ...


class FleetConfigStore:
    """ConfigStore backed by the fleet_config table via fleet_config_dao.

    Deliberately thin: every method forwards to the DAO. The value is the
    indirection, not the logic.
    """

    def __init__(self, dao=None):
        self._dao = dao

    @property
    def _backend(self):
        # Resolved on first use, not at import: config_store must be importable
        # (and replaceable via set_store) without the old owner module present.
        if self._dao is None:
            import fleet_config_dao
            self._dao = fleet_config_dao
        return self._dao

    def get_config(self, key: str) -> Optional[Dict[str, Any]]:
        return self._backend.get(key)

    def get_all(self) -> List[Dict[str, Any]]:
        """Not part of the protocol; retained because callers of the DAO use it."""
        return self._backend.get_all()

    def update_config(self, key: str, value: Any, note: Optional[str] = None,
                      updated_by: Optional[str] = None) -> Tuple[Optional[dict], Optional[dict]]:
        return self._backend.set_value(key, value, note=note, updated_by=updated_by)

    def bulk_insert(self, items: Iterable[Dict[str, Any]]) -> List[Tuple[Optional[dict], Optional[dict]]]:
        """Upsert many {key, value, note?, updated_by?} rows.

        The batch is validated against fleet_config_guard in full before the
        first write. Partially applying a batch and then rejecting row N would
        leave config in a state no caller asked for, and the offending value
        would already have been echoed into the write path's logs.
        """
        batch = list(items)
        for item in batch:
            if "key" not in item:
                raise ValueError("[config-store] bulk_insert item is missing 'key'")
            fleet_config_guard.assert_writable(item["key"], item.get("value"))

        results = []
        for item in batch:
            results.append(self.update_config(
                item["key"], item.get("value"),
                note=item.get("note"), updated_by=item.get("updated_by")))
        return results


_default = None


def get_store():
    """Process-wide store. FleetConfigStore unless set_store() said otherwise."""
    global _default
    if _default is None:
        _default = FleetConfigStore()
    return _default


def set_store(store) -> None:
    """Install the store every caller of get_store() will receive.

    This is how a later slice swaps the backend: build the new implementation,
    call set_store() once at startup, and no call site changes. Passing None
    restores the default.
    """
    global _default
    if store is not None and not isinstance(store, ConfigStore):
        raise TypeError("[config-store] set_store expects a ConfigStore, got %r"
                        % type(store).__name__)
    _default = store


def invalidate() -> None:
    """Clear the cached default store. For testing."""
    global _default
    _default = None
