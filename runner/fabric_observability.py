"""
fabric_observability.py — fleet / session / delivery observability for the development
session fabric, plus the reversible rollout that turns it on.

WHAT IS MISSING TODAY. `slo_controller` measures whether the fleet is MOVING and
`outcome_slo` measures whether what it builds is GOOD. Neither can answer the question
the operator actually asks: how many improvements reached a USER today, how long an
objective took to get there, and how often the fleet said "shipped" when nothing shipped.
DONE and MERGED are counted as if they were delivery; they are not — a branch exists, or
it is on an integration branch. Only DEPLOYED_AND_VERIFIED means a user can reach it.

WHY THIS MODULE IS PURE. Every existing SLO check fetches inside the check function, so
none can be exercised under a simulated load, and none can be shadow-read before rollout.
This module takes ROWS and returns metrics; a caller does the fetching. That split is what
makes stage 1 of the rollout ("shadow-read projections") possible at all.

ZERO FABRICATED POINTS — the load-bearing rule. Every metric is UNKNOWN (`value: None`)
rather than 0 when the sample is too thin or the field is missing. A zero improvements/day
and a no-data improvements/day mean opposite things, and a dashboard that renders them the
same is worse than no dashboard: it is the mechanism by which a stalled fleet looks calm.
`ok is None` matches the existing checks, which already skip remediation for UNKNOWN, so a
thin sample can never trigger an automated action.

CONVENTIONS (repo CLAUDE.md). Fail-soft: a malformed row is skipped, never fatal; nothing
here raises. All thresholds are SLO_-prefixed env vars so they are fleet-pushable via
fleet_control.py.
"""
import logging
import math
import os
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# ─── The one state that means a user can reach the change ────────────────────

#: Mirrors development_session_contract.DEPLOYED_AND_VERIFIED. Restated rather than
#: imported so this module has no import-order dependency on the contract package and
#: can be shadow-read on a host that has not taken that change yet.
DEPLOYED_AND_VERIFIED = "DEPLOYED_AND_VERIFIED"

#: States routinely mistaken for delivery. Named so the mistake is assertable.
NON_DELIVERY_STATES: Tuple[str, ...] = ("DONE", "MERGED")

# ─── Thresholds ──────────────────────────────────────────────────────────────

SLO_VERIFIED_PER_DAY = float(os.environ.get("SLO_VERIFIED_PER_DAY", "3"))
SLO_OBJECTIVE_TO_VERIFIED_P95_S = float(
    os.environ.get("SLO_OBJECTIVE_TO_VERIFIED_P95_S", "86400"))
SLO_FALSE_SHIPPED_RATE = float(os.environ.get("SLO_FALSE_SHIPPED_RATE", "0.02"))
SLO_PHANTOM_RATE = float(os.environ.get("SLO_PHANTOM_RATE", "0.05"))
SLO_RECOVERY_RATE = float(os.environ.get("SLO_RECOVERY_RATE", "0.80"))
SLO_QUEUE_AGE_P95_S = float(os.environ.get("SLO_QUEUE_AGE_P95_S", "172800"))
SLO_GENERATION_DRIFT = float(os.environ.get("SLO_GENERATION_DRIFT", "1"))
SLO_SESSION_RECONNECT_LOSS = float(os.environ.get("SLO_SESSION_RECONNECT_LOSS", "0.05"))
SLO_COST_PER_VERIFIED_USD = float(os.environ.get("SLO_COST_PER_VERIFIED_USD", "5"))
SLO_JOURNEY_RELIABILITY = float(os.environ.get("SLO_JOURNEY_RELIABILITY", "0.90"))

#: Below this many observations a metric reports UNKNOWN rather than a number.
SLO_MIN_SAMPLES = int(os.environ.get("SLO_FABRIC_MIN_SAMPLES", "5"))

#: Metric ids, pinned — the operator view and the alert routes key on these.
METRICS: Tuple[str, ...] = (
    "verified_per_day",
    "objective_to_verified_p50_s",
    "objective_to_verified_p95_s",
    "false_shipped_rate",
    "phantom_rate",
    "recovery_rate",
    "queue_age_p95_s",
    "host_generation_drift",
    "session_reconnect_loss",
    "cost_per_verified_change_usd",
    "journey_reliability",
)

