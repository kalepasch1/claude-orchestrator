#!/usr/bin/env python3
"""
illuminati_cothink.py — ONE Illuminati/CADE integration, consumed at FOUR phases.

WHY ONE INTEGRATION AND NOT FOUR
--------------------------------
The review-gate wave wired Illuminati CADE at planning only. Extending it phase
by phase is how the local CADE duplication started drifting in the first place:
each caller grows its own request shape, its own verdict vocabulary, and its own
idea of what "escalate" means, and then the four disagree. So this module owns
the request, the verdict and the escalation, and the four phases differ only by
a `Phase` value:

    intake   — legal framing of the objective
    planning — per-task legal dimension
    build    — the live sidecar: loop-level interception of agent edits
    premerge — final pass gating the release card

committees.py and colosseum.py keep running for NON-legal deliberation. The
legal/compliance dimension routes here. That split is the point: this module
must not grow general-purpose review opinions.

THE ESCALATE PATH IS THE PRODUCT
--------------------------------
An advisory verdict nobody acts on is theatre. `cothink()` therefore does not
just return a verdict — an `escalate` at ANY phase creates the gate appropriate
to that phase (a blocking approval card pre-merge, a steering-visible gate
earlier), and does it through the existing `steering_events` substrate so the
act is attributed rather than anonymous.

NON-ENGINEERS ARE FIRST-CLASS
-----------------------------
Clarification answers, redirects and approval rationales from lawyers, strategy
and finance are recorded as attributed steering_events with their author's own
label, so a lawyer's redirect shapes the build exactly as an engineer's does.
That is the "everyone is an engineer" unlock, and it is one function:
`record_human_input()`.

FAIL-SOFT
---------
Illuminati being unreachable must not wedge the fleet: transport errors yield a
`proceed` verdict marked `degraded=True` with the reason attached, never a
crash and never a silent `escalate` that would halt every build on an outage.
The one thing that is NOT fail-soft is a verdict that did arrive: a real
`escalate` is honoured even if the follow-up gate write fails, and the failure
is reported.
"""
import json
import os
import sys
import threading
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Configuration ───────────────────────────────────────────────────────────

ILLUMINATI_URL = os.environ.get("ORCH_ILLUMINATI_URL", "").rstrip("/")
ILLUMINATI_TIMEOUT = float(os.environ.get("ORCH_ILLUMINATI_TIMEOUT", "20"))
ENABLED = os.environ.get("ORCH_ILLUMINATI_COTHINK", "true").lower() in ("1", "true", "yes", "on")

#: The four phases. A caller that needs a fifth adds it HERE, where all four
#: existing ones see it, rather than inventing a string at a call site.
PHASES = ("intake", "planning", "build", "premerge")

#: Verdicts, narrowest to widest. Anything unrecognised is treated as 'review'
#: rather than 'proceed' — an unparseable answer is not permission.
VERDICTS = ("proceed", "review", "escalate")

_lock = threading.Lock()


