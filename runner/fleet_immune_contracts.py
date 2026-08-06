#!/usr/bin/env python3
"""fleet_immune_contracts.py — SHARED contracts for the fleet immune system.

Operator directive 2026-08-02 (HIGHEST PRIORITY). This module is deliberately the ONLY thing
the sibling work items may depend on: it defines the vocabulary (types, thresholds, verdicts)
for the immune system and nothing else. No process is killed here, no DB row is written here,
no daemon is scheduled here — the siblings own the actuators and wire against these contracts
so their behaviour is testable in isolation and consistent across machines.

The seven diagnoses of record from the 2026-08-02 incident map 1:1 onto the contracts below:

  1. 64/66 headless coder lanes were zombies >1h old, pinning all RAM and slots
        -> LaneSnapshot + LANE_ZOMBIE_AFTER_S + classify_lane()
  2. legal_docket.py leaked 14 concurrent copies (8-10h old, on a 30-min interval)
        -> DaemonSnapshot + detect_daemon_leak()
  3. the runner mem-gate correctly held claims because of RAM starvation CAUSED by (1)+(2)
        -> CapacityVerdict + classify_capacity(): starvation must be attributed, not just
           reported, so "claimable=803 / claiming=0" can never again read as a queue bug
  4. Mac 2's runner was down from ~10:28 with NO alert to the operator
        -> HostLiveness + classify_host()
  5. sentinel train-stale was a false alarm for days: pressure written to DB, sentinel
     watching a FILE
        -> SignalSource + AUTHORITATIVE_SOURCE: the DB is the single source of truth for
           fleet-scoped signals; file mirrors are advisory only
  6. release train batch floor of 10 silently held small merges out of production
        -> ReleaseGate + evaluate_release_gate(): a held batch must always name a reason and
           an age, so "silently" is structurally impossible
  7. weak-coder routes produced 0/12-merged cycles on legal-class tasks
        -> RouteQuality + classify_route()

CONVENTIONS (CLAUDE.md): fail-soft (bad input returns a sensible default, never raises),
env-var configuration with defaults, no external dependencies, module-level helpers.

See FLEET_IMMUNE_CONTRACTS.md for the prose version and the sibling wiring map.
"""
import os
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

CONTRACT_VERSION = "1.0.0"

# ── tunables (all env-overridable; defaults encode the 2026-08-02 findings) ───────────────
LANE_ZOMBIE_AFTER_S = int(os.environ.get("ORCH_LANE_ZOMBIE_AFTER_S", "3600"))
LANE_SUSPECT_AFTER_S = int(os.environ.get("ORCH_LANE_SUSPECT_AFTER_S", "2400"))
LANE_COUNT_WARN = int(os.environ.get("ORCH_LANE_COUNT_WARN", "25"))
DAEMON_LEAK_MAX_CONCURRENT = int(os.environ.get("ORCH_DAEMON_LEAK_MAX_CONCURRENT", "1"))
DAEMON_STUCK_INTERVAL_FACTOR = float(os.environ.get("ORCH_DAEMON_STUCK_INTERVAL_FACTOR", "1.5"))
HOST_DOWN_AFTER_S = int(os.environ.get("ORCH_HOST_DOWN_AFTER_S", "900"))
HOST_DEGRADED_AFTER_S = int(os.environ.get("ORCH_HOST_DEGRADED_AFTER_S", "300"))
RELEASE_MIN_BATCH = int(os.environ.get("RELEASE_MIN_BATCH", "1"))
RELEASE_MAX_HOLD_S = int(os.environ.get("ORCH_RELEASE_MAX_HOLD_S", "3600"))
ROUTE_MIN_SAMPLES = int(os.environ.get("ORCH_ROUTE_MIN_SAMPLES", "6"))
ROUTE_MIN_MERGE_RATE = float(os.environ.get("ORCH_ROUTE_MIN_MERGE_RATE", "0.15"))

# ── verdict vocabulary (plain strings: JSON-safe across process and DB boundaries) ────────
HEALTHY = "healthy"
SUSPECT = "suspect"
ZOMBIE = "zombie"
LEAKED = "leaked"
STUCK = "stuck"
DOWN = "down"
DEGRADED = "degraded"
STARVED = "starved"
HELD = "held"
RELEASE_OK = "release_ok"
DEMOTE = "demote"

# Diagnosis (5): fleet-scoped signals live in the DB. A file mirror may exist for humans and
# for offline mode, but a consumer that reads ONLY the file will go blind exactly when the
# writer switches to the DB — which is what made train-stale a false alarm for days.
SOURCE_DB = "db"
SOURCE_FILE = "file"
AUTHORITATIVE_SOURCE = SOURCE_DB


