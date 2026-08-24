#!/usr/bin/env python3
"""Exact queue counters used by autopilot and dashboard parity checks.

REAL-TIME QUEUE STATE (slice 1)
-------------------------------
`exact_counts()` is the queue-state read that autopilot, the dashboard parity check and
the monitors all poll. Its fallback path costs **25 PostgREST round-trips per call** —
12 state counts, 1 total, 2 prefix counts, 1 canary count and 5 release-fix prefixes
counted twice (QUEUED and RUNNING). Nothing memoized it, so every poller paid the full
25 independently, and "poll the queue state more often" meant multiplying that number by
the number of pollers.

Two changes here, both narrow:

  * A short-TTL snapshot cache behind a module-level singleton, so concurrent pollers in
    one process share one read instead of each issuing 25. TTL is env-tunable and can be
    set to 0 to restore the previous always-fresh behaviour exactly.
  * The view fast-path's `except Exception: pass` now writes a diagnostic before it
    swallows. Per this repo's conventions a broad catch IS the fail-soft convention, but
    a *silent* one is the defect: when `v_task_queue_counters` broke, callers silently
    fell back to the 25-round-trip path with nothing anywhere saying why they got slower.

Correctness is unchanged: a cache miss computes exactly what it computed before, and the
cached payload is the same dict.
"""
import os
import threading
import time

import db

QUEUE_STATES = tuple(
    s.strip().upper()
    for s in os.environ.get(
        "ORCH_QUEUE_COUNTER_STATES",
        "QUEUED,RUNNING,RETRY,DONE,MERGED,BLOCKED,CONFLICT,TESTFAIL,QUARANTINED,DECOMPOSED,SHELVED,WAITING",
    ).split(",")
    if s.strip()
)
BLOCKED_LIKE = ("BLOCKED", "CONFLICT", "TESTFAIL")
ACTIVE_LIKE = ("QUEUED", "RUNNING", "RETRY")
RECOVERY_PREFIX = "recover-missing-branch-"
IMPROVE_PREFIX = "improve-"
CANARY_PREFIX = "canary-"
RELEASE_FIX_PREFIXES = ("relfix-", "qafix-", "deployfix-", "buildfix-", "copyfix-")


# ── Snapshot cache (module-level singleton) ─────────────────────────────────
# Deliberately a module-level singleton rather than a parameter threaded through every
# caller: exact_counts() is called from autopilot, the dashboard parity check and the
# monitors, none of which share an object graph, so a cache they must be handed is a
# cache none of them will use.


def _default_ttl():
    """TTL in seconds. 0 disables caching entirely (previous behaviour, exactly)."""
    try:
        return max(0.0, float(os.environ.get("ORCH_QUEUE_COUNTER_TTL", "5")))
    except (TypeError, ValueError):
        return 5.0


class _Snapshot:
    """One cached counters payload, guarded by a lock, with observable stats."""

    def __init__(self):
        self._lock = threading.Lock()
        self._value = None
        self._at = 0.0
        self.hits = 0
        self.misses = 0

    def get(self, compute, ttl=None, now=None):
        ttl = _default_ttl() if ttl is None else max(0.0, float(ttl))
        now = time.monotonic() if now is None else now
        if ttl <= 0:
            self.misses += 1
            return compute()
        with self._lock:
            fresh = self._value is not None and (now - self._at) < ttl
            if fresh:
                self.hits += 1
                return dict(self._value)
        # Compute OUTSIDE the lock. Holding it across ~25 network round-trips would turn
        # a cache meant to reduce latency into a serialization point that adds it.
        value = compute()
        with self._lock:
            self._value = dict(value) if isinstance(value, dict) else value
            # Stamp with the time the read STARTED, not the time it finished. A slow
            # 25-round-trip read would otherwise present as fresher than it is.
            self._at = now
            self.misses += 1
        return value

    def invalidate(self):
        with self._lock:
            self._value = None
            self._at = 0.0

    def stats(self):
        with self._lock:
            return {"cached": self._value is not None, "age": (
                max(0.0, time.monotonic() - self._at) if self._value is not None else None),
                "hits": self.hits, "misses": self.misses, "ttl": _default_ttl()}


_snapshot = _Snapshot()


def invalidate():
    """Drop the cached snapshot. Call after a write that must be visible immediately."""
    _snapshot.invalidate()


def stats():
    """Cache observability for operators and tests."""
    return _snapshot.stats()


def _int_count(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"db.count returned non-numeric value {type(value).__name__}")
    return int(value)


def _count(db_client, params=None):
    return _int_count(db_client.count("tasks", params or {}))


def _state_count(db_client, state):
    return _count(db_client, {"state": f"eq.{state}"})


def _prefix_count(db_client, prefix, state=None):
    params = {"slug": f"like.{prefix}%"}
    if state:
        params["state"] = f"eq.{state}"
    return _count(db_client, params)


def _release_fix_count(db_client, state=None):
    return sum(_prefix_count(db_client, prefix, state=state) for prefix in RELEASE_FIX_PREFIXES)