#: Metrics where LOWER is better. Everything else is "higher is better".
LOWER_IS_BETTER: Tuple[str, ...] = (
    "objective_to_verified_p50_s", "objective_to_verified_p95_s",
    "false_shipped_rate", "phantom_rate", "queue_age_p95_s",
    "host_generation_drift", "session_reconnect_loss",
    "cost_per_verified_change_usd",
)


def _num(value, default=None):
    """Coerce to float, or return `default`. Never raises. bool is never a measurement."""
    if isinstance(value, bool):
        return default
    try:
        if value is None:
            return default
        n = float(value)
        return n if n == n and n not in (float("inf"), float("-inf")) else default
    except (TypeError, ValueError):
        return default


def percentile(values: Sequence[float], pct: float) -> Optional[float]:
    """Nearest-rank percentile. None on an empty or unusable sample — never 0.0."""
    clean = sorted(v for v in (_num(v) for v in (values or [])) if v is not None)
    if not clean:
        return None
    if pct <= 0:
        return clean[0]
    if pct >= 100:
        return clean[-1]
    # CEIL, not round: this is the textbook nearest-rank definition. round() uses
    # banker's rounding, so p50 of a 5-element sample landed on rank 2 instead of 3 and
    # the "median" was pulled below half the observations — a latency SLO that reads
    # optimistic by one rank on every odd-length sample.
    rank = max(1, int(math.ceil(pct / 100.0 * len(clean))))
    return clean[min(rank, len(clean)) - 1]


class Metric(dict):
    """One measurement plus its verdict.

    A dict so it serialises straight to the operator view. `ok is None` means UNKNOWN,
    and every consumer must treat that as "do not act", not as "fine".
    """

    def __init__(self, name: str, value: Optional[float], threshold: Optional[float],
                 samples: int = 0, reason: str = "", drill: Optional[Dict] = None):
        ok: Optional[bool]
        if value is None:
            ok = None
        elif threshold is None:
            ok = None
        elif name in LOWER_IS_BETTER:
            ok = value <= threshold
        else:
            ok = value >= threshold
        super().__init__(name=name, value=value, threshold=threshold, ok=ok,
                         samples=int(samples or 0), reason=reason, drill=drill or {})

    @property
    def unknown(self) -> bool:
        return self["ok"] is None


def _thin(name, threshold, samples, needed=None):
    needed = SLO_MIN_SAMPLES if needed is None else needed
    return Metric(name, None, threshold, samples,
                  reason=f"UNKNOWN: {samples} sample(s), need {needed}")


def _rate(numerator: int, denominator: int) -> Optional[float]:
    if not denominator:
        return None
    return round(numerator / float(denominator), 4)


def _is_delivered(row) -> bool:
    """Delivered means DEPLOYED_AND_VERIFIED. DONE and MERGED are not delivery."""
    state = row.get("state") or row.get("lifecycle_state")
    return isinstance(state, str) and state.strip().upper() == DEPLOYED_AND_VERIFIED


def _group(rows, key):
    out: Dict[Any, List[Dict]] = {}
    for row in rows or ():
        if isinstance(row, dict):
            out.setdefault(row.get(key), []).append(row)
    return out


# ─── Metrics ─────────────────────────────────────────────────────────────────


def verified_per_day(rows: Iterable[Dict], window_days: float = 1.0) -> Metric:
    """Production-VERIFIED improvements per day.

    The headline number, and the one the fleet has historically got wrong by counting
    merges. A merge is not a delivery.
    """
    rows = [r for r in (rows or ()) if isinstance(r, dict)]
    days = _num(window_days) or 0.0
    if days <= 0:
        return Metric("verified_per_day", None, SLO_VERIFIED_PER_DAY, len(rows),
                      reason="UNKNOWN: window must be > 0 days")
    if not rows:
        return _thin("verified_per_day", SLO_VERIFIED_PER_DAY, 0)
    delivered = [r for r in rows if _is_delivered(r)]
    return Metric("verified_per_day", round(len(delivered) / days, 3),
                  SLO_VERIFIED_PER_DAY, len(rows),
                  drill={"by_project": {k: len(v) for k, v in
                                        _group(delivered, "project").items()}})


