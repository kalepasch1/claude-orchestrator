#!/usr/bin/env python3
"""V15 capability manifest bound to the EXISTING fleet-control paths.

The brief is explicit that this must not become a second scheduler or a second
deployment system, so this module deliberately owns no loop, no queue and no
deploy step.  It is a manifest plus the gates around it, and it reaches the
fleet through the machinery that is already there:

* flags come from ``fleet_control.get_fleet_config``, which reads ``ORCH_*``
  keys that ``load_config`` already applied -- so a capability is toggled by the
  same fleet_config push as every other setting;
* breakers are ``circuit_breaker.get`` / ``wrap``, not a new implementation;
* rollout is a cohort *predicate* the existing release train can ask about, not
  a rollout runner.

**Config-key safety.**  Every key here is ``ORCH_``-prefixed and carries only
flags, versions and percentages.  Nothing in this module reads or writes a
credential: the 2026-08-02 plaintext-credential incident is why
``fleet_contracts.is_safe_config_key`` exists, and :func:`capability_flag_key`
is checked against it so a capability can never smuggle a secret-shaped key
into fleet_config.

**Release progression.**  :func:`promotion_decision` advances a stage only on
measured SLO gates -- error rate, p95 latency and a minimum sample count.  A
speed multiplier is explicitly *not* an input, because a capability can be fast
and wrong.
"""
from __future__ import annotations

import hashlib
import json
import statistics
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

try:  # pragma: no cover - import shape depends on caller
    import fleet_control
except ImportError:  # pragma: no cover
    fleet_control = None  # type: ignore

try:  # pragma: no cover
    import circuit_breaker
except ImportError:  # pragma: no cover
    circuit_breaker = None  # type: ignore


MANIFEST_SCHEMA_VERSION = 1


class Stage:
    OFF = "off"
    CANARY = "canary"
    ROLLOUT = "rollout"
    GENERAL = "general"

    ORDER = (OFF, CANARY, ROLLOUT, GENERAL)


class IncompatibleCapability(RuntimeError):
    """The runner cannot satisfy the capability's schema requirement."""


class UnsafeConfigKey(ValueError):
    """A capability tried to use a config key that fleet policy forbids."""


@dataclass(frozen=True)
class Capability:
    """One V15 capability and the contract it needs from the runner."""

    name: str
    version: str
    min_schema: int = 1
    max_schema: int = MANIFEST_SCHEMA_VERSION
    requires_migration: bool = False
    description: str = ""

    def key(self) -> str:
        return capability_flag_key(self.name)

    def supports(self, runner_schema: int) -> bool:
        return self.min_schema <= runner_schema <= self.max_schema


def capability_flag_key(name: str, project: Optional[str] = None) -> str:
    """The ORCH_ key that gates a capability, optionally per project.

    Validated against the fleet's own safe-key predicate so a capability cannot
    introduce a key shaped like a credential.
    """
    slug = "".join(ch if ch.isalnum() else "_" for ch in name).upper().strip("_")
    key = f"ORCH_V15_{slug}" if not project else \
        f"ORCH_V15_{slug}_{''.join(c if c.isalnum() else '_' for c in project).upper()}"
    if not _is_safe(key):
        raise UnsafeConfigKey(f"{key} is not an allowed fleet_config key")
    return key


def _is_safe(key: str) -> bool:
    try:
        import fleet_contracts
        return bool(fleet_contracts.is_safe_config_key(key))
    except Exception:
        # Fail CLOSED in the same shape fleet_control does: no contract module
        # means we trust nothing but the explicit prefix, and reject anything
        # that smells like a credential.
        upper = key.upper()
        if any(m in upper for m in ("TOKEN", "SECRET", "PASSWORD", "KEY_", "_PAT", "CREDENTIAL")):
            return False
        return upper.startswith("ORCH_")


def _flag(key: str, default: str = "") -> str:
    """Read through the EXISTING fleet-control accessor, never a private path."""
    if fleet_control is None:
        return default
    try:
        # get_fleet_config prepends ORCH_, so hand it the un-prefixed remainder.
        return fleet_control.get_fleet_config(key[len("ORCH_"):], default) \
            if key.upper().startswith("ORCH_") else default
    except Exception:
        return default


