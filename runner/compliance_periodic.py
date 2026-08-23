#!/usr/bin/env python3
"""Production scheduling + operational SLOs for the compliance subsystem.

The Round 8 audit found the compliance modules had an API surface but nothing
that ran them on a clock: `evidence_bus.flush()` — the durable outbox that
exists precisely so a DB outage cannot discard evidence — was called from one
ad-hoc caller and no schedule at all, so a spooled backlog drained only by
accident. Scorecards and cross-module anomaly detection were request-only.

This module is the scheduled half. Each `run_*` is a zero-argument entrypoint
matching the `periodic.JOBS` contract, so it inherits that module's per-job
`fcntl` lock, wedge reaping and disable-on-missing-relation handling for free
rather than reimplementing any of it.

Two invariants hold for every job here:

* **No protected-state mutation.** These jobs observe and deliver. They never
  write `tasks.state`, never claim, never merge. The only writes are evidence
  delivery (append-only, idempotent by key), metric snapshots, and alert rows.
* **Fail-soft.** A job returns a dict describing what happened. Errors are
  reported in that dict and logged; they never raise into the scheduler.
"""
from __future__ import annotations

import os
import time
from typing import Any

# ── documented intervals ────────────────────────────────────────────────────
# These are the values registered in runner._SCHEDULE. Kept here next to the
# jobs so the cadence is reviewable with the code it paces, and overridable
# per-fleet through ORCH_-prefixed keys (fleet_control pushes those).
#
#   outbox flush   120s  — the outbox is a availability buffer, not a queue;
#                          it should be near-empty. Two minutes bounds evidence
#                          loss exposure to one window if the machine dies.
#   scorecard      900s  — scorecards feed human review, not control loops;
#                          15 minutes is well inside any reaction time.
#   anomaly        600s  — needs >=4 samples of history to say anything, so a
#                          10 minute cadence gives a usable series within an hour.
#   health          60s  — readiness must be fresher than the thing it gates.
DEFAULT_INTERVALS = {
    "complianceoutbox": 120,
    "compliancescorecard": 900,
    "complianceanomaly": 600,
    "compliancehealth": 60,
}


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, "") or default))
    except (TypeError, ValueError):
        return default


#: SLOs. Breaching one is what turns a metric into an alert.
OUTBOX_BACKLOG_MAX = _env_int("ORCH_COMPLIANCE_OUTBOX_BACKLOG_MAX", 500)
OUTBOX_AGE_MAX_S = _env_int("ORCH_COMPLIANCE_OUTBOX_AGE_MAX_S", 3600)
FRESHNESS_MAX_S = _env_int("ORCH_COMPLIANCE_FRESHNESS_MAX_S", 86400)
CONSUMER_LAG_MAX = _env_int("ORCH_COMPLIANCE_CONSUMER_LAG_MAX", 1000)
OUTBOX_FLUSH_LIMIT = _env_int("ORCH_COMPLIANCE_OUTBOX_FLUSH_LIMIT", 500)
ANOMALY_THRESHOLD_Z = 3.0


def _emit(kind: str, **fields: Any) -> None:
    """Structured metric. Never raises — observability must not break the job."""
    try:
        import events
        events.emit(kind, **fields)
    except Exception:
        pass


def _alert(headline: str, detail: str = "") -> None:
    """Route an SLO breach. Each channel is independently fail-soft.

    Same three-channel idiom as periodic._alert_wedged: a human ping, a
    durable approval row, and a filed remediation task. Any one of them being
    unavailable must not suppress the others or fail the job.
    """
    try:
        import notify
        notify.send(f"[compliance] {headline}"[:400])
    except Exception:
        pass
    try:
        import db
        db.insert("approvals", {
            "project": "beethoven", "kind": "compliance-slo", "status": "open",
            "title": headline[:200], "why": detail[:2000] or headline[:2000],
            "risk": "compliance evidence or scoring is not keeping up",
        })
    except Exception:
        pass


# ── jobs ────────────────────────────────────────────────────────────────────

