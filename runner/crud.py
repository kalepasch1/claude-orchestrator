#!/usr/bin/env python3
"""
crud.py - Thin CRUD wrapper around db.py.

Every mutating operation returns ``(old_row_or_None, new_row_or_None)`` so
callers can diff, audit, or publish change events without a second round-trip.

Read-only helpers return rows directly (no tuple) for ergonomics.

All methods are fail-soft: on any db error they return the appropriate empty
value (None or empty list) rather than raising — consistent with the
orchestrator's fail-soft convention.
"""
import copy
import db


# ── helpers ────────────────────────────────────────────────────────────

def _first(rows):
    """Return the first row from a list, or None."""
    if rows and isinstance(rows, list):
        return rows[0]
    return None


def _match_params(match):
    """Convert a {col: val} dict to PostgREST eq. filter params."""
    return {k: f"eq.{v}" for k, v in match.items()}


# ── read ───────────────────────────────────────────────────────────────

def get(table, match, select="*"):
    """Fetch a single row matching *match* filters.  Returns row dict or None."""
    try:
        params = _match_params(match)
        params["select"] = select
        params["limit"] = "1"
        return _first(db.select(table, params))
    except Exception:
        return None


def list_rows(table, params=None):
    """Fetch multiple rows.  Returns list (possibly empty, never None)."""
    try:
        return db.select(table, params or {"select": "*"}) or []
    except Exception:
        return []


# ── create ─────────────────────────────────────────────────────────────

def create(table, row):
    """Insert *row* into *table*.

    Returns ``(None, new_row)`` on success, ``(None, None)`` on failure.
    """
    try:
        result = db.insert(table, row)
        return (None, _first(result))
    except Exception:
        return (None, None)


# ── update ─────────────────────────────────────────────────────────────

def update(table, match, patch):
    """Update rows matching *match* with *patch*.

    Fetches the row before patching so the caller gets a before/after pair.
    Returns ``(old_row, new_row)`` on success, ``(None, None)`` on failure.
    If the row doesn't exist, returns ``(None, None)``.
    """
    try:
        old = get(table, match)
        if old is None:
            return (None, None)
        result = db.update(table, match, patch)
        new = _first(result) if result else None
        # If update returned nothing (concurrent write swallowed), re-fetch
        if new is None:
            new = get(table, match)
        return (old, new)
    except Exception:
        return (None, None)


# ── upsert ─────────────────────────────────────────────────────────────

def upsert(table, row, match_keys=None):
    """Upsert *row*.  If *match_keys* are given, fetch the old row first.

    Returns ``(old_row_or_None, new_row)`` on success, ``(None, None)`` on failure.
    """
    try:
        old = None
        if match_keys:
            match = {k: row[k] for k in match_keys if k in row}
            if match:
                old = get(table, match)
        result = db.insert(table, row, upsert=True)
        new = _first(result)
        return (old, new)
    except Exception:
        return (None, None)


# ── delete ─────────────────────────────────────────────────────────────

def delete(table, match):
    """Delete rows matching *match*.  Fetches the row first for the return tuple.

    Returns ``(old_row, None)`` on success, ``(None, None)`` if not found or on error.
    """
    try:
        old = get(table, match)
        if old is None:
            return (None, None)
        params = _match_params(match)
        db._req("DELETE", f"/rest/v1/{table}", params=params)
        return (old, None)
    except Exception:
        return (None, None)