def _num(value, default=0.0):
    """Coerce to float, fail-soft."""
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass
class Verdict:
    """Uniform result of every immune-system classifier.

    `state`   one of the vocabulary constants above
    `reason`  human-readable; REQUIRED whenever action is taken or work is held. Diagnosis (6)
              was fundamentally a missing-reason bug: the batch floor held merges with nothing
              anywhere saying why.
    `action`  what a sibling actuator should do ("reap", "alert", "restart", "release", ...)
              or "" for no-op. Contracts describe; siblings act.
    """
    state: str = HEALTHY
    reason: str = ""
    action: str = ""
    subject: str = ""
    detail: Dict[str, Any] = field(default_factory=dict)

    @property
    def actionable(self) -> bool:
        return bool(self.action)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LaneSnapshot:
    """One headless coder lane (a `claude --output-format` process) as observed by a host."""
    pid: int = 0
    host: str = ""
    age_s: float = 0.0
    task_slug: str = ""
    cpu_pct: float = 0.0
    rss_mb: float = 0.0


@dataclass
class DaemonSnapshot:
    """One interval daemon (legal_docket.py, merge_train.py, ...) as observed by a host."""
    name: str = ""
    host: str = ""
    pids: List[int] = field(default_factory=list)
    oldest_age_s: float = 0.0
    interval_s: float = 0.0


@dataclass
class HostLiveness:
    """Last-seen heartbeat for one machine in the fleet."""
    host: str = ""
    last_heartbeat_age_s: Optional[float] = None
    runner_up: bool = True
    source: str = AUTHORITATIVE_SOURCE


@dataclass
class CapacitySignal:
    """Why the runner is (or is not) claiming work."""
    host: str = ""
    claimable: int = 0
    claiming: int = 0
    free_ram_gb: float = 0.0
    ram_floor_gb: float = 0.0
    live_lanes: int = 0
    zombie_lanes: int = 0


@dataclass
class ReleaseGate:
    """State of the production release train's batching decision."""
    pending: int = 0
    min_batch: int = RELEASE_MIN_BATCH
    oldest_pending_age_s: float = 0.0
    max_hold_s: float = RELEASE_MAX_HOLD_S


@dataclass
class RouteQuality:
    """Observed outcome record for one coder route on one task class."""
    route: str = ""
    task_class: str = ""
    samples: int = 0
    merged: int = 0


# ── classifiers ───────────────────────────────────────────────────────────────────────────

def classify_lane(lane, zombie_after_s=None, suspect_after_s=None) -> Verdict:
    """Diagnosis (1). Age-based lane triage. Never raises."""
    zombie_after_s = LANE_ZOMBIE_AFTER_S if zombie_after_s is None else zombie_after_s
    suspect_after_s = LANE_SUSPECT_AFTER_S if suspect_after_s is None else suspect_after_s
    try:
        age = _num(getattr(lane, "age_s", 0.0))
        pid = int(getattr(lane, "pid", 0) or 0)
        subject = f"lane:{pid}"
        if age >= zombie_after_s:
            return Verdict(ZOMBIE, f"lane alive {int(age)}s (>= {zombie_after_s}s) with no completion",
                           "reap", subject, {"pid": pid, "age_s": age})
        if age >= suspect_after_s:
            return Verdict(SUSPECT, f"lane alive {int(age)}s — approaching zombie threshold",
                           "watch", subject, {"pid": pid, "age_s": age})
        return Verdict(HEALTHY, "", "", subject, {"pid": pid, "age_s": age})
    except Exception:
        return Verdict(HEALTHY, "", "", "lane:?", {})


def detect_daemon_leak(daemon, max_concurrent=None, interval_factor=None) -> Verdict:
    """Diagnosis (2). More copies than allowed, or one far older than its own interval."""
    max_concurrent = DAEMON_LEAK_MAX_CONCURRENT if max_concurrent is None else max_concurrent
    interval_factor = DAEMON_STUCK_INTERVAL_FACTOR if interval_factor is None else interval_factor
    try:
        name = getattr(daemon, "name", "") or "?"
        pids = list(getattr(daemon, "pids", []) or [])
        oldest = _num(getattr(daemon, "oldest_age_s", 0.0))
        interval = _num(getattr(daemon, "interval_s", 0.0))
        subject = f"daemon:{name}"
        if len(pids) > max_concurrent:
            return Verdict(LEAKED,
                           f"{len(pids)} concurrent copies of {name} (max {max_concurrent})",
                           "reap_extra", subject,
                           {"pids": pids, "keep_newest": 1, "oldest_age_s": oldest})
        if interval > 0 and oldest > interval * interval_factor:
            return Verdict(STUCK,
                           f"{name} running {int(oldest)}s on a {int(interval)}s interval",
                           "reap", subject, {"pids": pids, "oldest_age_s": oldest})
        return Verdict(HEALTHY, "", "", subject, {"pids": pids})
    except Exception:
        return Verdict(HEALTHY, "", "", "daemon:?", {})