def run_outbox_flush() -> dict[str, Any]:
    """Drain the durable evidence outbox and alert if it is not keeping up.

    Delivery is idempotent (DB unique key on the idempotency key), so a retry
    that races another flusher is safe; the periodic lock makes overlap
    unlikely rather than impossible.
    """
    result: dict[str, Any] = {"job": "complianceoutbox", "delivered": 0,
                              "pending": 0, "corrupt": 0, "oldest_age_s": None,
                              "breached": [], "error": None}
    try:
        import evidence_bus
    except Exception as exc:
        result["error"] = f"evidence_bus unavailable: {exc}"[:300]
        return result

    try:
        before = evidence_bus.backlog()
        result["delivered"] = int(evidence_bus.flush(limit=OUTBOX_FLUSH_LIMIT) or 0)
        after = evidence_bus.backlog()
    except Exception as exc:
        result["error"] = str(exc)[:300]
        _emit("compliance:outbox_flush_failed", error=result["error"])
        return result

    result["pending"] = after.get("pending", 0)
    result["corrupt"] = after.get("corrupt", 0)
    result["oldest_age_s"] = after.get("oldest_age_s")

    if result["pending"] > OUTBOX_BACKLOG_MAX:
        result["breached"].append("backlog_depth")
    age = result["oldest_age_s"]
    if age is not None and age > OUTBOX_AGE_MAX_S:
        result["breached"].append("backlog_age")
    if result["corrupt"]:
        result["breached"].append("corrupt_rows")

    _emit("compliance:outbox_flush", delivered=result["delivered"],
          pending=result["pending"], corrupt=result["corrupt"],
          oldest_age_s=age, before_pending=before.get("pending", 0))

    if result["breached"]:
        _alert(
            f"evidence outbox not draining ({', '.join(result['breached'])})",
            f"pending={result['pending']} corrupt={result['corrupt']} "
            f"oldest_age_s={age} delivered_this_pass={result['delivered']}",
        )
    return result


def _fleet_telemetry() -> dict[str, dict[str, float]]:
    """Per-app telemetry for the scorecard. Read-only; empty on any failure."""
    try:
        import db
    except Exception:
        return {}
    try:
        projects = db.select("projects", {"select": "id,name"}) or []
    except Exception:
        return {}
    telemetry: dict[str, dict[str, float]] = {}
    for project in projects:
        name = str((project or {}).get("name") or "").strip()
        if not name:
            continue
        try:
            done = db.select("tasks", {"select": "id", "project_id": f"eq.{project['id']}",
                                       "state": "in.(DONE,MERGED)", "limit": "1000"}) or []
            queued = db.select("tasks", {"select": "id", "project_id": f"eq.{project['id']}",
                                         "state": "eq.QUEUED", "limit": "1000"}) or []
        except Exception:
            continue
        total = len(done) + len(queued)
        telemetry[name] = {
            "throughput": float(len(done)),
            "backlog": float(len(queued)),
            "completion_rate": (len(done) / total) if total else 0.0,
        }
    return telemetry


def run_scorecard_refresh() -> dict[str, Any]:
    """Recompute fleet + department scorecards and persist a metric snapshot."""
    result: dict[str, Any] = {"job": "compliancescorecard", "apps": 0,
                              "weakest_app": None, "persisted": False, "error": None}
    telemetry = _fleet_telemetry()
    result["apps"] = len(telemetry)
    if not telemetry:
        result["error"] = "no telemetry available"
        _emit("compliance:scorecard_skipped", reason="no-telemetry")
        return result

    try:
        import cade_scorecard
        scorecard = cade_scorecard.fleet_scorecard(telemetry)
    except Exception as exc:
        result["error"] = str(exc)[:300]
        _emit("compliance:scorecard_failed", error=result["error"])
        return result

    result["weakest_app"] = scorecard.get("weakest_app")
    result["recommended_next_capability"] = scorecard.get("recommended_next_capability")

    snapshot = {}
    for app, row in (scorecard.get("apps") or {}).items():
        try:
            snapshot[f"compliance_composite_{app}"] = float(row.get("composite") or 0.0)
        except (TypeError, ValueError):
            continue
    try:
        import metric_history
        metric_history.record_snapshot(snapshot)
        result["persisted"] = True
    except Exception as exc:
        result["error"] = f"snapshot not persisted: {exc}"[:300]

    _emit("compliance:scorecard_refresh", apps=result["apps"],
          weakest_app=result["weakest_app"], persisted=result["persisted"])
    return result


