#!/usr/bin/env python3
"""
approval_workflow.py – Approval workflow manager for the monitoring dashboard.

Manages human-in-the-loop approval flows: submit changes for review, track
approval state, auto-escalate stale approvals, and record decisions for audit.

Conventions: module-level singleton, fail-soft, ORCH_ env vars, thread-safe.
"""
import os, sys, json, datetime, threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ESCALATION_HOURS = int(os.environ.get("ORCH_APPROVAL_ESCALATE_HOURS", "4"))
MAX_PENDING = int(os.environ.get("ORCH_MAX_PENDING_APPROVALS", "50"))

_lock = threading.Lock()
_STATE = {
    "pending": [],
    "decided": 0,
    "escalated": 0,
    "last_check": None,
}


def submit_for_approval(slug, change_type, detail, requester=None):
    """
    Submit a change for human approval.

    Returns approval request dict with tracking ID.
    """
    now = datetime.datetime.utcnow().isoformat() + "Z"
    request = {
        "slug": slug,
        "change_type": change_type,
        "detail": detail[:500] if detail else "",
        "requester": requester or "system",
        "submitted_at": now,
        "state": "pending",
        "decision": None,
        "decided_at": None,
        "decided_by": None,
    }

    try:
        import db
        db.insert("inbox", {
            "kind": "approval_request",
            "title": f"Approval needed: {change_type} for {slug}",
            "body": json.dumps(request, indent=2)[:3000],
            "created_at": now,
        })
    except Exception:
        pass

    with _lock:
        _STATE["pending"].append(request)
        if len(_STATE["pending"]) > MAX_PENDING:
            _STATE["pending"] = _STATE["pending"][-MAX_PENDING:]

    return request


def record_decision(slug, approved, decided_by=None, reason=None):
    """Record an approval/rejection decision."""
    now = datetime.datetime.utcnow().isoformat() + "Z"
    decision = {
        "slug": slug,
        "approved": approved,
        "decided_by": decided_by or "human",
        "reason": reason,
        "decided_at": now,
    }

    with _lock:
        _STATE["pending"] = [p for p in _STATE["pending"] if p["slug"] != slug]
        _STATE["decided"] += 1

    try:
        import db
        db.insert("inbox", {
            "kind": "approval_decision",
            "title": f"{'Approved' if approved else 'Rejected'}: {slug}",
            "body": json.dumps(decision, indent=2)[:3000],
            "created_at": now,
        })
    except Exception:
        pass

    return decision


def check_escalations():
    """Find and escalate stale pending approvals."""
    now = datetime.datetime.utcnow()
    escalated = []

    with _lock:
        for req in _STATE["pending"]:
            try:
                submitted = datetime.datetime.fromisoformat(
                    req["submitted_at"].rstrip("Z")
                )
                age_hours = (now - submitted).total_seconds() / 3600
                if age_hours > ESCALATION_HOURS and req.get("state") != "escalated":
                    req["state"] = "escalated"
                    escalated.append(req)
            except (ValueError, KeyError):
                continue
        _STATE["escalated"] += len(escalated)
        _STATE["last_check"] = now.isoformat() + "Z"

    if escalated:
        try:
            import db
            slugs = [e["slug"] for e in escalated]
            db.insert("inbox", {
                "kind": "approval_escalation",
                "title": f"Escalation: {len(escalated)} approvals stale >{ESCALATION_HOURS}h",
                "body": f"Stale approvals: {', '.join(slugs[:10])}",
                "created_at": datetime.datetime.utcnow().isoformat() + "Z",
            })
        except Exception:
            pass

    return escalated


def pending_summary():
    """Return summary of pending approvals."""
    with _lock:
        return {
            "pending_count": len(_STATE["pending"]),
            "pending": [
                {"slug": p["slug"], "type": p["change_type"],
                 "submitted": p["submitted_at"], "state": p.get("state", "pending")}
                for p in _STATE["pending"]
            ],
            "total_decided": _STATE["decided"],
            "total_escalated": _STATE["escalated"],
        }


def stats():
    with _lock:
        return {
            "pending": len(_STATE["pending"]),
            "decided": _STATE["decided"],
            "escalated": _STATE["escalated"],
            "last_check": _STATE["last_check"],
        }


def run():
    """Entry point for periodic jobs."""
    escalated = check_escalations()
    return {
        "escalated": len(escalated),
        "pending": len(_STATE["pending"]),
    }


if __name__ == "__main__":
    print(json.dumps(pending_summary(), indent=2))
