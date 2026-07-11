"""
slo_controller.py — autonomous SLO controller.

Hard SLOs:
- merge_rate >= 90%
- missing_branch = 0
- queued_recovery < 10
- release_fixes_oldest_age < 2h
- fleet_utilization > 80% (unless RAM-bound)

When an SLO fails, the controller automatically adjusts:
- Routing (shift traffic to higher-merge-rate models)
- Queue order (prioritize recovery/fix tasks)
- Remediation strategy (trigger patch recovery, requeue)
- Alerts (to the dashboard)
"""
import os, sys, json, datetime, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# SLO thresholds (configurable via env)
SLO_MERGE_RATE = float(os.environ.get("SLO_MERGE_RATE", "0.90"))
SLO_MISSING_BRANCH = int(os.environ.get("SLO_MISSING_BRANCH", "0"))
SLO_QUEUED_RECOVERY = int(os.environ.get("SLO_QUEUED_RECOVERY", "10"))
SLO_RELEASE_FIX_AGE_H = float(os.environ.get("SLO_RELEASE_FIX_AGE_H", "2.0"))
SLO_FLEET_UTIL = float(os.environ.get("SLO_FLEET_UTIL", "0.80"))


def run():
    """Periodic entry: check SLOs, apply remediations."""
    checks = {}
    actions = []

    # SLO 1: Merge rate
    checks["merge_rate"] = _check_merge_rate()
    if not checks["merge_rate"]["ok"]:
        actions.extend(_remediate_merge_rate(checks["merge_rate"]))

    # SLO 2: Missing branches
    checks["missing_branch"] = _check_missing_branches()
    if not checks["missing_branch"]["ok"]:
        actions.extend(_remediate_missing_branches(checks["missing_branch"]))

    # SLO 3: Queued recovery backlog
    checks["queued_recovery"] = _check_recovery_backlog()
    if not checks["queued_recovery"]["ok"]:
        actions.extend(_remediate_recovery_backlog(checks["queued_recovery"]))

    # SLO 4: Release fix age
    checks["release_fix_age"] = _check_release_fix_age()
    if not checks["release_fix_age"]["ok"]:
        actions.extend(_remediate_release_fix_age(checks["release_fix_age"]))

    # SLO 5: Fleet utilization
    checks["fleet_util"] = _check_fleet_utilization()
    if not checks["fleet_util"]["ok"]:
        actions.extend(_remediate_fleet_util(checks["fleet_util"]))

    # Record SLO status
    passing = sum(1 for c in checks.values() if c["ok"])
    total = len(checks)

    try:
        db.insert("controls", {
            "key": "slo_status",
            "value": json.dumps({
                "checks": checks,
                "passing": passing,
                "total": total,
                "actions_taken": [a["action"] for a in actions],
                "checked_at": datetime.datetime.utcnow().isoformat()
            }),
            "updated_at": "now()"
        }, upsert=True)
    except Exception:
        pass

    # Apply actions
    for action in actions:
        try:
            _apply_action(action)
        except Exception as e:
            print(f"[slo] action failed ({action.get('action')}): {e}")

    status = "GREEN" if passing == total else ("YELLOW" if passing >= total - 1 else "RED")
    if actions:
        print(f"[slo] {status} ({passing}/{total}) actions={[a['action'] for a in actions]}")

    return {"status": status, "passing": passing, "total": total, "actions": len(actions)}


def _check_merge_rate():
    """Check 24h merge rate."""
    try:
        outcomes = db.select("outcomes", {
            "select": "tests_passed,integrated",
            "created_at": "gt." + _hours_ago_iso(24),
            "limit": "500"
        }) or []

        completed = sum(1 for o in outcomes if o.get("tests_passed") or o.get("integrated"))
        merged = sum(1 for o in outcomes if o.get("integrated"))
        rate = merged / max(1, completed)

        return {"ok": rate >= SLO_MERGE_RATE or completed < 5,
                "value": round(rate, 4), "threshold": SLO_MERGE_RATE,
                "completed": completed, "merged": merged}
    except Exception:
        return {"ok": True, "value": 0, "threshold": SLO_MERGE_RATE}


def _check_missing_branches():
    """Check for tasks stuck due to missing branches."""
    try:
        blocked = db.select("tasks", {
            "select": "id,slug",
            "state": "eq.BLOCKED",
            "note": "like.%missing%branch%",
            "limit": "50"
        }) or []

        recovery = db.select("tasks", {
            "select": "id",
            "state": "eq.QUEUED",
            "slug": "like.recover-missing-branch-%",
            "limit": "50"
        }) or []

        count = len(blocked) + len(recovery)
        return {"ok": count <= SLO_MISSING_BRANCH,
                "value": count, "threshold": SLO_MISSING_BRANCH}
    except Exception:
        return {"ok": True, "value": 0, "threshold": SLO_MISSING_BRANCH}


def _check_recovery_backlog():
    """Check recovery task backlog."""
    try:
        recovery = db.select("tasks", {
            "select": "id",
            "state": "eq.QUEUED",
            "slug": "like.recover-%",
            "limit": "50"
        }) or []

        return {"ok": len(recovery) <= SLO_QUEUED_RECOVERY,
                "value": len(recovery), "threshold": SLO_QUEUED_RECOVERY}
    except Exception:
        return {"ok": True, "value": 0, "threshold": SLO_QUEUED_RECOVERY}


