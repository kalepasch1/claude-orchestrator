#!/usr/bin/env python3
"""stage_cycle_time.py — stage-level cycle time and first-pass merge rate.

Section 3 of the throughput directive, bullet 1:

    Instrument stage-level cycle time per task: queued->claimed, claimed->coder-done,
    ->QA, ->merged, ->released; publish p50/p90 per project + per model route on the SLO
    dashboard. "First-pass merge rate" per route is the headline metric.

`route_escalation.py` is the actuator for bullets 2 and 3 of the same section, and it
already ships. What was missing is the measurement those rules are steered by: the fleet
could see *that* a route merged, never *where a task spent its hours* or *how often a route
merges on the first attempt*. `orchestrator_metrics.load_outcomes_data()` reports a field
called `first_pass_rate`, but it means "tests passed and no retries" — a coder-stage
quality signal, not a merge outcome. A route can score 1.0 there and still be the "0/12
merged" route the incident named, because the diff can pass its own tests and never
survive the merge train. The headline metric this module publishes is the merge one:
integrated AND attempts <= 1.

WHY PURE
--------
Same split as `outcome_slo.py`, and for the same reason: every computation here takes rows
and returns numbers, so p50/p90 accuracy is testable against a synthetic load without a
database, a lane or a model call. `summarize()` is the only function that touches the DB,
and it is a thin fetch wrapper around the pure `report()`.

CONVENTIONS (repo CLAUDE.md)
----------------------------
- Fail-soft everywhere: a malformed row is skipped, never fatal. Metric loss is always
  preferable to wedging the pipeline that produces the metric.
- Thin samples report None, not 0.0. A green first-pass rate computed from two rows is
  worse than no reading, because `route_escalation` and the operator both act on it.
- Python 3.9 is this fleet's interpreter: no PEP 604 unions at runtime, hence the
  `from __future__ import annotations` below.
"""
from __future__ import annotations

import os
import uuid
import datetime
import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)

#: Ordered pipeline stages. The names are the `outcomes.outcome_stage` vocabulary; the
#: transitions below are derived from consecutive pairs, so adding a stage here is enough
#: to start reporting it.
STAGES = ("queued", "claimed", "coder_done", "qa", "merged", "released")

#: Human-facing transition names, in pipeline order.
TRANSITIONS = tuple(
    "{}->{}".format(a, b) for a, b in zip(STAGES, STAGES[1:])
)

#: Minimum observations before a percentile or rate is reported as anything but None.
MIN_SAMPLES = int(os.environ.get("SLO_CYCLE_TIME_MIN_SAMPLES", "5"))

#: Upper bound on rows pulled per fetch, so a long lookback cannot page the whole history
#: into a dashboard process.
MAX_ROWS = int(os.environ.get("SLO_CYCLE_TIME_MAX_ROWS", "20000"))

#: Attempts at or above which a merge is no longer "first pass". Attempt numbering is
#: 1-based, matching `route_escalation.ESCALATE_AFTER_ATTEMPTS`.
FIRST_PASS_MAX_ATTEMPTS = int(os.environ.get("SLO_FIRST_PASS_MAX_ATTEMPTS", "1"))

#: Aliases seen in the wild for each canonical stage. Stage strings are written by several
#: producers over the fleet's history and an unrecognised spelling would silently drop a
#: whole transition from the dashboard.
#: The UPPERCASE spellings are the task-state vocabulary written to
#: `workflow_outcome_contracts.to_state`, which is the fleet's only real transition log —
#: 48k rows over 1.5k tasks. `outcomes` cannot serve this purpose: every row in it carries
#: outcome_stage='delivery', so it records one point per task and no transitions at all.
_STAGE_ALIASES = {
    "queued": ("queued", "queue", "pending"),
    "claimed": ("claimed", "claim", "running", "started"),
    "coder_done": ("coder_done", "coder-done", "coded", "coder", "implemented", "done"),
    "qa": ("qa", "qa_done", "tested", "review", "verified", "testpass", "testfail"),
    "merged": ("merged", "merge", "integrated"),
    "released": ("released", "release", "deployed", "shipped"),
}