class Manifest:
    """The registry of V15 capabilities and their per-project rollout state."""

    def __init__(self, runner_schema: int = MANIFEST_SCHEMA_VERSION) -> None:
        self.runner_schema = runner_schema
        self.capabilities: Dict[str, Capability] = {}
        self.telemetry: Dict[str, List[dict]] = {}
        self.metrics: Counter = Counter()
        self._seen_jobs: Dict[str, float] = {}

    # -- registration ----------------------------------------------------
    def register(self, capability: Capability) -> Capability:
        """Register with compatibility negotiation; incompatible is refused."""
        if not capability.supports(self.runner_schema):
            raise IncompatibleCapability(
                f"{capability.name} requires schema {capability.min_schema}.."
                f"{capability.max_schema}; this runner is at {self.runner_schema}")
        capability.key()   # validates the config key up front
        self.capabilities[capability.name] = capability
        self.metrics["registered"] += 1
        return capability

    def negotiate(self, capability: Capability) -> Dict[str, Any]:
        """Report compatibility without raising -- for a dry-run inventory."""
        return {
            "capability": capability.name, "version": capability.version,
            "runner_schema": self.runner_schema,
            "compatible": capability.supports(self.runner_schema),
            "requires_migration": capability.requires_migration,
        }

    def pending_migrations(self) -> List[str]:
        """Capabilities that genuinely need a schema migration, and only those."""
        return sorted(c.name for c in self.capabilities.values() if c.requires_migration)

    # -- flags -----------------------------------------------------------
    def stage(self, name: str, project: Optional[str] = None) -> str:
        """Resolved stage: per-project flag wins, then global, then off."""
        cap = self.capabilities.get(name)
        if cap is None:
            return Stage.OFF
        if project:
            scoped = _flag(capability_flag_key(name, project)).strip().lower()
            if scoped in Stage.ORDER:
                return scoped
        value = _flag(cap.key()).strip().lower()
        return value if value in Stage.ORDER else Stage.OFF

    # -- cohorts ---------------------------------------------------------
    @staticmethod
    def cohort_position(name: str, project: str) -> float:
        """Stable position in [0,1) for a (capability, project) pair.

        Deterministic so a project does not flip in and out of the canary on
        every tick, and salted by capability so one project is not the canary
        for everything at once.
        """
        digest = hashlib.blake2b(f"{name}\x00{project}".encode(), digest_size=8).digest()
        return int.from_bytes(digest, "big") / float(1 << 64)

    def in_canary(self, name: str, project: str, percent: Optional[float] = None) -> bool:
        if percent is None:
            raw = _flag(f"{capability_flag_key(name)}_CANARY_PCT", "0")
            try:
                percent = float(raw)
            except (TypeError, ValueError):
                percent = 0.0
        percent = max(0.0, min(100.0, percent))
        return self.cohort_position(name, project) < (percent / 100.0)

    def enabled_for(self, name: str, project: str,
                    canary_percent: Optional[float] = None) -> bool:
        """The single question the release train should ask."""
        stage = self.stage(name, project)
        if stage == Stage.OFF:
            return False
        if stage == Stage.GENERAL:
            return True
        if stage == Stage.CANARY:
            return self.in_canary(name, project, canary_percent)
        if stage == Stage.ROLLOUT:
            return self.in_canary(name, project,
                                  canary_percent if canary_percent is not None else 50.0)
        return False

    # -- guarded execution ----------------------------------------------
    def run(self, name: str, project: str, fn: Callable[[], Any],
            fallback: Optional[Callable[[], Any]] = None,
            canary_percent: Optional[float] = None) -> Any:
        """Run a capability behind its flag AND the existing circuit breaker."""
        if not self.enabled_for(name, project, canary_percent):
            self.metrics["skipped_disabled"] += 1
            return fallback() if fallback else None
        if circuit_breaker is None:
            return fn()
        self.metrics["guarded_runs"] += 1
        # wrap() returns a CALLABLE, not a result -- calling it here is what
        # actually puts the capability behind the breaker.
        return circuit_breaker.wrap(f"v15:{name}", fn, fallback=fallback)()

    # -- telemetry -------------------------------------------------------
    def record(self, name: str, project: str, ok: bool, latency_s: float,
               at: Optional[float] = None) -> None:
        self.telemetry.setdefault(name, []).append({
            "project": project, "ok": bool(ok), "latency_s": float(latency_s),
            "at": at if at is not None else time.time()})

    def slo(self, name: str) -> Dict[str, Any]:
        rows = self.telemetry.get(name, [])
        if not rows:
            return {"samples": 0, "error_rate": None, "p95_latency_s": None}
        latencies = sorted(r["latency_s"] for r in rows)
        errors = sum(1 for r in rows if not r["ok"])
        return {
            "samples": len(rows),
            "error_rate": errors / len(rows),
            "p95_latency_s": latencies[min(len(latencies) - 1, int(len(latencies) * .95))],
            "mean_latency_s": statistics.fmean(latencies),
            "projects": len({r["project"] for r in rows}),
        }

    # -- release progression --------------------------------------------
    def promotion_decision(self, name: str, max_error_rate: float = .01,
                           max_p95_s: float = 1.0, min_samples: int = 50
                           ) -> Dict[str, Any]:
        """Advance one stage only on measured SLO gates.

        Speed is deliberately not an input: a capability can be fast and wrong,
        and promoting on a headline multiplier is how a regression ships.
        """
        stats = self.slo(name)
        current = self.stage(name)
        reasons: List[str] = []
        if stats["samples"] < min_samples:
            reasons.append(f"insufficient_samples:{stats['samples']}<{min_samples}")
        if stats["error_rate"] is not None and stats["error_rate"] > max_error_rate:
            reasons.append(f"error_rate:{stats['error_rate']:.4f}>{max_error_rate}")
        if stats["p95_latency_s"] is not None and stats["p95_latency_s"] > max_p95_s:
            reasons.append(f"p95_latency:{stats['p95_latency_s']:.3f}>{max_p95_s}")

        idx = Stage.ORDER.index(current) if current in Stage.ORDER else 0
        promote = not reasons and idx < len(Stage.ORDER) - 1
        return {
            "capability": name, "current_stage": current,
            "next_stage": Stage.ORDER[idx + 1] if promote else current,
            "promote": promote, "blockers": reasons, "slo": stats,
            "note": "gated on error rate, p95 latency and sample count; never on a speed multiplier",
        }

    def rollback_plan(self, name: str, project: Optional[str] = None) -> Dict[str, Any]:
        """The exact fleet_config write an operator applies to disable a capability.

        Returned rather than executed: this module does not own the deployment
        path, and pushing config is the release train's job.
        """
        cap = self.capabilities.get(name)
        if cap is None:
            raise KeyError(name)
        key = capability_flag_key(name, project)
        return {"capability": name, "project": project, "set": {key: Stage.OFF},
                "breaker": f"v15:{name}",
                "note": "apply via the existing fleet_config push; no separate deploy path"}

    # -- queue dedupe ----------------------------------------------------
    @staticmethod
    def job_key(name: str, project: str, payload: Any) -> str:
        raw = json.dumps([name, project, payload], sort_keys=True, default=str,
                         separators=(",", ":"))
        return hashlib.blake2b(raw.encode(), digest_size=16).hexdigest()

    def claim_job(self, name: str, project: str, payload: Any,
                  window_s: float = 300.0, now: Optional[float] = None) -> bool:
        """True the first time; False for a duplicate inside the window."""
        now = now if now is not None else time.time()
        key = self.job_key(name, project, payload)
        seen = self._seen_jobs.get(key)
        if seen is not None and (now - seen) < window_s:
            self.metrics["deduped"] += 1
            return False
        self._seen_jobs[key] = now
        self.metrics["claimed"] += 1
        return True


V15_CAPABILITIES: Tuple[Capability, ...] = (
    Capability("speculative_chains", "1.0.0", description="budgeted deterministic speculation"),
    Capability("holographic_memory", "1.0.0", description="versioned fractal keys"),
    Capability("topology_distillation", "1.0.0", description="gated, reversible distillation"),
    Capability("channel_ecc", "1.0.0", description="bounded adaptive redundancy"),
    Capability("zero_copy_federation", "1.0.0", description="leased ring federation"),
    Capability("causal_attention", "1.0.0", description="aligned multi-scale association"),
    Capability("metabolic_budget", "1.0.0", description="hysteresis spike scheduling"),
    Capability("anomaly_curriculum", "1.0.0", description="promote/demote curriculum"),
    Capability("query_topologies", "1.0.0", description="bounded cluster formation"),
)


def default_manifest(runner_schema: int = MANIFEST_SCHEMA_VERSION) -> Manifest:
    manifest = Manifest(runner_schema=runner_schema)
    for capability in V15_CAPABILITIES:
        manifest.register(capability)
    return manifest