def objective_to_verified(rows: Iterable[Dict]) -> Tuple[Metric, Metric]:
    """p50 / p95 seconds from objective accepted to DEPLOYED_AND_VERIFIED.

    Only DELIVERED rows contribute. Including undelivered work would make the number
    improve every time something got stuck and never shipped.
    """
    durations = []
    for row in rows or ():
        if not isinstance(row, dict) or not _is_delivered(row):
            continue
        seconds = _num(row.get("objective_to_verified_s"))
        if seconds is None:
            start, end = _num(row.get("objective_at")), _num(row.get("verified_at"))
            seconds = None if (start is None or end is None) else end - start
        if seconds is not None and seconds >= 0:
            durations.append(seconds)
    n = len(durations)
    if n < SLO_MIN_SAMPLES:
        return (_thin("objective_to_verified_p50_s", None, n),
                _thin("objective_to_verified_p95_s", SLO_OBJECTIVE_TO_VERIFIED_P95_S, n))
    return (Metric("objective_to_verified_p50_s", percentile(durations, 50), None, n),
            Metric("objective_to_verified_p95_s", percentile(durations, 95),
                   SLO_OBJECTIVE_TO_VERIFIED_P95_S, n))


def false_shipped_rate(rows: Iterable[Dict]) -> Metric:
    """Fraction of work CLAIMED shipped that is not actually deployed and verified.

    This is the fleet lying to itself, measured. A row claims delivery via
    `claimed_shipped`; it earns it only by reaching DEPLOYED_AND_VERIFIED.
    """
    claimed = [r for r in (rows or ())
               if isinstance(r, dict) and bool(r.get("claimed_shipped"))]
    if len(claimed) < SLO_MIN_SAMPLES:
        return _thin("false_shipped_rate", SLO_FALSE_SHIPPED_RATE, len(claimed))
    false = [r for r in claimed if not _is_delivered(r)]
    return Metric("false_shipped_rate", _rate(len(false), len(claimed)),
                  SLO_FALSE_SHIPPED_RATE, len(claimed),
                  drill={"by_host": {k: len(v) for k, v in _group(false, "host").items()}})


def phantom_rate(rows: Iterable[Dict]) -> Metric:
    """Fraction of closed work with no artifact behind it.

    A phantom is a closure that records no commit — the claim cannot be reproduced,
    reverted or audited, which is the same as not having happened.
    """
    closed = [r for r in (rows or ())
              if isinstance(r, dict)
              and str(r.get("state") or "").upper() in
              (NON_DELIVERY_STATES + (DEPLOYED_AND_VERIFIED,))]
    if len(closed) < SLO_MIN_SAMPLES:
        return _thin("phantom_rate", SLO_PHANTOM_RATE, len(closed))
    phantom = [r for r in closed
               if not (r.get("artifact_commit") or r.get("artifact_sha"))]
    return Metric("phantom_rate", _rate(len(phantom), len(closed)),
                  SLO_PHANTOM_RATE, len(closed),
                  drill={"by_project": {k: len(v) for k, v in
                                        _group(phantom, "project").items()}})


def recovery_rate(rows: Iterable[Dict]) -> Metric:
    """Of the work that failed and was retried, how much eventually got delivered."""
    attempted = [r for r in (rows or ())
                 if isinstance(r, dict) and bool(r.get("recovery_attempted"))]
    if len(attempted) < SLO_MIN_SAMPLES:
        return _thin("recovery_rate", SLO_RECOVERY_RATE, len(attempted))
    recovered = [r for r in attempted if _is_delivered(r)]
    return Metric("recovery_rate", _rate(len(recovered), len(attempted)),
                  SLO_RECOVERY_RATE, len(attempted))


def queue_age_p95(rows: Iterable[Dict]) -> Metric:
    """p95 age of work still waiting. The far end of the queue is where starvation hides."""
    ages = [a for a in (_num(r.get("queued_age_s")) for r in (rows or ())
                        if isinstance(r, dict)) if a is not None and a >= 0]
    if len(ages) < SLO_MIN_SAMPLES:
        return _thin("queue_age_p95_s", SLO_QUEUE_AGE_P95_S, len(ages))
    return Metric("queue_age_p95_s", percentile(ages, 95), SLO_QUEUE_AGE_P95_S, len(ages))


def host_generation_drift(hosts: Iterable[Dict]) -> Metric:
    """Spread between the newest and oldest runner generation in the fleet.

    Drift is how a host keeps writing under a stale lease. Measured as a SPREAD, not a
    count of stale hosts, because one host four generations behind is a different
    problem from four hosts one behind.
    """
    gens = [g for g in (_num(h.get("generation")) for h in (hosts or ())
                        if isinstance(h, dict)) if g is not None]
    if not gens:
        return _thin("host_generation_drift", SLO_GENERATION_DRIFT, 0, needed=1)
    drift = max(gens) - min(gens)
    stale = [h for h in hosts
             if isinstance(h, dict) and _num(h.get("generation")) not in (None, max(gens))]
    return Metric("host_generation_drift", drift, SLO_GENERATION_DRIFT, len(gens),
                  drill={"behind": [h.get("host") for h in stale]})