_CANONICAL_STAGE = {
    alias: canonical
    for canonical, aliases in _STAGE_ALIASES.items()
    for alias in aliases
}


# ─── Coercion helpers (never raise) ──────────────────────────────────────────

def canonical_stage(value: Any) -> str:
    """Canonical stage name for whatever the producer wrote, or '' if unrecognised."""
    if not isinstance(value, str):
        return ""
    return _CANONICAL_STAGE.get(value.strip().lower().replace(" ", "_"), "")


def parse_ts(value: Any) -> Optional[float]:
    """Epoch seconds from an ISO-8601 string, epoch number or datetime. None if unusable.

    Accepts the trailing 'Z' Postgres and `datetime.utcnow().isoformat() + "Z"` both emit;
    `datetime.fromisoformat` rejects it outright on Python 3.9.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, datetime.datetime):
        return value.timestamp()
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def _first_present(row: Dict[str, Any], *keys: str) -> Any:
    """First key actually present with a non-None value.

    NOT `row.get(a) or row.get(b)`: an epoch timestamp of 0 and a stage recorded at second
    zero of a synthetic run are both falsy, and the `or` form silently discarded them —
    which dropped the whole `queued->claimed` transition, the one the directive cares most
    about, from every report whose producer used relative timestamps.
    """
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def percentile(values: Sequence[float], fraction: float) -> Optional[float]:
    """Nearest-rank percentile of `values`. None when the sample is empty.

    Nearest-rank (not interpolated) so a reported p90 is always a duration some task
    actually experienced — an interpolated p90 of a 6-sample lane is a number no task ever
    took, and operators act on these figures.
    """
    clean = sorted(float(v) for v in values if isinstance(v, (int, float))
                   and not isinstance(v, bool))
    if not clean:
        return None
    fraction = min(max(float(fraction), 0.0), 1.0)
    rank = max(1, int(round(fraction * len(clean) + 0.5)) - 1)
    return clean[min(rank, len(clean) - 1)]


# ─── Pure computation ────────────────────────────────────────────────────────

def stage_durations(events: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    """Per-task seconds spent in each pipeline transition.

    `events` are rows of {task_id|slug, stage, at}. Rows missing any of those, or carrying
    an unrecognised stage or unparseable timestamp, are skipped. Where a stage is recorded
    more than once for a task (a retried claim, a re-run QA) the EARLIEST timestamp wins,
    so a retry cannot make a stage look faster than it was.

    Returns {task_key: {transition: seconds}}. Transitions whose endpoints were not both
    observed are simply absent — never 0.0, which would read as "instant" on a dashboard.
    """
    first_seen: Dict[str, Dict[str, float]] = {}
    for row in events or ():
        if not isinstance(row, dict):
            continue
        key = _first_present(row, "task_id", "slug")
        stage = canonical_stage(_first_present(row, "stage", "outcome_stage"))
        at = parse_ts(_first_present(row, "at", "created_at", "recorded_at"))
        if not key or not stage or at is None:
            continue
        seen = first_seen.setdefault(str(key), {})
        if stage not in seen or at < seen[stage]:
            seen[stage] = at

    out: Dict[str, Dict[str, float]] = {}
    for key, stages in first_seen.items():
        spans: Dict[str, float] = {}
        for start, end in zip(STAGES, STAGES[1:]):
            if start in stages and end in stages:
                delta = stages[end] - stages[start]
                # A negative span means clock skew or out-of-order writes. Dropping it is
                # right: a negative duration would drag a p50 below zero.
                if delta >= 0:
                    spans["{}->{}".format(start, end)] = delta
        if spans:
            out[key] = spans
    return out


def first_pass_merge_rate(rows: Iterable[Dict[str, Any]]) -> Optional[float]:
    """Fraction of terminal tasks that merged on the first attempt. None if sample is thin.

    This is the headline metric. Denominator is every task that reached a terminal outcome
    on the route, not just the ones that merged — otherwise a route that merges one task in
    twelve scores 1.0.
    """
    total = 0
    first_pass = 0
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        total += 1
        attempts = row.get("attempts")
        if isinstance(attempts, bool) or not isinstance(attempts, (int, float)):
            attempts = 1  # unrecorded attempt count is the optimistic reading
        merged = bool(row.get("integrated") or row.get("state") == "MERGED")
        if merged and attempts <= FIRST_PASS_MAX_ATTEMPTS:
            first_pass += 1
    if total < MIN_SAMPLES:
        return None
    return round(first_pass / total, 4)


def _bucket(rows: Iterable[Dict[str, Any]], field: str) -> Dict[str, List[Dict[str, Any]]]:
    """Group rows by `field`, defaulting a missing or blank value to 'unknown'."""
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        name = row.get(field) or "unknown"
        buckets.setdefault(str(name), []).append(row)
    return buckets


def _percentiles_for(rows: Sequence[Dict[str, Any]],
                     durations: Dict[str, Dict[str, float]]) -> Dict[str, Dict[str, Any]]:
    """p50/p90/n per transition for the tasks in `rows`."""
    keys = {str(_first_present(r, "task_id", "slug")) for r in rows if isinstance(r, dict)}
    out: Dict[str, Dict[str, Any]] = {}
    for transition in TRANSITIONS:
        samples = [spans[transition] for key, spans in durations.items()
                   if key in keys and transition in spans]
        if not samples:
            continue
        thin = len(samples) < MIN_SAMPLES
        out[transition] = {
            "n": len(samples),
            "p50_s": None if thin else round(percentile(samples, 0.50) or 0.0, 1),
            "p90_s": None if thin else round(percentile(samples, 0.90) or 0.0, 1),
        }
    return out


def report(rows: Iterable[Dict[str, Any]],
           events: Optional[Iterable[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Full stage-cycle-time report, grouped by project and by model route.

    `rows` are outcome rows (project, model, attempts, integrated, task_id/slug).
    `events` are stage-transition rows; when omitted, `rows` are used as their own events,
    which is what the `outcomes` table supports today (one row per stage via
    `outcome_stage`). Pure: no DB, no clock beyond the timestamps in the data.
    """
    rows = [r for r in (rows or ()) if isinstance(r, dict)]
    durations = stage_durations(events if events is not None else rows)

    def group(field: str) -> Dict[str, Dict[str, Any]]:
        return {
            name: {
                "tasks": len(bucket),
                "first_pass_merge_rate": first_pass_merge_rate(bucket),
                "stages": _percentiles_for(bucket, durations),
            }
            for name, bucket in _bucket(rows, field).items()
        }

    return {
        "transitions": list(TRANSITIONS),
        "min_samples": MIN_SAMPLES,
        "tasks_observed": len(rows),
        "tasks_with_timings": len(durations),
        "first_pass_merge_rate": first_pass_merge_rate(rows),
        "by_project": group("project"),
        "by_route": group("model"),
    }