def _post(path: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """POST to Illuminati. Raises on transport failure; callers degrade."""
    if not ILLUMINATI_URL:
        raise RuntimeError("ORCH_ILLUMINATI_URL is not configured")
    req = urllib.request.Request(
        f"{ILLUMINATI_URL}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=ILLUMINATI_TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def _normalize(raw: Any, phase: str) -> Dict[str, Any]:
    """Coerce whatever came back into the verdict contract.

    Unknown verdict -> 'review'. Deliberately not 'proceed': a response we
    cannot read is a reason to look, not a reason to ship.
    """
    if not isinstance(raw, dict):
        return {"phase": phase, "verdict": "review", "rationale": "unreadable response",
                "dimensions": [], "degraded": False}
    verdict = str(raw.get("verdict") or "").strip().lower()
    if verdict not in VERDICTS:
        verdict = "review"
    dims = raw.get("dimensions")
    return {
        "phase": phase,
        "verdict": verdict,
        "rationale": str(raw.get("rationale") or "")[:4000],
        "dimensions": list(dims) if isinstance(dims, list) else [],
        "degraded": False,
    }


def _degraded(phase: str, reason: str) -> Dict[str, Any]:
    """The outage verdict: proceed, but say so loudly.

    Returning 'escalate' on an outage would halt every build whenever Illuminati
    hiccups; returning 'proceed' silently would hide that no legal review
    happened. So: proceed, degraded=True, reason attached — and the caller can
    decide, with the fact in hand.
    """
    return {"phase": phase, "verdict": "proceed", "rationale": f"illuminati unavailable: {reason}",
            "dimensions": [], "degraded": True}


def review(phase: str, subject: Dict[str, Any]) -> Dict[str, Any]:
    """Ask Illuminati for the legal/compliance dimension at `phase`.

    Never raises. Returns the verdict contract:
        {phase, verdict, rationale, dimensions, degraded}
    """
    if phase not in PHASES:
        return {"phase": phase, "verdict": "review",
                "rationale": f"unknown phase '{phase}'", "dimensions": [], "degraded": False}
    if not ENABLED:
        return _degraded(phase, "co-think disabled by ORCH_ILLUMINATI_COTHINK")
    try:
        raw = _post("/api/cade/review", {"phase": phase, "subject": subject or {}})
        return _normalize(raw, phase)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError,
            ValueError, RuntimeError) as e:
        return _degraded(phase, str(e)[:200])


# ── Escalation: the part that makes the verdict matter ──────────────────────

def _record_steering(event_type: str, verdict: Dict[str, Any],
                     project: Optional[str], task_id: Optional[str],
                     actor_label: str) -> bool:
    try:
        import steering
        row = steering.record(
            event_type,
            project=project,
            task_id=task_id,
            actor_id="illuminati",
            actor_label=actor_label,
            rationale=verdict.get("rationale"),
            payload={"phase": verdict.get("phase"), "verdict": verdict.get("verdict"),
                     "dimensions": verdict.get("dimensions", []),
                     "degraded": bool(verdict.get("degraded"))},
        )
        return row is not None
    except Exception:  # noqa: BLE001 — steering is fail-soft by contract
        return False


def _open_premerge_card(verdict: Dict[str, Any], project: Optional[str],
                        task_id: Optional[str]) -> Optional[str]:
    """A pre-merge escalate must BLOCK, so it becomes an approval card.

    THIS CARD HAS NEVER BEEN CREATED. The insert named three columns the
    approvals table does not have — `state` (it is `status`), `summary` (it is
    `title`) and `task_id` (there is no such column) — so PostgREST answered 400
    every time, and the bare `except Exception: return None` turned that into an
    ordinary "no card", indistinguishable from a verdict that did not need one.

    That matters more here than in a monitor: this is the blocking path. An
    escalate at pre-merge is supposed to stop the merge behind a human decision,
    and for the life of this function it has instead returned None and let the
    loop continue. The task id now travels in `slug`, which exists and is what
    the rest of the fleet keys cards by.
    """
    try:
        import db
        row = db.insert("approvals", {
            "kind": "legal_gate",
            "project": project,
            "slug": f"illuminati-legal-gate-{task_id}" if task_id else "illuminati-legal-gate",
            "status": "pending",
            "title": f"Illuminati escalate at {verdict.get('phase')}",
            "detail": verdict.get("rationale") or "",
        })
        if isinstance(row, dict):
            return str(row.get("id") or "") or None
        if isinstance(row, list) and row and isinstance(row[0], dict):
            return str(row[0].get("id") or "") or None
        return None
    except Exception as exc:  # noqa: BLE001
        # Fail-soft, but never silent: a blocking gate that could not be opened
        # is the one failure that must not look like "nothing to block".
        sys.stderr.write(f"[illuminati_cothink] BLOCKING approval card could NOT be "
                         f"opened for {project}/{task_id}: {exc}\n")
        return None


def cothink(phase: str, subject: Dict[str, Any], project: Optional[str] = None,
            task_id: Optional[str] = None) -> Dict[str, Any]:
    """Review at `phase` AND apply the consequence of the verdict.

    Returns the verdict plus what was done about it:
        {..., 'gate': {'created': bool, 'kind': str, 'approval_id': str|None,
                       'steering_recorded': bool}}

    proceed  -> nothing created (a degraded proceed still records, so the gap
                in legal coverage is visible afterwards).
    review   -> attributed steering event; build continues.
    escalate -> steering event, and pre-merge additionally opens a BLOCKING
                approval card. Earlier phases do not block the loop; they make
                the objection visible where a human is already looking.
    """
    verdict = review(phase, subject)
    v = verdict["verdict"]
    gate: Dict[str, Any] = {"created": False, "kind": "none",
                            "approval_id": None, "steering_recorded": False}

    if v == "proceed" and not verdict.get("degraded"):
        return {**verdict, "gate": gate}

    if v == "proceed" and verdict.get("degraded"):
        gate["kind"] = "degraded_notice"
        gate["steering_recorded"] = _record_steering(
            "clarification_answer", verdict, project, task_id, "Illuminati (unavailable)")
        gate["created"] = gate["steering_recorded"]
        return {**verdict, "gate": gate}

    with _lock:
        gate["steering_recorded"] = _record_steering(
            "approval_rationale" if v == "escalate" else "clarification_answer",
            verdict, project, task_id, "Illuminati CADE")
        if v == "escalate" and phase == "premerge":
            gate["kind"] = "blocking_card"
            gate["approval_id"] = _open_premerge_card(verdict, project, task_id)
            gate["created"] = gate["approval_id"] is not None
        elif v == "escalate":
            gate["kind"] = "escalation_notice"
            gate["created"] = gate["steering_recorded"]
        else:
            gate["kind"] = "review_notice"
            gate["created"] = gate["steering_recorded"]

    return {**verdict, "gate": gate}


# ── Non-engineer steering, first-class ──────────────────────────────────────

HUMAN_EVENT_TYPES = ("clarification_answer", "redirect", "approval_rationale")


def record_human_input(event_type: str, actor_id: str, actor_label: str,
                       rationale: str, project: Optional[str] = None,
                       task_id: Optional[str] = None,
                       discipline: Optional[str] = None) -> bool:
    """Record a non-engineer's steering act as a first-class attributed event.

    A lawyer's redirect and an engineer's redirect are the same kind of row on
    purpose: if legal input arrived as a comment somewhere it would not shape
    the build, and shaping the build is the entire claim.

    `discipline` ('legal' | 'strategy' | 'finance' | ...) rides in the payload
    so downstream routing can weight by it without parsing the label.
    """
    if event_type not in HUMAN_EVENT_TYPES:
        return False
    if not (actor_id and rationale):
        return False
    try:
        import steering
        row = steering.record(
            event_type, project=project, task_id=task_id,
            actor_id=actor_id, actor_label=actor_label or actor_id,
            rationale=rationale,
            payload={"discipline": discipline or "unspecified", "source": "human"},
        )
        return row is not None
    except Exception:  # noqa: BLE001
        return False


def stats() -> Dict[str, Any]:
    """Observability for operators and tests."""
    return {"enabled": ENABLED, "configured": bool(ILLUMINATI_URL),
            "phases": list(PHASES), "verdicts": list(VERDICTS)}