def run_anomaly_check() -> dict[str, Any]:
    """Cross-module anomaly sweep over persisted metric history.

    `anomaly.py` already watches queue-level counters on its own schedule.
    This is the compliance-scoped complement: it runs the rolling z-score
    detector over the composite scores this subsystem persists, which nothing
    was doing on a clock.
    """
    result: dict[str, Any] = {"job": "complianceanomaly", "checked": 0,
                              "anomalies": [], "error": None}
    try:
        import anomaly_detector
        import metric_history
    except Exception as exc:
        result["error"] = f"detector unavailable: {exc}"[:300]
        return result

    detector = anomaly_detector.CrossModuleAnomalyDetector()
    try:
        history = metric_history.read_history
    except Exception as exc:
        result["error"] = str(exc)[:300]
        return result

    metrics = []
    try:
        import db
        projects = db.select("projects", {"select": "name"}) or []
        metrics = [f"compliance_composite_{p['name']}" for p in projects if p.get("name")]
    except Exception:
        metrics = []

    for metric in metrics:
        try:
            series = history(metric, hours=24) or []
            values = [float(point.get("value")) for point in series
                      if isinstance(point, dict) and point.get("value") is not None]
        except Exception:
            continue
        if len(values) < 4:
            continue
        result["checked"] += 1
        try:
            found = detector.detect(metric, values, ANOMALY_THRESHOLD_Z)
        except Exception:
            continue
        if found is None:
            continue
        result["anomalies"].append({"metric": metric, "severity": found.severity,
                                    "z_score": found.z_score, "value": found.value})

    _emit("compliance:anomaly_sweep", checked=result["checked"],
          anomalies=len(result["anomalies"]))
    for row in result["anomalies"]:
        if row["severity"] == "critical":
            _alert(f"compliance metric anomaly: {row['metric']}",
                   f"value={row['value']} z={row['z_score']} severity={row['severity']}")
    return result


# ── health / readiness ──────────────────────────────────────────────────────

def health() -> dict[str, Any]:
    """Readiness snapshot: backlog age, outbox failures, consumer lag, freshness.

    Pure observation — it must be safe to poll from an HTTP handler at any
    rate, so it never writes, never alerts, and never raises. `status` is
    "ok" | "degraded" | "unknown"; "unknown" means a probe could not be read,
    which is deliberately distinct from a healthy answer.
    """
    checks: dict[str, Any] = {}
    breached: list[str] = []

    # Outbox: depth, corruption and age of the oldest undelivered row.
    try:
        import evidence_bus
        state = evidence_bus.backlog()
        age = state.get("oldest_age_s")
        checks["outbox"] = {
            "pending": state.get("pending", 0),
            "corrupt": state.get("corrupt", 0),
            "oldest_age_s": age,
            "backlog_max": OUTBOX_BACKLOG_MAX,
            "age_max_s": OUTBOX_AGE_MAX_S,
        }
        if state.get("pending", 0) > OUTBOX_BACKLOG_MAX:
            breached.append("outbox_backlog")
        if age is not None and age > OUTBOX_AGE_MAX_S:
            breached.append("outbox_age")
        if state.get("corrupt", 0):
            breached.append("outbox_corrupt")
    except Exception as exc:
        checks["outbox"] = {"error": str(exc)[:200]}

    # Consumer lag: spooled-but-undelivered rows are the only lag the outbox
    # can observe locally; the delivered side is authoritative in the DB.
    try:
        pending = checks.get("outbox", {}).get("pending")
        checks["consumer_lag"] = {"undelivered": pending, "max": CONSUMER_LAG_MAX}
        if isinstance(pending, int) and pending > CONSUMER_LAG_MAX:
            breached.append("consumer_lag")
    except Exception as exc:
        checks["consumer_lag"] = {"error": str(exc)[:200]}

    # Data freshness: how long since evidence actually landed in the DB.
    try:
        import evidence_bus
        rows = evidence_bus.events(limit=1) or []
        newest = rows[0].get("created_at") if rows else None
        age_s = None
        if newest:
            import datetime
            parsed = datetime.datetime.fromisoformat(str(newest).replace("Z", "+00:00"))
            stamp = parsed.timestamp()
            age_s = max(0, int(time.time() - stamp))
        checks["freshness"] = {"newest_event_age_s": age_s, "max_s": FRESHNESS_MAX_S}
        if age_s is not None and age_s > FRESHNESS_MAX_S:
            breached.append("stale_evidence")
    except Exception as exc:
        checks["freshness"] = {"error": str(exc)[:200]}

    unknown = any(isinstance(v, dict) and "error" in v for v in checks.values())
    if breached:
        status = "degraded"
    elif unknown:
        status = "unknown"
    else:
        status = "ok"
    return {"status": status, "breached": breached, "checks": checks,
            "intervals": dict(DEFAULT_INTERVALS), "checked_at": int(time.time())}


def run_health() -> dict[str, Any]:
    """Scheduled health probe: same snapshot, but it records and alerts."""
    snapshot = health()
    _emit("compliance:health", status=snapshot["status"],
          breached=",".join(snapshot["breached"]))
    if snapshot["status"] == "degraded":
        _alert("compliance readiness degraded",
               f"breached={snapshot['breached']} checks={snapshot['checks']}")
    return snapshot