# ─── Recording ───────────────────────────────────────────────────────────────

#: Task states worth a transition row. Every other state (heartbeats, note-only patches)
#: is ignored so the log stays a pipeline record rather than an audit of every PATCH.
RECORDED_STATES = frozenset({
    "QUEUED", "RUNNING", "DONE", "MERGED", "RELEASED",
    "TESTPASS", "TESTFAIL", "BLOCKED", "QUARANTINED",
})


def record_transition(task_id: Any, to_state: Any, project_id: Any = None,
                      from_state: Any = None, lane: Optional[str] = None) -> bool:
    """Append one state transition to `workflow_outcome_contracts`. True if written.

    This is the producer half of the instrumentation, and the reason the p50/p90 panel was
    empty: the transition log holds 48k historical rows and had dropped to roughly one row
    a day, so nothing recent could be measured. Without a producer the whole percentile
    path is dead code no matter how correct it is.

    Fail-soft and never raises — it is called from `db.update`, the hottest write path in
    the fleet, and a metrics write must never be able to fail a task state change.
    """
    state = str(to_state or "").strip().upper()
    if not task_id or state not in RECORDED_STATES:
        return False
    stage = canonical_stage(state)
    if not stage:
        return False
    try:
        import db
        now = datetime.datetime.utcnow()
        db.insert("workflow_outcome_contracts", {
            # A re-entered state (QUEUED again after a zombie release) must not collide
            # with its earlier occurrence. Milliseconds alone are not enough — two writes
            # inside one millisecond produced the same key, and against the NOT NULL
            # `transition_key` that silently drops the second transition.
            "transition_key": "state:{}:{}:{}:{}".format(
                task_id, state, int(now.timestamp() * 1000), uuid.uuid4().hex[:8]),
            "task_id": str(task_id),
            "project_id": str(project_id) if project_id else None,
            "lane": lane or os.environ.get("ORCH_LANE", "runner"),
            "from_state": str(from_state) if from_state else None,
            "to_state": state,
            "stage": stage,
            "contract": {"source": "stage_cycle_time.record_transition"},
            "observed_at": now.isoformat() + "Z",
        })
        return True
    except Exception as exc:  # pragma: no cover - exercised only against a live DB
        logger.debug("stage_cycle_time.record_transition: %s", exc)
        return False