def classify_host(liveness, down_after_s=None, degraded_after_s=None) -> Verdict:
    """Diagnosis (4). A silent machine must ALWAYS produce an operator-visible verdict.

    An unknown heartbeat age is treated as DOWN, never as healthy: Mac 2 was dark for hours
    precisely because "no data" was indistinguishable from "fine".
    """
    down_after_s = HOST_DOWN_AFTER_S if down_after_s is None else down_after_s
    degraded_after_s = HOST_DEGRADED_AFTER_S if degraded_after_s is None else degraded_after_s
    try:
        host = getattr(liveness, "host", "") or "?"
        age = getattr(liveness, "last_heartbeat_age_s", None)
        subject = f"host:{host}"
        if not getattr(liveness, "runner_up", True):
            return Verdict(DOWN, f"{host} reports its runner is not running", "alert", subject,
                           {"host": host})
        if age is None:
            return Verdict(DOWN, f"no heartbeat on record for {host} — treat unknown as down",
                           "alert", subject, {"host": host})
        age = _num(age)
        if age >= down_after_s:
            return Verdict(DOWN, f"{host} last heartbeat {int(age)}s ago (>= {down_after_s}s)",
                           "alert", subject, {"host": host, "age_s": age})
        if age >= degraded_after_s:
            return Verdict(DEGRADED, f"{host} heartbeat lagging ({int(age)}s)", "watch", subject,
                           {"host": host, "age_s": age})
        return Verdict(HEALTHY, "", "", subject, {"host": host, "age_s": age})
    except Exception:
        return Verdict(DOWN, "host liveness unreadable — treat unknown as down", "alert", "host:?", {})


def classify_capacity(signal) -> Verdict:
    """Diagnosis (3). Attribute claim starvation to its cause instead of blaming the queue."""
    try:
        host = getattr(signal, "host", "") or "?"
        claimable = int(_num(getattr(signal, "claimable", 0)))
        claiming = int(_num(getattr(signal, "claiming", 0)))
        free = _num(getattr(signal, "free_ram_gb", 0.0))
        floor = _num(getattr(signal, "ram_floor_gb", 0.0))
        zombies = int(_num(getattr(signal, "zombie_lanes", 0)))
        live = int(_num(getattr(signal, "live_lanes", 0)))
        subject = f"capacity:{host}"
        if claimable > 0 and claiming == 0:
            if zombies > 0:
                return Verdict(STARVED,
                               f"{claimable} claimable but 0 claiming: {zombies}/{live} lanes are "
                               f"zombies holding RAM and slots — reap lanes, do not touch the queue",
                               "reap_lanes", subject,
                               {"claimable": claimable, "zombie_lanes": zombies, "live_lanes": live})
            if floor and free <= floor:
                return Verdict(STARVED,
                               f"{claimable} claimable but 0 claiming: free RAM {free:.1f}GB at or "
                               f"below floor {floor:.1f}GB — mem-gate is correct, free memory",
                               "free_memory", subject, {"free_ram_gb": free, "ram_floor_gb": floor})
            return Verdict(SUSPECT,
                           f"{claimable} claimable but 0 claiming with no RAM or lane cause found",
                           "investigate", subject, {"claimable": claimable})
        return Verdict(HEALTHY, "", "", subject, {"claimable": claimable, "claiming": claiming})
    except Exception:
        return Verdict(HEALTHY, "", "", "capacity:?", {})


