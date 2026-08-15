#!/usr/bin/env python3
"""One switch that stops the fleet writing anywhere shared, and records what it would have done.

WHY THIS EXISTS (2026-08-15)
----------------------------
Bear's position, in his words: he cannot trust the orchestrator, and it has delayed product
launches by two months. The right response to "I don't trust it" is not another fix — it is to
let the thing run beside a process he DOES trust and prove itself on the record, without being
able to damage anything while it does.

That was already possible in principle: set ORCH_PUSH_ON_MERGE=false and ORCH_PUSH_ON_DEV_MERGE
=false and ORCH_AUTO_MERGE_APPROVALS=false and add the merge/release jobs to ORCH_DISABLED_JOBS,
and hope all four stay in sync across two hosts, a .env, and a fleet_config table that outranks
it. Four switches that must all be right is not a safety property anyone can verify at a glance,
and this codebase has already been bitten by exactly that (a pin that silently did not apply
because the runner inherited a stale value from its parent shell).

So: ONE switch. ORCH_SHADOW_MODE=true and no shared ref moves, full stop.

WHAT SHADOW MODE IS NOT
-----------------------
It is not "off". Ingest, planning, drafting, testing, verification and card-filing all continue,
because the point is to see what the orchestrator WOULD do. Every refused action is written to
orch_shadow_intents with the project, the slug and the exact operation, so the proposals can be
read back and compared against what the manual process actually did. Trust should be rebuilt
from that comparison, not from an assurance.

USE
    if shadow_mode.refuse("push", project=pname, subject=slug, detail=f"{base} -> origin"):
        return "shadow"
"""

from __future__ import annotations

import os
import sys

_LOGGED = []


def active() -> bool:
    """True when shared-ref writes are forbidden. Defaults to OFF, so this changes nothing
    until someone deliberately turns it on."""
    return os.environ.get("ORCH_SHADOW_MODE", "false").strip().lower() in ("1", "true", "yes", "on")


def refuse(action: str, project: str = "", subject: str = "", detail: str = "") -> bool:
    """False when writes are permitted. True when shadow mode blocked this action.

    Recording is best-effort and must never be the reason a pass fails — a shadow run that
    crashes on its own bookkeeping teaches nothing about whether the orchestrator is
    trustworthy.
    """
    if not active():
        return False
    line = f"[shadow] REFUSED {action} project={project or '-'} subject={subject or '-'} {detail}".rstrip()
    print(line, flush=True)
    _LOGGED.append(line)
    try:
        import db
        db.insert("orch_shadow_intents", {
            "action": str(action)[:60],
            "project": str(project)[:80] or None,
            "subject": str(subject)[:200] or None,
            "detail": str(detail)[:500] or None,
        })
    except Exception as exc:
        sys.stderr.write(f"[shadow] intent not persisted ({exc}); it is still in the log\n")
    return True


def intents():
    """Everything this process would have done. Useful in tests and at end-of-pass."""
    return list(_LOGGED)