def session_reconnect_loss(sessions: Iterable[Dict]) -> Metric:
    """Fraction of resumed sessions that lost events across the reconnect.

    A gap in the dense per-session sequence means an event was lost in transit — the
    difference between a replay that reconstructs the session and one that reconstructs
    a different session.
    """
    resumed = [s for s in (sessions or ())
               if isinstance(s, dict) and bool(s.get("resumed"))]
    if len(resumed) < SLO_MIN_SAMPLES:
        return _thin("session_reconnect_loss", SLO_SESSION_RECONNECT_LOSS, len(resumed))
    lossy = [s for s in resumed if (_num(s.get("event_gaps"), 0) or 0) > 0]
    return Metric("session_reconnect_loss", _rate(len(lossy), len(resumed)),
                  SLO_SESSION_RECONNECT_LOSS, len(resumed),
                  drill={"by_session": [s.get("session_id") for s in lossy]})


def cost_per_verified_change(rows: Iterable[Dict]) -> Metric:
    """Total spend divided by DELIVERED changes.

    Denominator is deliveries, not merges. Dividing by merges is how cost per change
    falls while nothing reaches a user.
    """
    rows = [r for r in (rows or ()) if isinstance(r, dict)]
    spend = sum(_num(r.get("cost_usd"), 0) or 0 for r in rows)
    delivered = [r for r in rows if _is_delivered(r)]
    if not delivered:
        return Metric("cost_per_verified_change_usd", None, SLO_COST_PER_VERIFIED_USD,
                      len(rows),
                      reason="UNKNOWN: nothing was verified; cost per change is undefined, "
                             "not infinite and not zero")
    return Metric("cost_per_verified_change_usd", round(spend / len(delivered), 4),
                  SLO_COST_PER_VERIFIED_USD, len(delivered))


def journey_reliability(journeys: Iterable[Dict]) -> Metric:
    """Fraction of end-to-end journeys that completed without an operator rescue.

    A journey that only finished because a human intervened did not work.
    """
    seen = [j for j in (journeys or ()) if isinstance(j, dict)]
    if len(seen) < SLO_MIN_SAMPLES:
        return _thin("journey_reliability", SLO_JOURNEY_RELIABILITY, len(seen))
    good = [j for j in seen if j.get("completed") and not j.get("manual_intervention")]
    return Metric("journey_reliability", _rate(len(good), len(seen)),
                  SLO_JOURNEY_RELIABILITY, len(seen))


# ─── The operator view ───────────────────────────────────────────────────────


def evaluate(tasks: Iterable[Dict] = (), hosts: Iterable[Dict] = (),
             sessions: Iterable[Dict] = (), journeys: Iterable[Dict] = (),
             window_days: float = 1.0) -> Dict[str, Any]:
    """Compute every metric. Pure: rows in, verdicts out, no I/O.

    Returns the ONE operator view: metrics keyed by id, plus breached / unknown lists
    so an alert route never has to re-derive them and never has to guess what `ok: None`
    meant. Fail-soft: an exception in one metric leaves that metric UNKNOWN rather than
    taking the whole view down — a broken dashboard tile must not blind the other ten.
    """
    tasks = list(tasks or ())
    metrics: Dict[str, Metric] = {}

    def _safe(name, fn, *args):
        try:
            return fn(*args)
        except Exception as e:
            logger.warning("fabric_observability: %s failed (%s); reporting UNKNOWN",
                           name, e)
            return Metric(name, None, None, 0, reason=f"UNKNOWN: computation failed ({e})")

    metrics["verified_per_day"] = _safe(
        "verified_per_day", verified_per_day, tasks, window_days)
    try:
        p50, p95 = objective_to_verified(tasks)
    except Exception as e:
        p50 = Metric("objective_to_verified_p50_s", None, None, 0, reason=str(e))
        p95 = Metric("objective_to_verified_p95_s", None, None, 0, reason=str(e))
    metrics["objective_to_verified_p50_s"] = p50
    metrics["objective_to_verified_p95_s"] = p95
    metrics["false_shipped_rate"] = _safe("false_shipped_rate", false_shipped_rate, tasks)
    metrics["phantom_rate"] = _safe("phantom_rate", phantom_rate, tasks)
    metrics["recovery_rate"] = _safe("recovery_rate", recovery_rate, tasks)
    metrics["queue_age_p95_s"] = _safe("queue_age_p95_s", queue_age_p95, tasks)
    metrics["host_generation_drift"] = _safe(
        "host_generation_drift", host_generation_drift, hosts)
    metrics["session_reconnect_loss"] = _safe(
        "session_reconnect_loss", session_reconnect_loss, sessions)
    metrics["cost_per_verified_change_usd"] = _safe(
        "cost_per_verified_change_usd", cost_per_verified_change, tasks)
    metrics["journey_reliability"] = _safe(
        "journey_reliability", journey_reliability, journeys)

    return {
        "metrics": metrics,
        "breached": sorted(k for k, m in metrics.items() if m["ok"] is False),
        "unknown": sorted(k for k, m in metrics.items() if m["ok"] is None),
        "window_days": window_days,
    }