# ─── The one impure read ─────────────────────────────────────────────────────

def summarize(lookback_hours: int = 168) -> Dict[str, Any]:
    """Fetch recent outcomes plus their state transitions and return `report()`.

    Two fetches because the two halves live in different tables: `outcomes` carries the
    route and project a task ran under (and its attempt count, for the headline metric),
    while `workflow_outcome_contracts` is the only place the fleet records WHEN a task
    changed state. Joined on task_id. Fail-soft: {} on any error, and a failed event fetch
    degrades to rates-without-timings rather than losing the whole panel.
    """
    since = (datetime.datetime.utcnow()
             - datetime.timedelta(hours=max(1, int(lookback_hours)))).isoformat()
    try:
        import db  # local import: the pure half must import without a DB module present
        # select_all, not select: `select` stops at one PostgREST page (1000 rows) and the
        # fleet produces more than that per week, so a percentile built on it would silently
        # describe an arbitrary 1000-row slice rather than the window asked for.
        rows = db.select_all("outcomes", {
            "select": "task_id,slug,project,model,attempts,integrated,outcome_stage,created_at",
            "created_at": "gte.{}".format(since),
        }, max_rows=MAX_ROWS, order="created_at.desc") or []
    except Exception as exc:  # pragma: no cover - exercised only against a live DB
        logger.debug("stage_cycle_time.summarize outcomes: %s", exc)
        return {}

    events: List[Dict[str, Any]] = []
    try:
        import db
        # Newest-first for the same reason as above: `select_all` pages id.asc by default,
        # so a window that overflows MAX_ROWS would be answered with the OLDEST rows in it —
        # exactly inverted from what a lookback means, and the transitions would then belong
        # to different tasks than the outcomes they are joined against.
        for row in db.select_all("workflow_outcome_contracts", {
            "select": "task_id,to_state,observed_at",
            "observed_at": "gte.{}".format(since),
        }, max_rows=MAX_ROWS, order="observed_at.desc") or []:
            events.append({"task_id": row.get("task_id"),
                           "stage": row.get("to_state"),
                           "at": row.get("observed_at")})
    except Exception as exc:  # pragma: no cover - exercised only against a live DB
        logger.debug("stage_cycle_time.summarize transitions: %s", exc)

    try:
        return report(rows, events if events else None)
    except Exception as exc:  # pragma: no cover - report() is total by construction
        logger.debug("stage_cycle_time.report: %s", exc)
        return {}


if __name__ == "__main__":  # pragma: no cover
    import json
    print(json.dumps(summarize(), indent=2, default=str))