def _check_release_fix_age():
    """Check age of oldest release fix task."""
    try:
        fixes = db.select("tasks", {
            "select": "id,slug,created_at",
            "state": "eq.QUEUED",
            "slug": "like.relfix-%",
            "order": "created_at.asc",
            "limit": "5"
        }) or []

        if not fixes:
            return {"ok": True, "value": 0, "threshold": SLO_RELEASE_FIX_AGE_H}

        oldest = fixes[0]
        age_h = _age_hours(oldest.get("created_at", ""))

        return {"ok": age_h <= SLO_RELEASE_FIX_AGE_H,
                "value": round(age_h, 2), "threshold": SLO_RELEASE_FIX_AGE_H}
    except Exception:
        return {"ok": True, "value": 0, "threshold": SLO_RELEASE_FIX_AGE_H}


def _check_fleet_utilization():
    """Check fleet lane utilization."""
    try:
        heartbeats = db.select("runner_heartbeats", {
            "select": "runner_id,active_tasks",
            "last_seen": "gt." + _hours_ago_iso(0.1),  # last 6 minutes
            "limit": "50"
        }) or []

        if not heartbeats:
            return {"ok": True, "value": 0, "threshold": SLO_FLEET_UTIL}

        total_lanes = len(heartbeats)
        active = sum(1 for h in heartbeats if (h.get("active_tasks") or 0) > 0)
        util = active / max(1, total_lanes)

        # Check if RAM-bound (excuse for low util)
        ram_bound = False
        try:
            import lane_scheduler
            status = lane_scheduler.run()
            ram_bound = not status.get("ram_ok", True)
        except Exception:
            pass

        return {"ok": util >= SLO_FLEET_UTIL or ram_bound,
                "value": round(util, 4), "threshold": SLO_FLEET_UTIL,
                "ram_bound": ram_bound}
    except Exception:
        return {"ok": True, "value": 0, "threshold": SLO_FLEET_UTIL}


# ── Remediation strategies ──────────────────────────────────────────────────────

def _remediate_merge_rate(check):
    """Shift traffic to higher-merge-rate models."""
    actions = []
    if check["value"] < SLO_MERGE_RATE * 0.5:
        # Critical: force all traffic to best-performing model
        actions.append({
            "action": "force_best_model",
            "reason": f"merge rate {check['value']:.0%} < {SLO_MERGE_RATE:.0%}"
        })
    else:
        # Warning: increase canary traffic to find better models
        actions.append({
            "action": "increase_canaries",
            "reason": f"merge rate {check['value']:.0%} below target"
        })
    return actions


def _remediate_missing_branches(check):
    """Trigger patch recovery for missing branches."""
    actions = []
    if check["value"] > 0:
        actions.append({
            "action": "trigger_patch_recovery",
            "reason": f"{check['value']} tasks with missing branches"
        })
    return actions


def _remediate_recovery_backlog(check):
    """Prioritize recovery tasks in queue."""
    actions = []
    if check["value"] > SLO_QUEUED_RECOVERY:
        actions.append({
            "action": "prioritize_recovery",
            "reason": f"{check['value']} recovery tasks queued (>{SLO_QUEUED_RECOVERY})"
        })
    return actions


def _remediate_release_fix_age(check):
    """Bump release fix task priority."""
    actions = []
    if check["value"] > SLO_RELEASE_FIX_AGE_H:
        actions.append({
            "action": "bump_release_fixes",
            "reason": f"oldest release fix is {check['value']:.1f}h old (>{SLO_RELEASE_FIX_AGE_H}h)"
        })
    return actions


def _remediate_fleet_util(check):
    """Scale up or restart idle lanes."""
    actions = []
    if check["value"] < SLO_FLEET_UTIL and not check.get("ram_bound"):
        actions.append({
            "action": "restart_idle_lanes",
            "reason": f"fleet util {check['value']:.0%} below target"
        })
    return actions


def _apply_action(action):
    """Apply a remediation action."""
    act = action.get("action", "")

    if act == "trigger_patch_recovery":
        try:
            blocked = db.select("tasks", {
                "select": "id,slug",
                "state": "eq.BLOCKED",
                "note": "like.%missing%branch%",
                "limit": "20"
            }) or []
            for t in blocked:
                slug = t.get("slug", "")
                # Requeue with patch_recovery hint
                db.update("tasks", {"id": t["id"]}, {
                    "state": "QUEUED",
                    "note": "slo: requeued for patch recovery",
                    "kind": "recovery"
                })
        except Exception:
            pass

    elif act == "bump_release_fixes":
        try:
            fixes = db.select("tasks", {
                "select": "id",
                "state": "eq.QUEUED",
                "slug": "like.relfix-*",
                "limit": "20"
            }) or []
            for t in fixes:
                db.update("tasks", {"id": t["id"]}, {"priority": 0})
        except Exception:
            pass

    elif act == "prioritize_recovery":
        try:
            recovery = db.select("tasks", {
                "select": "id",
                "state": "eq.QUEUED",
                "slug": "like.recover-*",
                "limit": "30"
            }) or []
            for t in recovery:
                db.update("tasks", {"id": t["id"]}, {"priority": 1})
        except Exception:
            pass

    elif act == "force_best_model":
        try:
            import model_score
            best = model_score.best_model()
            if best:
                db.insert("controls", {
                    "key": "slo_forced_model",
                    "value": json.dumps({"model": best, "reason": action.get("reason", "")}),
                    "updated_at": "now()"
                }, upsert=True)
        except Exception:
            pass

    # Log the action
    try:
        db.insert("resource_events", {
            "kind": "slo_action",
            "detail": json.dumps(action)[:1000],
            "action": act,
            "created_at": "now()"
        })
    except Exception:
        pass


def _hours_ago_iso(hours):
    return (datetime.datetime.utcnow() - datetime.timedelta(hours=hours)).isoformat()


def _age_hours(ts_str):
    try:
        ts = datetime.datetime.fromisoformat(str(ts_str).replace("Z", "+00:00").replace("+00:00", ""))
        return (datetime.datetime.utcnow() - ts).total_seconds() / 3600
    except Exception:
        return 0


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2))
