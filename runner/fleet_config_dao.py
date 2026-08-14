#!/usr/bin/env python3
"""
fleet_config_dao.py - data access for the fleet_config table.

Thin CRUD wrapper around db.py. Does not apply config to env — use
fleet_control.load_config() for that.

An optional change hook (_change_hook) fires immediately after a successful
write so callers can get sub-millisecond notification (before the next watcher
poll cycle). The watcher is still the authoritative source for out-of-band DB
changes; the hook is purely a fast-path optimisation.

ROUND-TRIP BUDGET (slice 3, high-performance config store). Every function here
costs network round trips, and the fleet writes config far more often than it
reads it. Two costs were being paid for nothing:

  1. set_value() issued get -> upsert -> get, three round trips per write, even
     though db.insert() already sends `Prefer: return=representation` and so
     hands back the row it just wrote. The trailing read is now only performed
     when the write response is unusable, taking the common path to two.
  2. Callers needing N keys called get() N times. get_many() fetches them in a
     single `key=in.(...)` request, and set_many() uses it to capture all the
     `old` rows for a batch in one request instead of N.

Behaviour is unchanged: same return shapes, same fail-soft `None`/`[]` on
error, same hook semantics. Only the number of requests differs.
"""
import os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

_change_hook = None   # callable(old, new, change_type) or None


def _first_row(result):
    """Normalise a PostgREST write response to a single row dict, or None.

    db.insert returns whatever `return=representation` produced: a list of rows
    for a normal write, a bare dict from some paths, or None when the write was
    swallowed (409 dedup). Anything that is not a usable row yields None so the
    caller falls back to an explicit read rather than inventing state.
    """
    if isinstance(result, dict):
        return result or None
    if isinstance(result, list):
        for item in result:
            if isinstance(item, dict) and item:
                return item
    return None


def set_change_hook(hook):
    """Register a callback invoked immediately after every successful write."""
    global _change_hook
    _change_hook = hook


def get_all():
    """Return all fleet_config rows as a list of dicts."""
    try:
        return db.select("fleet_config", {"select": "*"}) or []
    except Exception:
        return []


def get(key):
    """Return the fleet_config row for key, or None."""
    try:
        rows = db.select("fleet_config",
                         {"select": "*", "key": f"eq.{key}", "limit": "1"}) or []
        return rows[0] if rows else None
    except Exception:
        return None


def get_many(keys):
    """Return {key: row} for the given keys, in ONE request.

    Keys that do not exist are simply absent from the result — callers use
    ``.get(key)`` and see the same ``None`` that ``get()`` would have returned.
    Fail-soft: an empty dict on any error, matching ``get()``'s contract.
    """
    wanted = [str(k) for k in (keys or []) if k is not None]
    if not wanted:
        return {}
    # PostgREST `in.(...)` needs each value quoted; a key containing a quote or
    # comma would otherwise split the filter into a different query.
    quoted = ",".join('"%s"' % k.replace('"', '""') for k in dict.fromkeys(wanted))
    try:
        rows = db.select("fleet_config",
                         {"select": "*", "key": f"in.({quoted})"}) or []
    except Exception:
        return {}
    return {row["key"]: row for row in rows if isinstance(row, dict) and "key" in row}


def set_value(key, value, note=None, updated_by=None):
    """Upsert key=value in fleet_config.

    Returns (old_row_or_None, new_row_or_None). Captures old value before the
    write so change-stream consumers get accurate before/after context.
    Fires _change_hook immediately after a successful write.
    """
    return _write(key, value, get(key), note=note, updated_by=updated_by)


def set_many(items):
    """Upsert many {key, value, note?, updated_by?} rows.

    Returns one (old_row_or_None, new_row_or_None) pair per item, in input
    order — exactly what N calls to set_value() would return. The saving is on
    reads: all the `old` rows are captured in a single get_many() rather than
    one get() per item.

    Writes are still issued one at a time so each row keeps its own guard
    check, its own failure isolation, and its own change-hook firing.
    """
    batch = [dict(item) for item in (items or [])]
    for item in batch:
        if "key" not in item:
            raise ValueError("[fleet-config-dao] set_many item is missing 'key'")
    olds = get_many([item["key"] for item in batch])
    return [
        _write(item["key"], item.get("value"), olds.get(item["key"]),
               note=item.get("note"), updated_by=item.get("updated_by"))
        for item in batch
    ]


def _write(key, value, old, note=None, updated_by=None):
    """Upsert one row given its already-fetched `old`. Returns (old, new)."""
    row = {
        "key": key,
        "value": str(value),
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    if note is not None:
        row["note"] = note
    if updated_by is not None:
        row["updated_by"] = updated_by
    try:
        written = db.upsert("fleet_config", row)
    except Exception:
        return old, None
    # db.insert asks for return=representation, so the written row normally
    # comes back here — re-reading it would be a second round trip for a value
    # we already hold. Only fall back to a read when the response is unusable
    # (409 dedup path returns None), which is also the case where the row on
    # disk may differ from what we sent.
    new = _first_row(written) or get(key)
    hook = _change_hook
    if hook and new is not None:
        change_type = "created" if old is None else "updated"
        try:
            hook(old=old, new=new, change_type=change_type)
        except Exception:
            pass
    return old, new
