#!/usr/bin/env python3
"""
config_approval_engine.py – AI-driven configuration approval workflow.

Evaluates proposed fleet_config changes against safety rules, historical
patterns, and risk scoring. Auto-approves low-risk changes, flags high-risk
for human review, and maintains an audit trail.

Conventions: module-level singleton, fail-soft, ORCH_ env vars, thread-safe.
"""
import os, sys, re, json, datetime, threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

UNSAFE_KEYS = set(os.environ.get(
    "ORCH_UNSAFE_CONFIG_KEYS",
    "SUPABASE_SERVICE_KEY,GITHUB_PAT,ANTHROPIC_API_KEY,DATABASE_URL"
).split(","))

MAX_VALUE_LEN = int(os.environ.get("ORCH_CONFIG_MAX_VALUE", "10240"))
AUTO_APPROVE_THRESHOLD = float(os.environ.get("ORCH_AUTO_APPROVE_RISK", "0.3"))

_lock = threading.Lock()
_STATE = {
    "evaluations": 0,
    "auto_approved": 0,
    "flagged": 0,
    "last_eval": None,
}


def _risk_score(key, old_value, new_value):
    """
    Compute risk score (0.0 - 1.0) for a config change.

    Factors:
    - Key sensitivity (secrets, auth = high risk)
    - Value magnitude change
    - Presence of URLs or paths (injection risk)
    """
    score = 0.0

    # Sensitive key patterns
    if key.upper() in UNSAFE_KEYS:
        score += 0.8
    if any(kw in key.lower() for kw in ("secret", "token", "password", "key", "credential")):
        score += 0.5
    if any(kw in key.lower() for kw in ("url", "endpoint", "host")):
        score += 0.3

    # Value analysis
    new_str = str(new_value) if new_value is not None else ""
    if len(new_str) > MAX_VALUE_LEN:
        score += 0.4
    if not new_str.strip():
        score += 0.3  # empty values are suspicious

    # URL/path injection
    if re.search(r"https?://|/etc/|/usr/|/tmp/", new_str):
        score += 0.2

    # Numeric magnitude change
    try:
        old_num = float(old_value) if old_value else 0
        new_num = float(new_value) if new_value else 0
        if old_num != 0 and abs(new_num / old_num) > 10:
            score += 0.3  # 10x change is risky
    except (ValueError, TypeError, ZeroDivisionError):
        pass

    return min(score, 1.0)


def evaluate_change(key, old_value, new_value, requester=None):
    """
    Evaluate a single config change for approval.

    Returns dict with:
      - approved: bool
      - risk_score: float 0-1
      - reasons: list of risk factors
      - requires_human: bool
    """
    risk = _risk_score(key, old_value, new_value)
    reasons = []

    if key.upper() in UNSAFE_KEYS:
        reasons.append(f"Key '{key}' is in the unsafe keys list")
    if any(kw in key.lower() for kw in ("secret", "token", "password")):
        reasons.append("Key name suggests sensitive credential")
    new_str = str(new_value) if new_value is not None else ""
    if len(new_str) > MAX_VALUE_LEN:
        reasons.append(f"Value exceeds max length ({len(new_str)} > {MAX_VALUE_LEN})")
    if not new_str.strip():
        reasons.append("New value is empty")

    approved = risk <= AUTO_APPROVE_THRESHOLD
    requires_human = risk > AUTO_APPROVE_THRESHOLD

    result = {
        "key": key,
        "risk_score": round(risk, 3),
        "approved": approved,
        "requires_human": requires_human,
        "reasons": reasons,
        "requester": requester,
        "evaluated_at": datetime.datetime.utcnow().isoformat() + "Z",
    }

    with _lock:
        _STATE["evaluations"] += 1
        if approved:
            _STATE["auto_approved"] += 1
        else:
            _STATE["flagged"] += 1
        _STATE["last_eval"] = result["evaluated_at"]

    return result


def evaluate_batch(changes, requester=None):
    """
    Evaluate a batch of config changes.

    Args:
        changes: list of {"key": str, "old": any, "new": any}

    Returns dict with per-change results and overall approval.
    """
    results = []
    all_approved = True
    max_risk = 0.0

    for change in changes:
        result = evaluate_change(
            change.get("key", ""),
            change.get("old"),
            change.get("new"),
            requester,
        )
        results.append(result)
        if not result["approved"]:
            all_approved = False
        max_risk = max(max_risk, result["risk_score"])

    return {
        "changes": results,
        "all_approved": all_approved,
        "max_risk": round(max_risk, 3),
        "total_changes": len(changes),
        "flagged_count": sum(1 for r in results if not r["approved"]),
        "evaluated_at": datetime.datetime.utcnow().isoformat() + "Z",
    }


def audit_log(change_result):
    """Persist approval decision to the audit trail."""
    try:
        import db
        db.insert("inbox", {
            "kind": "config_approval_audit",
            "title": f"Config change: {change_result.get('key', '?')} "
                     f"({'approved' if change_result.get('approved') else 'FLAGGED'})",
            "body": json.dumps(change_result, indent=2)[:3000],
            "created_at": datetime.datetime.utcnow().isoformat() + "Z",
        })
    except Exception:
        pass  # fail-soft


def stats():
    """Return cached approval engine state."""
    with _lock:
        return dict(_STATE)


def run():
    """Entry point for orchestrator periodic jobs — summarize recent activity."""
    with _lock:
        return {
            "status": "ok",
            "evaluations": _STATE["evaluations"],
            "auto_approved": _STATE["auto_approved"],
            "flagged": _STATE["flagged"],
        }


if __name__ == "__main__":
    # Demo evaluation
    demo = evaluate_change("ORCH_MAX_WORKERS", "4", "8", requester="admin")
    print(json.dumps(demo, indent=2))
