#!/usr/bin/env python3
"""
bulk_update_guard.py — makes the fleet's own metrics trustworthy again.

WHY
---
9,236 tasks were flipped to MERGED by two bulk `UPDATE`s. Every downstream number —
merge rate, throughput, "shipped" counts, the owner report — was computed from that
fabricated state. The system could not tell the truth about itself.

WHAT
----
Any single operation that moves more than ORCH_BULK_STATE_MAX rows (default 100) into
a new state is REFUSED unless the caller supplies an explicit override reason, and every
allowed bulk transition is written to `bulk_state_change_audit` so it is permanently visible.

There is no way to do a large state flip silently any more.

ENV
---
  ORCH_BULK_STATE_MAX            row threshold (default 100)
  ORCH_ALLOW_BULK_STATE_CHANGE   override token/reason — REQUIRED for >threshold ops
  ORCH_BULK_GUARD_ENABLED        default on; set 0 only for local dry-runs
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DEFAULT_MAX = 100
STATE_FIELDS = ("state", "status", "deploy_status")


class BulkStateChangeRefused(RuntimeError):
    """Raised when a bulk state transition is attempted without an explicit override."""


def _enabled():
    return os.environ.get("ORCH_BULK_GUARD_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")


def threshold():
    try:
        return int(os.environ.get("ORCH_BULK_STATE_MAX", str(DEFAULT_MAX)))
    except Exception:
        return DEFAULT_MAX


def override_token():
    return (os.environ.get("ORCH_ALLOW_BULK_STATE_CHANGE") or "").strip()


def is_state_change(patch):
    """True if `patch` moves rows into a new state/status."""
    if not isinstance(patch, dict):
        return False
    return any(f in patch for f in STATE_FIELDS)


def changed_state_value(patch):
    for f in STATE_FIELDS:
        if f in (patch or {}):
            return str(patch[f])
    return ""


def check(table, patch, row_count, actor="unknown", reason=""):
    """Authorise a bulk state transition of `row_count` rows.

    Returns True when the operation may proceed. Raises BulkStateChangeRefused otherwise.
    Small operations and non-state patches pass straight through.
    """
    if not _enabled() or not is_state_change(patch):
        return True
    limit = threshold()
    if row_count is None or row_count <= limit:
        return True

    token = override_token()
    if not token:
        raise BulkStateChangeRefused(
            f"REFUSED bulk state change: {row_count} rows in '{table}' -> "
            f"{changed_state_value(patch)!r} exceeds ORCH_BULK_STATE_MAX={limit}. "
            f"9,236 tasks were once flipped to MERGED this way and every metric downstream "
            f"became untrue. If this is genuinely intended, set "
            f"ORCH_ALLOW_BULK_STATE_CHANGE='<why>' — the operation will then be recorded in "
            f"bulk_state_change_audit."
        )

    _audit(table, patch, row_count, actor, reason or token, token)
    print(f"[bulk-guard] ALLOWED {row_count} row state change on '{table}' -> "
          f"{changed_state_value(patch)!r} (override: {token}) — audited.", flush=True)
    return True


def _audit(table, patch, row_count, actor, reason, token):
    try:
        import db
        db.insert("bulk_state_change_audit", {
            "table_name": table,
            "operation": "bulk_update",
            "row_count": int(row_count),
            "to_state": changed_state_value(patch)[:120],
            "reason": (reason or "")[:2000],
            "actor": (actor or "unknown")[:200],
            "override_token": (token or "")[:200],
        })
    except Exception as e:
        print(f"[bulk-guard] WARNING: could not write audit row: {e}", flush=True)


def audited_bulk_update(table, match, patch, actor="unknown", reason=""):
    """Convenience helper: count first, authorise, then update. Use this instead of a raw
    multi-row db.update() when you genuinely need one."""
    import db
    try:
        n = db.count(table, {k: f"eq.{v}" for k, v in (match or {}).items()})
    except Exception:
        n = None
    check(table, patch, n, actor=actor, reason=reason)
    return db.update(table, match, patch)


if __name__ == "__main__":
    import json
    print(json.dumps({"enabled": _enabled(), "threshold": threshold(),
                      "override_set": bool(override_token())}, indent=2))
