#!/usr/bin/env python3
"""
cross_portfolio_ab.py — cross-portfolio A/B test compounding.

When one app discovers a winning growth tactic (statistically significant lift),
this module propagates it as an experiment to other apps in the portfolio.

Flow:
  1. find_winning_tactics()  — query growth_distribution_run for proven winners
  2. propagate_tactic()      — create ab_test_framework entries for target apps
  3. cross_pollinate()       — main entry: find winners, fan out to untested apps
  4. stats()                 — module statistics

Feature flag: ORCH_CROSS_PORTFOLIO_AB_ENABLED (default "true")
Fail-soft: every function catches exceptions and returns safe defaults.
"""
import os, sys, json, time, uuid
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

ENABLED = os.environ.get("ORCH_CROSS_PORTFOLIO_AB_ENABLED", "true").lower() == "true"
DEFAULT_MIN_LIFT = float(os.environ.get("ORCH_CROSS_AB_MIN_LIFT", "0.1"))
DEFAULT_MIN_CONFIDENCE = float(os.environ.get("ORCH_CROSS_AB_MIN_CONFIDENCE", "0.95"))

# Internal counters
_counters = {"winners_found": 0, "tactics_propagated": 0, "experiments_created": 0,
             "apps_skipped": 0, "errors": 0}


def find_winning_tactics(min_lift=None, min_confidence=None):
    """Query growth_distribution_run for tactics with statistically significant lifts.

    Returns list of dicts: [{tactic_id, app_id, tactic_name, lift, confidence, params}, ...]
    """
    if not ENABLED:
        return []
    if min_lift is None:
        min_lift = DEFAULT_MIN_LIFT
    if min_confidence is None:
        min_confidence = DEFAULT_MIN_CONFIDENCE
    try:
        rows = db.select("growth_distribution_run", {
            "select": "*",
            "status": "eq.completed",
            "order": "lift.desc",
        }) or []
        winners = []
        for r in rows:
            lift = r.get("lift") or 0
            confidence = r.get("confidence") or 0
            try:
                lift = float(lift)
                confidence = float(confidence)
            except (TypeError, ValueError):
                continue
            if lift >= min_lift and confidence >= min_confidence:
                winners.append({
                    "tactic_id": r.get("id"),
                    "app_id": r.get("app_id"),
                    "tactic_name": r.get("tactic_name") or r.get("name", "unknown"),
                    "lift": lift,
                    "confidence": confidence,
                    "params": r.get("params") or r.get("config") or {},
                })
        _counters["winners_found"] += len(winners)
        return winners
    except Exception as e:
        print(f"cross_portfolio_ab find_winning_tactics error: {e}")
        _counters["errors"] += 1
        return []


def propagate_tactic(tactic, target_app_ids):
    """Create experiment entries in ab_test_framework for each target app.

    Args:
        tactic: dict with tactic_id, tactic_name, lift, confidence, params
        target_app_ids: list of app IDs to propagate to

    Returns list of created experiment IDs.
    """
    if not ENABLED:
        return []
    created = []
    for app_id in target_app_ids:
        try:
            experiment = {
                "app_id": app_id,
                "source_tactic_id": tactic.get("tactic_id"),
                "source_app_id": tactic.get("app_id"),
                "name": f"cross_ab_{tactic.get('tactic_name', 'unknown')}_{app_id}",
                "tactic_name": tactic.get("tactic_name"),
                "status": "pending",
                "params": json.dumps(tactic.get("params", {})) if isinstance(tactic.get("params"), dict) else tactic.get("params", "{}"),
                "expected_lift": tactic.get("lift", 0),
                "origin": "cross_portfolio_ab",
            }
            result = db.insert("ab_test_framework", experiment)
            exp_id = (result[0].get("id") if isinstance(result, list) and result else None)
            created.append(exp_id)
            _counters["experiments_created"] += 1
        except Exception as e:
            print(f"cross_portfolio_ab propagate error app={app_id}: {e}")
            _counters["errors"] += 1
    _counters["tactics_propagated"] += 1 if created else 0
    return created


def _get_all_app_ids():
    """Return set of all app IDs in the portfolio."""
    try:
        rows = db.select("apps", {"select": "id"}) or []
        return {r["id"] for r in rows if r.get("id")}
    except Exception as e:
        print(f"cross_portfolio_ab _get_all_app_ids error: {e}")
        _counters["errors"] += 1
        return set()


def _apps_already_running(tactic_name):
    """Return set of app IDs already running or completed this tactic."""
    try:
        rows = db.select("ab_test_framework", {
            "select": "app_id",
            "tactic_name": f"eq.{tactic_name}",
        }) or []
        return {r["app_id"] for r in rows if r.get("app_id")}
    except Exception as e:
        print(f"cross_portfolio_ab _apps_already_running error: {e}")
        _counters["errors"] += 1
        return set()


def cross_pollinate():
    """Main entry point: find winners, identify apps that haven't tried them, create experiments.

    Returns dict with summary of actions taken.
    """
    if not ENABLED:
        return {"status": "disabled", "winners": 0, "propagated": 0}
    try:
        winners = find_winning_tactics()
        if not winners:
            return {"status": "ok", "winners": 0, "propagated": 0, "detail": "no winners found"}
        all_apps = _get_all_app_ids()
        if not all_apps:
            return {"status": "ok", "winners": len(winners), "propagated": 0, "detail": "no apps"}
        total_propagated = 0
        details = []
        for tactic in winners:
            tactic_name = tactic.get("tactic_name", "unknown")
            source_app = tactic.get("app_id")
            already = _apps_already_running(tactic_name)
            # Exclude the source app and any app already running the tactic
            already.add(source_app)
            targets = [a for a in all_apps if a not in already]
            _counters["apps_skipped"] += len(all_apps) - len(targets) - (1 if source_app in all_apps else 0)
            if not targets:
                details.append({"tactic": tactic_name, "targets": 0, "reason": "all apps covered"})
                continue
            created = propagate_tactic(tactic, targets)
            total_propagated += len(created)
            details.append({"tactic": tactic_name, "targets": len(targets), "created": len(created)})
        return {"status": "ok", "winners": len(winners), "propagated": total_propagated, "details": details}
    except Exception as e:
        print(f"cross_portfolio_ab cross_pollinate error: {e}")
        _counters["errors"] += 1
        return {"status": "error", "error": str(e), "winners": 0, "propagated": 0}


def stats():
    """Module statistics."""
    return {
        "module": "cross_portfolio_ab",
        "enabled": ENABLED,
        "min_lift": DEFAULT_MIN_LIFT,
        "min_confidence": DEFAULT_MIN_CONFIDENCE,
        **_counters,
    }


if __name__ == "__main__":
    print(json.dumps(cross_pollinate(), indent=2))
