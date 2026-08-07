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
"""
from typing import Any, Dict, Iterable, List, Optional, Protocol, Tuple, runtime_checkable

import fleet_config_guard
import fleet_config_dao


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

    def __init__(self, dao=fleet_config_dao):
        self._dao = dao

    def get_config(self, key: str) -> Optional[Dict[str, Any]]:
        return self._dao.get(key)

    def get_all(self) -> List[Dict[str, Any]]:
        """Not part of the protocol; retained because callers of the DAO use it."""
        return self._dao.get_all()

    def update_config(self, key: str, value: Any, note: Optional[str] = None,
                      updated_by: Optional[str] = None) -> Tuple[Optional[dict], Optional[dict]]:
        return self._dao.set_value(key, value, note=note, updated_by=updated_by)

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


_default: Optional[FleetConfigStore] = None


def get_store() -> FleetConfigStore:
    """Process-wide default store."""
    global _default
    if _default is None:
        _default = FleetConfigStore()
    return _default


def invalidate() -> None:
    """Clear the cached default store. For testing."""
    global _default
    _default = None