def _view_counts(db_client):
    if not hasattr(db_client, "select"):
        return None
    rows = db_client.select("v_task_queue_counters", {"select": "bucket,name,n"}) or []
    if not isinstance(rows, list):
        return None
    rows = [r for r in rows if isinstance(r, dict) and r.get("bucket") and r.get("name")]
    if not rows:
        return None
    states = {r["name"]: _int_count(r.get("n", 0)) for r in rows if r.get("bucket") == "state"}
    totals = {r["name"]: _int_count(r.get("n", 0)) for r in rows if r.get("bucket") == "total"}
    prefixes = {r["name"]: _int_count(r.get("n", 0)) for r in rows if r.get("bucket") == "prefix"}
    total_tasks = totals.get("tasks", sum(states.values()))
    queued = states.get("QUEUED", 0)
    running = states.get("RUNNING", 0)
    retry = states.get("RETRY", 0)
    blocked_like = sum(states.get(state, 0) for state in BLOCKED_LIKE)
    active_like = sum(states.get(state, 0) for state in ACTIVE_LIKE)
    return {
        "states": states,
        "total_tasks": total_tasks,
        "known_state_total": sum(states.values()),
        "unknown_state_total": max(0, total_tasks - sum(states.values())),
        "queued": queued,
        "running": running,
        "retry": retry,
        "active_like": active_like,
        "blocked_like": blocked_like,
        "quarantined": states.get("QUARANTINED", 0),
        "recovery_queued": prefixes.get("recovery_queued", 0),
        "improvements_queued": prefixes.get("improvements_queued", 0),
        "canaries_active": prefixes.get("canaries_active", 0),
        "release_fix_queued": prefixes.get("release_fix_queued", 0),
        "release_fix_running": prefixes.get("release_fix_running", 0),
        "source": "v_task_queue_counters",
    }


def exact_counts(db_client=None, *, ttl=None, fresh=False):
    """Return exact full-table queue pressure counters.

    Sampled task lists are useful for recency, but they hide old backlog once the queue is deeper
    than the UI or autopilot sample window. These counters use PostgREST's SQL count path instead.

    Results are memoized for `ORCH_QUEUE_COUNTER_TTL` seconds (default 5, 0 disables) so
    concurrent pollers share one read. Pass `fresh=True` to bypass the cache for a
    correctness-critical read, or `ttl=` to override the window for one call.
    """
    # Resolved here rather than as a default argument so that `db` stays late-bound:
    # a default of `db_client=db` freezes the module object at import time, which makes
    # the identity check below untestable and the module unmockable.
    default = db
    if db_client is None:
        db_client = default

    if fresh:
        _snapshot.invalidate()
        return _compute_counts(db_client)
    # Cache ONLY the default client. A snapshot keyed on nothing would happily hand a
    # caller passing db_client=A the counters computed from db_client=B — which is
    # exactly what it did on the first draft of this change, silently crossing fixtures
    # between tests. Every real polling caller (autopilot, fleet_stuck_alarm,
    # scoreboard_data) uses the default client, so this keeps the whole win and gives up
    # nothing that anyone actually asks for.
    if db_client is not db:
        return _compute_counts(db_client)
    return _snapshot.get(lambda: _compute_counts(db_client), ttl=ttl)


def _compute_counts(db_client=db):
    """The uncached read. Exactly the previous behaviour of exact_counts()."""
    try:
        from_view = _view_counts(db_client)
        if from_view:
            return from_view
    except Exception as exc:  # noqa: BLE001 — fail-soft, but NOT silent
        # The bare `pass` that used to live here meant a broken v_task_queue_counters
        # degraded callers from 1 round-trip to 25 with no signal anywhere. Fail-soft is
        # the convention; swallowing without a diagnostic is the defect.
        print(f"queue_counters: v_task_queue_counters unavailable "
              f"({type(exc).__name__}: {exc}); falling back to per-state counts")

    states = {state: _state_count(db_client, state) for state in QUEUE_STATES}
    total_tasks = _count(db_client, {})
    known_state_total = sum(states.values())
    queued = states.get("QUEUED", 0)
    running = states.get("RUNNING", 0)
    retry = states.get("RETRY", 0)
    blocked_like = sum(states.get(state, 0) for state in BLOCKED_LIKE)
    active_like = sum(states.get(state, 0) for state in ACTIVE_LIKE)
    recovery_queued = _prefix_count(db_client, RECOVERY_PREFIX, state="QUEUED")
    improvements_queued = _prefix_count(db_client, IMPROVE_PREFIX, state="QUEUED")
    canaries_active = _count(db_client, {
        "slug": f"like.{CANARY_PREFIX}%",
        "state": "in.(QUEUED,RUNNING)",
    })
    release_fix_queued = _release_fix_count(db_client, state="QUEUED")
    release_fix_running = _release_fix_count(db_client, state="RUNNING")
    return {
        "states": states,
        "total_tasks": total_tasks,
        "known_state_total": known_state_total,
        "unknown_state_total": max(0, total_tasks - known_state_total),
        "queued": queued,
        "running": running,
        "retry": retry,
        "active_like": active_like,
        "blocked_like": blocked_like,
        "quarantined": states.get("QUARANTINED", 0),
        "recovery_queued": recovery_queued,
        "improvements_queued": improvements_queued,
        "canaries_active": canaries_active,
        "release_fix_queued": release_fix_queued,
        "release_fix_running": release_fix_running,
        "source": "postgrest_exact_count",
    }