def evaluate_release_gate(gate) -> Verdict:
    """Diagnosis (6). Holding a batch is allowed; holding it SILENTLY or FOREVER is not."""
    try:
        pending = int(_num(getattr(gate, "pending", 0)))
        min_batch = int(_num(getattr(gate, "min_batch", RELEASE_MIN_BATCH), RELEASE_MIN_BATCH))
        age = _num(getattr(gate, "max_hold_s", RELEASE_MAX_HOLD_S))
        oldest = _num(getattr(gate, "oldest_pending_age_s", 0.0))
        subject = "release"
        detail = {"pending": pending, "min_batch": min_batch, "oldest_pending_age_s": oldest}
        if pending <= 0:
            return Verdict(HEALTHY, "", "", subject, detail)
        if pending >= max(min_batch, 1):
            return Verdict(RELEASE_OK, f"{pending} pending >= min batch {min_batch}", "release",
                           subject, detail)
        if oldest >= age:
            return Verdict(RELEASE_OK,
                           f"{pending} pending below min batch {min_batch} but oldest has waited "
                           f"{int(oldest)}s (>= {int(age)}s) — age overrides the floor",
                           "release", subject, detail)
        return Verdict(HELD,
                       f"{pending} pending below min batch {min_batch}; oldest waited {int(oldest)}s "
                       f"of {int(age)}s before the age override fires",
                       "report", subject, detail)
    except Exception:
        return Verdict(HEALTHY, "", "", "release", {})


def classify_route(quality, min_samples=None, min_merge_rate=None) -> Verdict:
    """Diagnosis (7). Demote a route only once it has enough evidence to be judged."""
    min_samples = ROUTE_MIN_SAMPLES if min_samples is None else min_samples
    min_merge_rate = ROUTE_MIN_MERGE_RATE if min_merge_rate is None else min_merge_rate
    try:
        route = getattr(quality, "route", "") or "?"
        task_class = getattr(quality, "task_class", "") or "?"
        samples = int(_num(getattr(quality, "samples", 0)))
        merged = int(_num(getattr(quality, "merged", 0)))
        subject = f"route:{route}/{task_class}"
        detail = {"route": route, "task_class": task_class, "samples": samples, "merged": merged}
        if samples < min_samples:
            return Verdict(HEALTHY, "", "", subject, detail)
        rate = merged / samples if samples else 0.0
        detail["merge_rate"] = rate
        if rate < min_merge_rate:
            return Verdict(DEMOTE,
                           f"{route} merged {merged}/{samples} on {task_class} "
                           f"({rate:.0%} < {min_merge_rate:.0%})",
                           "demote_route", subject, detail)
        return Verdict(HEALTHY, "", "", subject, detail)
    except Exception:
        return Verdict(HEALTHY, "", "", "route:?", {})


def sweep(lanes=(), daemons=(), hosts=(), capacity=(), gates=(), routes=()) -> List[Verdict]:
    """Run every classifier and return only the actionable verdicts, newest concern first.

    This is the single entry point the sibling actuators consume; they never re-implement
    thresholds. Fail-soft: a bad element is skipped, not fatal.
    """
    out: List[Verdict] = []
    for items, fn in ((lanes, classify_lane), (daemons, detect_daemon_leak),
                      (hosts, classify_host), (capacity, classify_capacity),
                      (gates, evaluate_release_gate), (routes, classify_route)):
        for item in items or ():
            try:
                verdict = fn(item)
            except Exception:
                continue
            if verdict.actionable:
                out.append(verdict)
    return out


# ── DB migration stub (siblings apply it; this is the agreed shape) ───────────────────────
# One append-only journal so every immune action is auditable and so "it happened silently"
# is impossible by construction. Idempotent, per CLAUDE.md.
FLEET_IMMUNE_EVENT_DDL = """
CREATE TABLE IF NOT EXISTS fleet_immune_event (
  id           bigserial PRIMARY KEY,
  ts           timestamptz NOT NULL DEFAULT now(),
  host         text NOT NULL,
  subject      text NOT NULL,
  state        text NOT NULL,
  action       text NOT NULL DEFAULT '',
  reason       text NOT NULL DEFAULT '',
  detail       jsonb NOT NULL DEFAULT '{}'::jsonb,
  contract_ver text NOT NULL DEFAULT '""" + CONTRACT_VERSION + """'
);
CREATE INDEX IF NOT EXISTS fleet_immune_event_ts_idx ON fleet_immune_event (ts DESC);
CREATE INDEX IF NOT EXISTS fleet_immune_event_host_state_idx ON fleet_immune_event (host, state);
"""


def event_row(verdict, host):
    """Shape a Verdict into a fleet_immune_event row. Never raises."""
    try:
        return {
            "host": host or "",
            "subject": getattr(verdict, "subject", "") or "",
            "state": getattr(verdict, "state", HEALTHY) or HEALTHY,
            "action": getattr(verdict, "action", "") or "",
            "reason": getattr(verdict, "reason", "") or "",
            "detail": getattr(verdict, "detail", {}) or {},
            "contract_ver": CONTRACT_VERSION,
        }
    except Exception:
        return {"host": host or "", "subject": "", "state": HEALTHY, "action": "",
                "reason": "", "detail": {}, "contract_ver": CONTRACT_VERSION}
