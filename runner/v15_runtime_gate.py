#!/usr/bin/env python3
"""Canary-gated consumption of the V15 runtime inside the orchestrator.

The orchestrator is the one app that does not need an adapter to *reach* the
runtime -- ``hivemind_v15`` is right here.  What it needs is the discipline
around calling it, and that discipline is the whole content of this module:

* **Legacy behaviour when disabled, proven rather than asserted.**  With every
  flag off, :func:`gated` returns exactly what the legacy callable returns,
  having called it once and never touched the V15 path.  That is the property
  the rollout is judged on.
* **No second scheduler.**  Flags are read through ``fleet_control`` (the same
  ``ORCH_*`` keys ``load_config`` already applies) and failures go through the
  existing ``circuit_breaker``.  This module owns no loop and no deploy step.
* **Queue invariants are not negotiable.**  :func:`observe_task_gated` is a
  read-only learning hook: it may never mutate, claim, reorder or drop a task,
  and it contains its own failures so a learning bug cannot wedge intake.
* **Single-instance protection is preserved.**  The runtime is a process-local
  singleton; :func:`assert_single_instance` lets a caller confirm it is talking
  to one instance rather than accidentally constructing a second.

Fail-soft is deliberate throughout: every V15 path here is an OPTIONAL
enhancement to a working system, so an error in it must degrade to legacy
behaviour rather than propagate.  Each fallback increments a counter, because a
silent swallow is the defect this repo's own conventions call out.
"""
from __future__ import annotations

import os
import threading
from collections import Counter
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

try:  # pragma: no cover - import shape depends on caller
    import fleet_control
except ImportError:  # pragma: no cover
    fleet_control = None  # type: ignore

try:  # pragma: no cover
    import circuit_breaker
except ImportError:  # pragma: no cover
    circuit_breaker = None  # type: ignore

try:  # pragma: no cover
    import hivemind_v15
except ImportError:  # pragma: no cover
    hivemind_v15 = None  # type: ignore


#: The ten capabilities, named as the fleet manifest names them.
CAPABILITIES: Tuple[str, ...] = (
    "speculative_chains",
    "holographic_retrieval",
    "spike_attention_budget",
    "topology_distillation",
    "curriculum_error_correction",
    "zero_copy_federation",
    "causal_attention",
    "metabolic_budget",
    "anomaly_curriculum",
    "query_topologies",
)

TRUTHY = frozenset({"on", "true", "1", "enabled", "canary"})

metrics: Counter = Counter()
_lock = threading.Lock()


def flag_key(capability: str, project: Optional[str] = None) -> str:
    """ORCH_-prefixed flag key, optionally scoped to one project."""
    slug = "".join(ch if ch.isalnum() else "_" for ch in capability).upper().strip("_")
    if not project:
        return f"ORCH_V15_{slug}"
    proj = "".join(ch if ch.isalnum() else "_" for ch in project).upper().strip("_")
    return f"ORCH_V15_{slug}_{proj}"


def _read_flag(key: str) -> str:
    """Read through fleet_control when available, else the process env.

    ``fleet_control.get_fleet_config`` prepends ORCH_, so it is handed the
    remainder.  Falling back to ``os.environ`` keeps unit tests and any
    non-fleet process working without introducing a second configuration
    system.
    """
    if fleet_control is not None and key.upper().startswith("ORCH_"):
        try:
            value = fleet_control.get_fleet_config(key[len("ORCH_"):], "")
            if value:
                return str(value).strip().lower()
        except Exception:
            metrics["flag:fleet_control_error"] += 1
    return str(os.environ.get(key, "")).strip().lower()


def is_enabled(capability: str, project: Optional[str] = None) -> bool:
    """Default OFF.  An unrecognised value is OFF, never a soft yes."""
    if capability not in CAPABILITIES:
        return False
    if project:
        scoped = _read_flag(flag_key(capability, project))
        if scoped:
            return scoped in TRUTHY
    return _read_flag(flag_key(capability)) in TRUTHY


def status(project: Optional[str] = None) -> Dict[str, bool]:
    return {c: is_enabled(c, project) for c in CAPABILITIES}


def any_enabled(project: Optional[str] = None) -> bool:
    return any(status(project).values())


def gated(capability: str, project: str, legacy: Callable[[], Any],
          v15: Optional[Callable[[], Any]] = None) -> Any:
    """Run the V15 path only when flagged on; otherwise legacy, untouched.

    A V15 path that raises falls back to legacy.  A canary that can turn a
    working orchestrator call into an exception is not a canary, it is an
    outage with a flag on it.
    """
    if v15 is None or not is_enabled(capability, project):
        with _lock:
            metrics[f"{capability}:legacy"] += 1
        return legacy()

    with _lock:
        metrics[f"{capability}:v15"] += 1
    try:
        if circuit_breaker is not None:
            return circuit_breaker.wrap(f"v15:{capability}", v15, fallback=legacy)()
        return v15()
    except Exception:
        with _lock:
            metrics[f"{capability}:fallback"] += 1
        return legacy()


# -- queue-safe learning hook -------------------------------------------
def observe_task_gated(task: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """Read-only intake hook.

    Returns None when disabled or on any failure.  It never mutates the task,
    and callers must not branch queue behaviour on its result -- a learning
    hook that can change what gets claimed is a queue bug waiting to happen.
    """
    project = str(task.get("project") or task.get("project_name") or "orchestrator")
    if not is_enabled("query_topologies", project):
        with _lock:
            metrics["observe:skipped"] += 1
        return None
    if hivemind_v15 is None:
        with _lock:
            metrics["observe:unavailable"] += 1
        return None
    try:
        snapshot = dict(task)          # never hand the live row to the runtime
        result = hivemind_v15.observe_task(snapshot)
        with _lock:
            metrics["observe:ok"] += 1
        return result
    except Exception:
        # Fail-soft with a COUNTER rather than a silent pass: intake must not
        # wedge because a learning hook broke, but the breakage stays visible.
        with _lock:
            metrics["observe:error"] += 1
        return None


# -- single-instance protection -----------------------------------------
def runtime_fingerprint() -> Optional[int]:
    """Identity of the process-local runtime singleton, or None if absent."""
    if hivemind_v15 is None:
        return None
    try:
        return id(hivemind_v15.runtime())
    except Exception:
        return None


def assert_single_instance() -> bool:
    """True when repeated calls resolve to the SAME runtime object."""
    first = runtime_fingerprint()
    if first is None:
        return False
    return first == runtime_fingerprint()


# -- rollout reporting ---------------------------------------------------
def rollback_plan(capability: str, project: Optional[str] = None) -> Dict[str, Any]:
    """The exact config write that disables a capability.  Returned, not applied."""
    if capability not in CAPABILITIES:
        raise KeyError(capability)
    return {
        "capability": capability,
        "project": project,
        "set": {flag_key(capability, project): "off"},
        "breaker": f"v15:{capability}",
        "note": "apply via the existing fleet_config push; this module owns no deploy path",
    }


def report(project: Optional[str] = None) -> Dict[str, Any]:
    with _lock:
        counters = dict(metrics)
    enabled = status(project)
    return {
        "capabilities": len(CAPABILITIES),
        "enabled": sorted(c for c, on in enabled.items() if on),
        "disabled": sorted(c for c, on in enabled.items() if not on),
        "counters": counters,
        "single_instance": assert_single_instance(),
    }


def reset_metrics() -> None:
    with _lock:
        metrics.clear()
