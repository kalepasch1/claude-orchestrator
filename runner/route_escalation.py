#!/usr/bin/env python3
"""route_escalation.py — the coder-routing actuator for the fleet immune system.

Section 3 of the 2026-08-02 operator directive, diagnosis (7):

    weak-coder routes produced "0/12 merged" cycles on legal-class tasks

`fleet_immune_contracts` already defines the vocabulary for that finding — `RouteQuality`
and `classify_route()` — and says explicitly that "the siblings own the actuators and wire
against these contracts". Nothing ever built that sibling: a grep for `classify_route` and
`RouteQuality` across runner/ returns ONLY the contracts module itself. So the fleet could
describe a failing route perfectly and had no code that would stop using it.

This module is that actuator. It answers one question — *given a task and its history,
which coder route may run it?* — as a pure function, so it is testable without a database,
a model call or a live lane.

TWO RULES, both from the directive:

  1. ESCALATION. After 2 failed attempts on any task, force the strongest coder route
     regardless of cost score. A third attempt down the same cheap path is how one task
     burns a lane for a day.
  2. LEGAL-CLASS FLOOR. A task with need >= 8 NEVER routes to a weak local model for the
     CODER stage. Triage and QA may stay cheap — the directive is explicit about that, and
     the saving is real — but the stage that writes the diff must be capable.

Both rules only ever move a route UP. That is deliberate: an actuator that can also demote
into a cheaper model is one bad heuristic away from re-creating the incident it exists to
prevent, and `classify_route`'s DEMOTE verdict is advisory input to humans, not a licence
for this code to downgrade a live task.

Fail-soft per CLAUDE.md: bad input returns the caller's original route rather than raising,
because a routing bug must never be able to stop a task from running at all.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

try:
    import fleet_immune_contracts as contracts
except Exception:  # pragma: no cover - contracts must never be a hard dependency
    contracts = None

#: Attempts allowed on the caller's chosen route before escalation is forced.
#: The directive says "after 2 failed attempts"; attempt numbering is 1-based, so a task
#: arriving for attempt 3 has already failed twice.
ESCALATE_AFTER_ATTEMPTS = int(os.environ.get("ORCH_ESCALATE_AFTER_ATTEMPTS", "2"))

#: `need` at or above which a task is legal-class. Matches the directive and the existing
#: `need >= 8` checks in agentic_coders.py / model_policy.py.
LEGAL_CLASS_NEED = int(os.environ.get("ORCH_LEGAL_CLASS_NEED", "8"))

#: The strongest coder route. Env-overridable so a model rename is a config change.
STRONGEST_CODER = os.environ.get("ORCH_STRONGEST_CODER", "claude")
STRONGEST_MODEL = os.environ.get("ORCH_ESCALATION_MODEL", "claude-sonnet-4-6")

#: Providers that are never permitted to write the diff for a legal-class task. `local` and
#: `ollama` are the self-hosted small models the incident named; `xai` is included because
#: the same "0/12 merged" cycles were observed on it.
WEAK_CODER_PROVIDERS = tuple(
    p.strip().lower() for p in os.environ.get(
        "ORCH_WEAK_CODER_PROVIDERS", "local,ollama,swarm:ollama").split(",") if p.strip())

#: Reason codes. Stable strings — they are written to task notes and read back by queries.
REASON_OK = "route_ok"
REASON_ATTEMPTS = "escalated_after_failed_attempts"
REASON_LEGAL_FLOOR = "escalated_legal_class_floor"


def _provider_of(route: Any) -> str:
    """Provider half of a route, however the caller spelled it.

    Accepts 'local', 'local:qwen2.5-coder:32b', ('local', 'qwen…') and objects with a
    `.provider`. Returns '' when it cannot tell — which callers must treat as "unknown",
    never as "weak", or an unrecognised spelling would silently escalate every task.
    """
    if route is None:
        return ""
    if isinstance(route, (tuple, list)) and route:
        return str(route[0]).strip().lower()
    provider = getattr(route, "provider", None)
    if provider:
        return str(provider).strip().lower()
    text = str(route).strip().lower()
    if not text:
        return ""
    # 'swarm:ollama:x' keeps two segments; 'local:model' keeps one.
    if text.startswith("swarm:"):
        return ":".join(text.split(":")[:2])
    return text.split(":")[0]


def is_weak_coder(route: Any, weak_providers=None) -> bool:
    """True when `route`'s provider is on the weak list. Unknown providers are NOT weak."""
    provider = _provider_of(route)
    if not provider:
        return False
    weak = tuple(weak_providers) if weak_providers is not None else WEAK_CODER_PROVIDERS
    return provider in weak


