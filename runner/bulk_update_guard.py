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
import json
import os
import sys
import time

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
    # FAIL-OPEN HOLE CLOSED 2026-08-04 (adversarial sweep): `row_count is None` used to return
    # True. db.update() computes that count with `count(table, params)` inside a bare
    # `except: _n = None`, so ANY failure of the count query — a network blip, a PostgREST
    # 5xx, a malformed filter — turned an unbounded mass state flip into an unconditional
    # allow. The one moment the guard most needs to hold is the moment it cannot see how many
    # rows it is about to rewrite. Unknown count is now treated as unbounded and refused
    # unless the operator has explicitly opted in.
    if row_count is None:
        token = override_token()
        if not token:
            raise BulkStateChangeRefused(
                f"REFUSED bulk state change on '{table}' -> {changed_state_value(patch)!r}: "
                f"the number of affected rows could NOT be determined, so this may be "
                f"unbounded. 9,236 tasks were once flipped to MERGED by exactly this kind of "
                f"unbounded write. Match on an id, or set ORCH_ALLOW_BULK_STATE_CHANGE='<why>' "
                f"if the transition is genuinely intended.")
        _audit(table, patch, None, actor, reason or token, token)
        return True
    if row_count <= limit:
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
    """Record the transition. The LOCAL record is written first and is not optional.

    2026-08-04: the DB insert below is the only record this guard used to keep, and it is
    wrapped in `except: print(warning)` — so the single write that most needs an audit trail
    (a mass state flip, authorised by an override, at a moment when the database is already
    misbehaving) could proceed with nothing but a line on stdout. An audit trail that
    disappears exactly when the database is unhealthy is not an audit trail. A durable local
    JSONL record is written and fsync'd first; only then is the DB row attempted.
    """
    record = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "bot": "bulk-update-guard", "event": "bulk_state_change",
        "table_name": table, "operation": "bulk_update",
        "row_count": row_count, "to_state": changed_state_value(patch)[:120],
        "patch": patch, "reason": (reason or "")[:2000],
        "actor": (actor or "unknown")[:200], "override_token": (token or "")[:200],
    }
    try:
        home = os.environ.get(
            "CLAUDE_ORCH_HOME",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".runtime"))
        logdir = os.path.join(home, "logs")
        os.makedirs(logdir, exist_ok=True)
        with open(os.path.join(logdir, "bulk-update-guard.log"), "a") as fh:
            fh.write(json.dumps(record, separators=(",", ":"), default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    except OSError as e:
        # No durable record means no reversal path. Refuse rather than proceed blind.
        raise BulkStateChangeRefused(
            f"REFUSED bulk state change on '{table}': the audit record could not be written "
            f"({e}), so the transition would be irreversible. Fix the log path and retry.")
    try:
        import db
        db.insert("bulk_state_change_audit", {
            "table_name": table,
            "operation": "bulk_update",
            "row_count": int(row_count) if row_count is not None else -1,
            "to_state": changed_state_value(patch)[:120],
            "reason": (reason or "")[:2000],
            "actor": (actor or "unknown")[:200],
            "override_token": (token or "")[:200],
        })
    except Exception as e:
        print(f"[bulk-guard] WARNING: could not write audit ROW (local JSONL record was "
              f"written and is authoritative): {e}", flush=True)


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
