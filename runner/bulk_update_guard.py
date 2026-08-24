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


#: What `row_count` means when the guard could not determine it.
#:
#: bulk_state_change_audit.row_count is `integer NOT NULL`, so "we could not count the rows"
#: has to be encoded as a value rather than as NULL. It was written as a bare `-1` literal at
#: the one place that produces it, which cost a full investigation
#: (investigate-audit-anomaly-20260814-p3qz): 37 rows reading row_count=-1, actor='unknown'
#: were read as impossible/corrupt data from an unidentified writer, and the proposed remedy
#: was a `CHECK (row_count >= 0)` constraint.
#:
#: They are neither corrupt nor anonymous. They are this guard working: `check()` refuses an
#: UNBOUNDED state flip when the count is unknown unless an operator sets
#: ORCH_ALLOW_BULK_STATE_CHANGE, and when the operator does, `_audit` records the transition
#: with the count it never had. `actor='unknown'` is the parameter default on `check()` /
#: `audited_bulk_update()` (and the column default in Postgres), not a mystery writer.
#:
#: DO NOT add `CHECK (row_count >= 0)`. It would make this insert fail on exactly the
#: unknown-count path — the most dangerous write in the system would become the one that
#: goes unaudited, which is the failure mode the whole module exists to prevent.
ROW_COUNT_UNKNOWN = -1


def _default_actor():
    """Best available identity for a caller that did not name itself.

    Every one of the 37 audited rows says actor='unknown', which reads as "no writer could be
    identified" and sent the investigation looking for a rogue process. It only ever meant
    "the caller used the parameter default". ORCH_ACTOR is already set fleet-wide and is what
    db.update() passes, so falling back to it recovers a real name in the common case; the
    literal survives only when there is genuinely nothing to report. Never raises.
    """
    try:
        return (os.environ.get("ORCH_ACTOR") or "").strip() or "unknown"
    except Exception:
        return "unknown"

#: Prefixed onto the audit `reason` whenever ROW_COUNT_UNKNOWN is stored, so the row explains
#: itself in a plain `select *` and nobody has to re-derive the above from source again.
UNKNOWN_COUNT_NOTE = (
    f"[row_count={ROW_COUNT_UNKNOWN} means COUNT-UNDETERMINED, not a negative count: the "
    f"affected-row count could not be read before this operator-authorised transition] ")


def changed_state_value(patch):
    for f in STATE_FIELDS:
        if f in (patch or {}):
            return str(patch[f])
    return ""


def check(table, patch, row_count, actor=None, reason=""):
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
    # Normalise ONCE, so the local JSONL and the DB row cannot disagree about what happened.
    # They previously could: the JSONL kept row_count=None while the DB row silently became
    # -1, so the durable record that is documented as authoritative did not contain the value
    # an investigator would later find in Postgres.
    count_unknown = row_count is None
    stored_count = ROW_COUNT_UNKNOWN if count_unknown else int(row_count)
    stored_reason = ((UNKNOWN_COUNT_NOTE if count_unknown else "") + (reason or ""))[:2000]
    stored_actor = (actor or _default_actor())[:200]

    record = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "bot": "bulk-update-guard", "event": "bulk_state_change",
        "table_name": table, "operation": "bulk_update",
        "row_count": stored_count, "row_count_unknown": count_unknown,
        "to_state": changed_state_value(patch)[:120],
        "patch": patch, "reason": stored_reason,
        "actor": stored_actor, "override_token": (token or "")[:200],
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
            "row_count": stored_count,
            "to_state": changed_state_value(patch)[:120],
            "reason": stored_reason,
            "actor": stored_actor,
            "override_token": (token or "")[:200],
        })
    except Exception as e:
        print(f"[bulk-guard] WARNING: could not write audit ROW (local JSONL record was "
              f"written and is authoritative): {e}", flush=True)


def audited_bulk_update(table, match, patch, actor=None, reason=""):
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