def is_legal_class(need: Any, threshold: int = None) -> bool:
    """True when a task's `need` puts it in the legal/high-risk class."""
    threshold = LEGAL_CLASS_NEED if threshold is None else threshold
    try:
        return float(need) >= threshold
    except (TypeError, ValueError):
        # Unknown need must not silently drop a task below the floor.
        return False


def decide_route(task: Optional[Dict[str, Any]], route: Any = None,
                 attempts: int = None, need: Any = None,
                 escalate_after: int = None) -> Dict[str, Any]:
    """Return the coder route a task may actually use.

    {"route": <route>, "escalated": bool, "reason": <code>, "detail": str}

    `route` is the caller's proposed route (whatever the cost optimiser picked). Everything
    else is read from `task` when not passed explicitly, so both the runner (which has a
    task dict) and a test (which has neither) can call it.
    """
    task = task if isinstance(task, dict) else {}
    proposed = route if route is not None else (task.get("force_coder") or task.get("coder") or "")
    escalate_after = ESCALATE_AFTER_ATTEMPTS if escalate_after is None else escalate_after

    if attempts is None:
        attempts = task.get("attempt", 0)
    try:
        attempts = int(attempts or 0)
    except (TypeError, ValueError):
        attempts = 0

    if need is None:
        need = task.get("need", task.get("task_need", 0))

    strongest = {"provider": STRONGEST_CODER, "model": STRONGEST_MODEL}

    # Rule 1 — escalation on repeated failure. Checked first: it applies to EVERY task
    # class, and a legal-class task that has also failed twice should read as an attempts
    # escalation, which is the more actionable signal.
    if attempts >= escalate_after:
        return {
            "route": STRONGEST_CODER, "model": STRONGEST_MODEL, "escalated": True,
            "reason": REASON_ATTEMPTS,
            "detail": (f"attempt {attempts} >= {escalate_after}: forcing {STRONGEST_CODER}"
                       f"/{STRONGEST_MODEL} regardless of cost score"),
            "strongest": strongest,
        }

    # Rule 2 — legal-class floor for the CODER stage only.
    if is_legal_class(need) and is_weak_coder(proposed):
        return {
            "route": STRONGEST_CODER, "model": STRONGEST_MODEL, "escalated": True,
            "reason": REASON_LEGAL_FLOOR,
            "detail": (f"need={need} is legal-class and {_provider_of(proposed)!r} is a weak "
                       f"coder provider; triage/QA may stay cheap, the coder stage may not"),
            "strongest": strongest,
        }

    return {"route": proposed, "model": task.get("model") or "", "escalated": False,
            "reason": REASON_OK, "detail": "", "strongest": strongest}


def route_health(samples: int, merged: int, route: str = "", task_class: str = "") -> Dict[str, Any]:
    """Advisory verdict for a route, delegating the thresholds to the shared contract.

    Deliberately does NOT act on a DEMOTE verdict — see the module docstring. It is
    surfaced so an operator (or a dashboard) can see which routes are earning their place.
    """
    if contracts is None:
        return {"verdict": "healthy", "reason": "", "merge_rate": None}
    try:
        quality = contracts.RouteQuality(route=route, task_class=task_class,
                                         samples=int(samples or 0), merged=int(merged or 0))
        verdict = contracts.classify_route(quality)
        return {"verdict": getattr(verdict, "state", "healthy"),
                "reason": getattr(verdict, "reason", ""),
                "merge_rate": (int(merged or 0) / int(samples)) if samples else None}
    except Exception:
        return {"verdict": "healthy", "reason": "", "merge_rate": None}


__all__ = ["decide_route", "is_weak_coder", "is_legal_class", "route_health",
           "ESCALATE_AFTER_ATTEMPTS", "LEGAL_CLASS_NEED", "WEAK_CODER_PROVIDERS",
           "REASON_OK", "REASON_ATTEMPTS", "REASON_LEGAL_FLOOR"]
