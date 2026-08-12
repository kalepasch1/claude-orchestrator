#!/usr/bin/env python3
"""
compliance_event_router.py — durable, cross-process routing for compliance events.

WHAT THIS REPLACES

`ComplianceEventStream` fans out synchronously to in-process callbacks and keeps
its history in a Python list. Three consequences, all invisible until they matter:

  * A subscriber that raises is logged once and the event is dropped. No retry,
    no record that the consumer never saw it.
  * A consumer in another process cannot see the event at all.
  * A restart loses `_history` and every consumer's position, so there is no
    answer to "which events has this consumer actually handled?"

For a compliance stream that is the wrong failure mode: the missing delivery is
exactly the one an auditor asks about.

WHAT THIS GUARANTEES

  Ordering       Strict, by monotonic `seq`. Replay from any offset yields the
                 same sequence, so a re-run is comparable to the original.
  Idempotent in  `publish()` keys on the evidence-bus idempotency key. Publishing
                 the same logical event twice inserts one row.
  At-least-once  Delivery is retried until it succeeds or exhausts its budget.
  Exactly-once   For effects recorded through `ctx.record(...)`: the effect row
    EFFECTS      and the consumer's offset advance are written in ONE SQLite
                 transaction. A crash before commit rolls back both, so redelivery
                 re-runs the handler and the effect lands exactly once. A crash
                 cannot land the effect without the offset, or the offset without
                 the effect.

                 This is the whole reason the router hands the handler a context
                 object instead of just the event. An effect the handler writes
                 somewhere else — a POST, a file, another database — is outside
                 the transaction and is therefore at-least-once. That is stated
                 rather than papered over: exactly-once is a property of the
                 ledger, not a property the router can grant to arbitrary code.

  Dead-letter    After `max_attempts` failures the event is dead-lettered and the
                 offset advances past it. A poisoned event must not wedge a
                 compliance stream behind it; the dead-letter row is the durable
                 record, and `requeue_dead_letters()` puts it back.

`events.py` and `evidence_bus.py` receipts are untouched — every publish still
emits both. This router is an additional durable path, not a replacement for the
evidence trail.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional

import evidence_bus

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(os.path.dirname(HERE), ".runtime")

DEFAULT_MAX_ATTEMPTS = int(os.environ.get("ORCH_COMPLIANCE_ROUTER_MAX_ATTEMPTS", "3"))
DEFAULT_BATCH = int(os.environ.get("ORCH_COMPLIANCE_ROUTER_BATCH", "100"))

_lock = threading.RLock()
_conn: Optional[sqlite3.Connection] = None
_conn_path: Optional[str] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def db_path() -> str:
    """Resolved at call time, not import time, so a test can point it at a tmpdir."""
    return os.environ.get(
        "ORCH_COMPLIANCE_ROUTER_DB", os.path.join(RUNTIME, "compliance_router.db")
    )


SCHEMA = """
CREATE TABLE IF NOT EXISTS outbox (
    seq              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id         TEXT NOT NULL UNIQUE,
    idempotency_key  TEXT NOT NULL UNIQUE,
    kind             TEXT NOT NULL,
    app_id           TEXT NOT NULL,
    tenant_id        TEXT NOT NULL DEFAULT 'default',
    payload          TEXT NOT NULL DEFAULT '{}',
    occurred_at      TEXT,
    enqueued_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_outbox_kind ON outbox(kind, seq);

CREATE TABLE IF NOT EXISTS consumer_offsets (
    consumer    TEXT PRIMARY KEY,
    seq         INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deliveries (
    consumer     TEXT NOT NULL,
    event_id     TEXT NOT NULL,
    seq          INTEGER NOT NULL,
    attempts     INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL,
    last_error   TEXT,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (consumer, event_id)
);

CREATE TABLE IF NOT EXISTS dead_letters (
    consumer   TEXT NOT NULL,
    event_id   TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    attempts   INTEGER NOT NULL,
    error      TEXT,
    dead_at    TEXT NOT NULL,
    PRIMARY KEY (consumer, event_id)
);

CREATE TABLE IF NOT EXISTS effects (
    consumer     TEXT NOT NULL,
    effect_key   TEXT NOT NULL,
    event_id     TEXT NOT NULL,
    seq          INTEGER NOT NULL,
    value        TEXT,
    recorded_at  TEXT NOT NULL,
    PRIMARY KEY (consumer, effect_key)
);
"""


def _connect() -> Optional[sqlite3.Connection]:
    """Module-level singleton keyed on the resolved path, per the runner convention."""
    global _conn, _conn_path
    path = db_path()
    with _lock:
        if _conn is not None and _conn_path == path:
            return _conn
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass
            _conn = None
        try:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            conn.executescript(SCHEMA)
            _conn, _conn_path = conn, path
            return _conn
        except Exception as exc:
            _emit("compliance_router:open_failed", error=str(exc)[:300], path=path)
            return None


def _emit(kind: str, **fields: Any) -> None:
    """Never let telemetry failure take down the router."""
    try:
        import events

        events.emit(kind, **fields)
    except Exception:
        pass


def reset_connection() -> None:
    """Drop the cached handle. Reopening reads state from disk — a process restart."""
    global _conn, _conn_path
    with _lock:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass
        _conn, _conn_path = None, None


# ── publish ──────────────────────────────────────────────────────────────────

def publish(
    kind: str,
    app_id: str,
    payload: Optional[dict] = None,
    tenant_id: str = "default",
    event_id: Optional[str] = None,
    occurred_at: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> dict:
    """Durably enqueue an event. Re-publishing the same logical event is a no-op.

    The key is `evidence_bus.idempotency_key`, so the outbox and the evidence trail
    agree on what "the same event" means instead of each having its own opinion.
    """
    payload = payload or {}
    key = idempotency_key or evidence_bus.idempotency_key(app_id, kind, event_id or "", payload)
    conn = _connect()
    if conn is None:
        return {"seq": None, "duplicate": False, "persisted": False}
    row = {
        "event_id": event_id or key,
        "idempotency_key": key,
        "kind": kind,
        "app_id": app_id,
        "tenant_id": tenant_id,
        "payload": json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str),
        "occurred_at": occurred_at or _now(),
        "enqueued_at": _now(),
    }
    with _lock:
        try:
            cur = conn.execute(
                "INSERT OR IGNORE INTO outbox "
                "(event_id, idempotency_key, kind, app_id, tenant_id, payload, occurred_at, enqueued_at) "
                "VALUES (:event_id, :idempotency_key, :kind, :app_id, :tenant_id, :payload, :occurred_at, :enqueued_at)",
                row,
            )
            if cur.rowcount == 0:
                existing = conn.execute(
                    "SELECT seq FROM outbox WHERE idempotency_key = ?", (key,)
                ).fetchone()
                return {
                    "seq": existing["seq"] if existing else None,
                    "duplicate": True,
                    "persisted": True,
                }
            return {"seq": cur.lastrowid, "duplicate": False, "persisted": True}
        except Exception as exc:
            _emit("compliance_router:publish_failed", error=str(exc)[:300], kind=kind)
            return {"seq": None, "duplicate": False, "persisted": False}


# ── delivery ─────────────────────────────────────────────────────────────────

class DeliveryContext:
    """Handed to a handler so its effect can join the router's transaction.

    `record()` writes into the same SQLite transaction that advances the offset.
    Either both land or neither does — that is what makes the effect exactly-once
    across a restart.
    """

    def __init__(self, conn: sqlite3.Connection, consumer: str, event: dict) -> None:
        self._conn = conn
        self.consumer = consumer
        self.event = event

    def record(self, effect_key: str, value: Any = None) -> bool:
        """Record an idempotent effect. Returns False if this key already landed."""
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO effects (consumer, effect_key, event_id, seq, value, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                self.consumer,
                effect_key,
                self.event["event_id"],
                self.event["seq"],
                json.dumps(value, sort_keys=True, default=str) if value is not None else None,
                _now(),
            ),
        )
        return cur.rowcount > 0


Handler = Callable[[dict, DeliveryContext], None]


def _row_to_event(row: sqlite3.Row) -> dict:
    return {
        "seq": row["seq"],
        "event_id": row["event_id"],
        "kind": row["kind"],
        "app_id": row["app_id"],
        "tenant_id": row["tenant_id"],
        "payload": json.loads(row["payload"] or "{}"),
        "occurred_at": row["occurred_at"],
    }


def offset(consumer: str) -> int:
    conn = _connect()
    if conn is None:
        return 0
    row = conn.execute(
        "SELECT seq FROM consumer_offsets WHERE consumer = ?", (consumer,)
    ).fetchone()
    return int(row["seq"]) if row else 0


def pending(consumer: str, limit: int = DEFAULT_BATCH) -> list[dict]:
    """Events this consumer has not yet passed, in seq order. Read-only."""
    conn = _connect()
    if conn is None:
        return []
    rows = conn.execute(
        "SELECT * FROM outbox WHERE seq > ? ORDER BY seq ASC LIMIT ?",
        (offset(consumer), int(limit)),
    ).fetchall()
    return [_row_to_event(r) for r in rows]


def deliver(
    consumer: str,
    handler: Handler,
    limit: int = DEFAULT_BATCH,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    _crash_after_handler: bool = False,
) -> dict:
    """Deliver pending events to `handler`, in order, advancing the durable offset.

    `_crash_after_handler` exists for the restart test: it aborts between the
    handler returning and the commit — the exact window in which a naive
    implementation double-applies an effect.
    """
    conn = _connect()
    if conn is None:
        return {"delivered": 0, "failed": 0, "dead_lettered": 0, "skipped": 0}
    result = {"delivered": 0, "failed": 0, "dead_lettered": 0, "skipped": 0}

    for event in pending(consumer, limit):
        with _lock:
            prior = conn.execute(
                "SELECT attempts, status FROM deliveries WHERE consumer = ? AND event_id = ?",
                (consumer, event["event_id"]),
            ).fetchone()
            if prior is not None and prior["status"] == "delivered":
                # Offset lags a committed delivery only if a crash landed between
                # them; re-advancing is safe and must not re-run the handler.
                _advance(conn, consumer, event["seq"])
                result["skipped"] += 1
                continue
            attempts = (prior["attempts"] if prior else 0) + 1

            try:
                conn.execute("BEGIN IMMEDIATE")
                handler(event, DeliveryContext(conn, consumer, event))
                if _crash_after_handler:
                    raise _SimulatedCrash(event["event_id"])
                conn.execute(
                    "INSERT INTO deliveries (consumer, event_id, seq, attempts, status, last_error, updated_at) "
                    "VALUES (?, ?, ?, ?, 'delivered', NULL, ?) "
                    "ON CONFLICT(consumer, event_id) DO UPDATE SET "
                    "attempts = excluded.attempts, status = 'delivered', last_error = NULL, updated_at = excluded.updated_at",
                    (consumer, event["event_id"], event["seq"], attempts, _now()),
                )
                conn.execute(
                    "INSERT INTO consumer_offsets (consumer, seq, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(consumer) DO UPDATE SET seq = excluded.seq, updated_at = excluded.updated_at",
                    (consumer, event["seq"], _now()),
                )
                conn.execute("COMMIT")
                result["delivered"] += 1
            except BaseException as exc:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                if isinstance(exc, _SimulatedCrash):
                    # Modelling a process death: nothing committed, nothing recorded.
                    raise
                _record_failure(conn, consumer, event, attempts, exc, max_attempts, result)
                if result["dead_lettered"] and attempts >= max_attempts:
                    continue
                break  # preserve order: do not deliver later events past a retrying one
    return result


class _SimulatedCrash(RuntimeError):
    """Test-only: models the process dying between handler and commit."""


def _advance(conn: sqlite3.Connection, consumer: str, seq: int) -> None:
    conn.execute(
        "INSERT INTO consumer_offsets (consumer, seq, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(consumer) DO UPDATE SET seq = excluded.seq, updated_at = excluded.updated_at",
        (consumer, seq, _now()),
    )


def _record_failure(
    conn: sqlite3.Connection,
    consumer: str,
    event: dict,
    attempts: int,
    exc: BaseException,
    max_attempts: int,
    result: dict,
) -> None:
    error = f"{type(exc).__name__}: {exc}"[:500]
    dead = attempts >= max_attempts
    try:
        conn.execute(
            "INSERT INTO deliveries (consumer, event_id, seq, attempts, status, last_error, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(consumer, event_id) DO UPDATE SET "
            "attempts = excluded.attempts, status = excluded.status, "
            "last_error = excluded.last_error, updated_at = excluded.updated_at",
            (
                consumer,
                event["event_id"],
                event["seq"],
                attempts,
                "dead_lettered" if dead else "failed",
                error,
                _now(),
            ),
        )
        if dead:
            conn.execute(
                "INSERT OR REPLACE INTO dead_letters (consumer, event_id, seq, attempts, error, dead_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (consumer, event["event_id"], event["seq"], attempts, error, _now()),
            )
            # Advance past the poison pill. A compliance stream must not stall
            # behind one bad event; the dead_letters row is the durable record.
            _advance(conn, consumer, event["seq"])
            result["dead_lettered"] += 1
        else:
            result["failed"] += 1
    except Exception as write_exc:
        _emit(
            "compliance_router:failure_write_failed",
            consumer=consumer,
            event_id=event["event_id"],
            error=str(write_exc)[:300],
        )
    _emit(
        "compliance_router:delivery_failed",
        consumer=consumer,
        event_id=event["event_id"],
        attempts=attempts,
        dead_lettered=dead,
        error=error[:300],
    )


# ── operator surface ─────────────────────────────────────────────────────────

def dead_letters(consumer: Optional[str] = None, limit: int = 200) -> list[dict]:
    conn = _connect()
    if conn is None:
        return []
    if consumer:
        rows = conn.execute(
            "SELECT * FROM dead_letters WHERE consumer = ? ORDER BY seq ASC LIMIT ?",
            (consumer, int(limit)),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM dead_letters ORDER BY seq ASC LIMIT ?", (int(limit),)
        ).fetchall()
    return [dict(r) for r in rows]


def requeue_dead_letters(consumer: str) -> int:
    """Clear the dead-letter and attempt records so the next deliver() retries them.

    The offset is rewound to just before the earliest dead letter, so ordering on
    the retry matches the original stream.
    """
    conn = _connect()
    if conn is None:
        return 0
    with _lock:
        rows = conn.execute(
            "SELECT event_id, seq FROM dead_letters WHERE consumer = ? ORDER BY seq ASC",
            (consumer,),
        ).fetchall()
        if not rows:
            return 0
        try:
            conn.execute("BEGIN IMMEDIATE")
            for row in rows:
                conn.execute(
                    "DELETE FROM deliveries WHERE consumer = ? AND event_id = ?",
                    (consumer, row["event_id"]),
                )
            conn.execute("DELETE FROM dead_letters WHERE consumer = ?", (consumer,))
            _advance(conn, consumer, int(rows[0]["seq"]) - 1)
            conn.execute("COMMIT")
        except Exception as exc:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            _emit("compliance_router:requeue_failed", consumer=consumer, error=str(exc)[:300])
            return 0
    return len(rows)


def replay(from_seq: int = 0, to_seq: Optional[int] = None, kind: Optional[str] = None) -> list[dict]:
    """Deterministic ordered read of the log. Mutates nothing — safe for audit."""
    conn = _connect()
    if conn is None:
        return []
    sql = "SELECT * FROM outbox WHERE seq > ?"
    args: list[Any] = [int(from_seq)]
    if to_seq is not None:
        sql += " AND seq <= ?"
        args.append(int(to_seq))
    if kind:
        sql += " AND kind = ?"
        args.append(kind)
    sql += " ORDER BY seq ASC"
    return [_row_to_event(r) for r in conn.execute(sql, args).fetchall()]


def effects(consumer: str, limit: int = 500) -> list[dict]:
    conn = _connect()
    if conn is None:
        return []
    rows = conn.execute(
        "SELECT * FROM effects WHERE consumer = ? ORDER BY seq ASC LIMIT ?",
        (consumer, int(limit)),
    ).fetchall()
    return [dict(r) for r in rows]


def stats() -> dict:
    conn = _connect()
    if conn is None:
        return {"events": 0, "consumers": 0, "dead_letters": 0, "effects": 0}

    def _count(table: str) -> int:
        try:
            return int(conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])
        except Exception:
            return 0

    return {
        "events": _count("outbox"),
        "consumers": _count("consumer_offsets"),
        "dead_letters": _count("dead_letters"),
        "effects": _count("effects"),
    }


def invalidate() -> bool:
    """Drop all router state. For tests and for a deliberate operator reset."""
    conn = _connect()
    if conn is None:
        return False
    with _lock:
        try:
            for table in ("effects", "dead_letters", "deliveries", "consumer_offsets", "outbox"):
                conn.execute(f"DELETE FROM {table}")
            conn.execute("DELETE FROM sqlite_sequence WHERE name = 'outbox'")
            return True
        except Exception as exc:
            _emit("compliance_router:invalidate_failed", error=str(exc)[:300])
            return False
