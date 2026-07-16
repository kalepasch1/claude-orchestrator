#!/usr/bin/env python3
"""
rca_auto_remediate.py — automated remediation actions based on RCA clusters.

Takes rca_engine.analyze() output and generates concrete remediation tasks
that can be queued for execution. Only safe, reversible actions are automated;
destructive or ambiguous actions produce recommendations for human review.

Env vars:
    ORCH_RCA_REMEDIATE_ENABLED   "true" to enable (default "true")
    ORCH_RCA_REMEDIATE_DRY_RUN   "true" for dry-run mode (default "true")
    ORCH_RCA_REMEDIATE_MAX       max remediations per run (default 5)
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ENABLED = os.environ.get("ORCH_RCA_REMEDIATE_ENABLED", "true").lower() in ("1", "true", "yes")
DRY_RUN = os.environ.get("ORCH_RCA_REMEDIATE_DRY_RUN", "true").lower() in ("1", "true", "yes")
MAX_REMEDIATIONS = int(os.environ.get("ORCH_RCA_REMEDIATE_MAX", "5"))

# Map root cause → safe automated action
_SAFE_ACTIONS = {
    "missing-branch": "requeue_with_recovery",
    "no-op": "mark_done",
    "timeout": "requeue_with_extended_timeout",
    "rate-limited": "requeue_with_cooldown",
}

_HUMAN_REVIEW_ACTIONS = {
    "auth-or-repo-missing": "Verify PAT and repo access manually.",
    "merge-conflict": "Rebase branches and resolve conflicts.",
    "build-failure": "Fix build errors in source code.",
    "test-failure": "Investigate and fix failing tests.",
    "disk-space": "Clean up disk space on fleet machines.",
    "unresolvable-template": "Re-scope task with human guidance.",
}


def _requeue_with_recovery(samples):
    """Requeue missing-branch tasks with recovery directive."""
    actions = []
    for s in samples:
        actions.append({
            "slug": s.get("slug", ""),
            "action": "requeue",
            "params": {"note": "rca-auto: requeue for branch recovery", "state": "QUEUED"},
        })
    return actions


def _mark_done(samples):
    """Mark no-op tasks as DONE."""
    actions = []
    for s in samples:
        actions.append({
            "slug": s.get("slug", ""),
            "action": "mark_done",
            "params": {"note": "rca-auto: no-op confirmed, marking DONE", "state": "DONE"},
        })
    return actions


def _requeue_with_extended_timeout(samples):
    """Requeue timed-out tasks with extended timeout hint."""
    actions = []
    for s in samples:
        actions.append({
            "slug": s.get("slug", ""),
            "action": "requeue",
            "params": {"note": "rca-auto: requeue with extended timeout", "state": "QUEUED"},
        })
    return actions


def _requeue_with_cooldown(samples):
    """Requeue rate-limited tasks with cooldown."""
    actions = []
    for s in samples:
        actions.append({
            "slug": s.get("slug", ""),
            "action": "requeue_delayed",
            "params": {"note": "rca-auto: requeue after cooldown", "state": "QUEUED",
                       "delay_minutes": 30},
        })
    return actions


_ACTION_FNS = {
    "requeue_with_recovery": _requeue_with_recovery,
    "mark_done": _mark_done,
    "requeue_with_extended_timeout": _requeue_with_extended_timeout,
    "requeue_with_cooldown": _requeue_with_cooldown,
}


def generate_remediations(clusters):
    """Generate remediation actions from RCA clusters.

    Returns list of {'root_cause', 'action_type', 'automated', 'actions'|'recommendation'}.
    """
    results = []
    auto_count = 0

    for cluster in clusters:
        rc = cluster.get("root_cause", "unknown")
        samples = cluster.get("samples", [])

        if rc in _SAFE_ACTIONS and auto_count < MAX_REMEDIATIONS:
            action_key = _SAFE_ACTIONS[rc]
            fn = _ACTION_FNS.get(action_key)
            if fn:
                actions = fn(samples)
                results.append({
                    "root_cause": rc,
                    "action_type": action_key,
                    "automated": True,
                    "dry_run": DRY_RUN,
                    "actions": actions,
                    "count": cluster.get("count", 0),
                })
                auto_count += 1
                continue

        # Human review needed
        results.append({
            "root_cause": rc,
            "action_type": "human_review",
            "automated": False,
            "recommendation": _HUMAN_REVIEW_ACTIONS.get(rc, cluster.get("remediation", "Investigate manually.")),
            "count": cluster.get("count", 0),
        })

    return results


def apply_remediations(remediations):
    """Apply automated remediations to the database. Respects DRY_RUN."""
    if not ENABLED:
        return {"applied": 0, "reason": "disabled"}

    applied = 0
    skipped = 0

    for rem in remediations:
        if not rem.get("automated") or DRY_RUN:
            skipped += 1
            continue
        for action in rem.get("actions", []):
            slug = action.get("slug")
            params = action.get("params", {})
            if not slug:
                continue
            try:
                import db
                new_state = params.get("state", "QUEUED")
                note = params.get("note", "rca-auto-remediate")
                db.update("tasks", {"state": new_state, "note": note},
                          {"slug": f"eq.{slug}"})
                applied += 1
            except Exception:
                skipped += 1

    return {"applied": applied, "skipped": skipped, "dry_run": DRY_RUN}


def run():
    """CLI entry point."""
    if not ENABLED:
        print("rca_auto_remediate: disabled")
        return {}
    try:
        import rca_engine
        clusters = rca_engine.analyze()
    except Exception as e:
        print(f"rca_auto_remediate: failed to get clusters: {e}")
        return {}

    remediations = generate_remediations(clusters)
    auto = [r for r in remediations if r.get("automated")]
    manual = [r for r in remediations if not r.get("automated")]
    print(f"rca_auto_remediate: {len(auto)} automated, {len(manual)} need human review")
    if DRY_RUN:
        print("  (dry-run mode — no changes applied)")
    return {"remediations": remediations}


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, default=str))