def alerts(view: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Alertable breaches, with the drill-down attached.

    UNKNOWN never alerts. That is deliberate and it is the whole zero-fabricated-points
    rule in one line: paging someone because a metric has no data trains them to ignore
    the pager, and the pager is the only thing standing between a false-shipped rate and
    a customer finding out first.
    """
    out = []
    for name in sorted((view or {}).get("breached", ())):
        metric = view["metrics"][name]
        out.append({"metric": name, "value": metric["value"],
                    "threshold": metric["threshold"], "samples": metric["samples"],
                    "drill": metric.get("drill") or {}})
    return out


# ─── Rollout ─────────────────────────────────────────────────────────────────

#: Ordered, reversible. Each stage is gated by its own ORCH_ switch so any stage can be
#: turned off independently and instantly — a rollout you cannot stop at the stage you
#: are in is not staged, it is just slow.
ROLLOUT_STAGES: Tuple[str, ...] = (
    "shadow",    # compute projections, write nothing anyone reads
    "canary",    # one repo on one Mac reads them
    "adapters",  # the session adapters read them
    "embeds",    # product surfaces read them
)

STAGE_SWITCHES: Dict[str, str] = {
    "shadow": "ORCH_FABRIC_OBS_SHADOW",
    "canary": "ORCH_FABRIC_OBS_CANARY",
    "adapters": "ORCH_FABRIC_OBS_ADAPTERS",
    "embeds": "ORCH_FABRIC_OBS_EMBEDS",
}

#: One switch that turns everything off regardless of stage.
KILL_SWITCH = "ORCH_FABRIC_OBS_DISABLED"


def _on(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in ("1", "true", "yes", "on")


def stage_enabled(stage: str) -> bool:
    """Is this stage live?

    Fails CLOSED: an unknown stage, or the kill switch, is off. A staged rollout that
    defaults ON when it cannot tell has no stages.
    """
    if _on(KILL_SWITCH):
        return False
    switch = STAGE_SWITCHES.get(stage)
    if not switch:
        return False
    return _on(switch)


def active_stage() -> Optional[str]:
    """The furthest stage currently enabled, or None. Order is the source of truth."""
    live = [s for s in ROLLOUT_STAGES if stage_enabled(s)]
    return live[-1] if live else None


def rollout_plan() -> Dict[str, Any]:
    """The rollout as data, including how to reverse it.

    Shadow first is not ceremony: these metrics change what the fleet does, and a metric
    that is wrong in shadow costs a diff, while the same metric wrong at the adapters
    stage stops delivery.
    """
    return {
        "stages": ROLLOUT_STAGES,
        "switches": dict(STAGE_SWITCHES),
        "kill_switch": KILL_SWITCH,
        "active": active_stage(),
        "order": (
            "1. shadow: compute projections, compare against the existing SLO surface, "
            "read nothing back into decisions",
            "2. canary: one repo on one Mac consumes them",
            "3. adapters: session adapters consume them",
            "4. embeds: product surfaces consume them",
        ),
        "rollback": (
            f"unset the stage switch, or set {KILL_SWITCH}=1 to stop every stage at "
            "once; no data migration is required because shadow writes are additive "
            "and nothing downstream is required to read them"
        ),
        "invariant": (
            "UNKNOWN is never rendered as 0 and never alerts, at any stage"
        ),
    }
