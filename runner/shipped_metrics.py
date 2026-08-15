#!/usr/bin/env python3
"""
shipped_metrics.py — honest telemetry for owner_goals #2 (weight 1.4):

    "Ship real, tested improvements to production continuously — no credit-burn loops."

There was NO telemetry for this goal. The numbers that existed measured merges, and
merges were not delivery: 9,236 tasks had been bulk-flipped to MERGED, and production
only shipped because Vercel auto-deploys on push.

This module answers one question honestly:

    How many improvements actually reached production, per day, per app?

Rules that keep it honest:
  * Only DEPLOYED_AND_VERIFIED counts as shipped. MERGED does not.
  * Synthetic work never counts: canary-, shadow-, cont-, deployfix-, relfix-,
    recover-missing-branch- and batch-mech tasks are pipeline plumbing, not improvements.
  * Self-work is reported SEPARATELY from user-app work, so 'we shipped a lot' can never
    again mean 'we shipped a lot to ourselves'.
"""
import os
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

SELF_PROJECT = os.environ.get("ORCH_SELF_PROJECT", "beethoven")

# Slug prefixes that are plumbing, not user-visible improvements.
NON_IMPROVEMENT_PREFIXES = (
    "canary-", "shadow-", "cont-", "deployfix-", "relfix-", "release-fix-",
    "recover-missing-branch-", "batch-mech", "rework-", "copyfix-", "smoke-",
)


def is_improvement(slug):
    s = str(slug or "").lower()
    if not s:
        return False
    return not any(s.startswith(p) for p in NON_IMPROVEMENT_PREFIXES)


def _project_names():
    try:
        return {p["id"]: p["name"] for p in (db.select("projects", {"select": "id,name"}) or [])}
    except Exception:
        return {}


def shipped(days=14):
    """Per-day, per-app count of improvements that reached DEPLOYED_AND_VERIFIED."""
    since = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).isoformat()
    names = _project_names()
    try:
        rows = db.select("tasks", {
            "select": "slug,state,project_id,updated_at",
            "state": "eq.DEPLOYED_AND_VERIFIED",
            "updated_at": f"gte.{since}",
            "limit": "5000"}) or []
    except Exception as e:
        print(f"shipped_metrics: query failed ({e})")
        rows = []

    per = {}
    for r in rows:
        if not is_improvement(r.get("slug")):
            continue
        app = names.get(r.get("project_id"), "unknown")
        day = str(r.get("updated_at") or "")[:10]
        key = (day, app)
        per[key] = per.get(key, 0) + 1

    user_total = sum(v for (d, a), v in per.items() if a != SELF_PROJECT)
    self_total = sum(v for (d, a), v in per.items() if a == SELF_PROJECT)
    return {
        "window_days": days,
        "per_day_per_app": [{"day": d, "app": a, "shipped": n}
                            for (d, a), n in sorted(per.items(), reverse=True)],
        "shipped_to_user_apps": user_total,
        "shipped_to_self": self_total,
        "user_app_share": round(user_total / max(1, user_total + self_total), 3),
        "per_day_avg_user_apps": round(user_total / max(1, days), 2),
    }


def targeting(days=7):
    """Of tasks CREATED recently, what share target user apps vs the orchestrator itself?

    This is the counterpart metric: it shows whether the fleet's attention has actually
    inverted, not just its output.
    """
    since = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).isoformat()
    # EXACT counts, not select+len(): PostgREST caps a select at 1000 rows, which silently
    # reported "1000 tasks created / 44% self" no matter the real volume. db.count() uses
    # Prefer: count=exact and returns the true number.
    self_id = ""
    for pid, name in _project_names().items():
        if name == SELF_PROJECT:
            self_id = pid
            break
    try:
        total = db.count("tasks", {"created_at": f"gte.{since}"})
    except Exception:
        total = 0
    self_n = 0
    if self_id:
        try:
            self_n = db.count("tasks", {"created_at": f"gte.{since}",
                                        "project_id": f"eq.{self_id}"})
        except Exception:
            self_n = 0
    return {"window_days": days, "created_total": total,
            "targeting_self": self_n, "targeting_user_apps": total - self_n,
            "self_share": round(self_n / max(1, total), 3)}


def run():
    s = shipped()
    t = targeting()
    print(f"shipped_metrics: last {s['window_days']}d — "
          f"{s['shipped_to_user_apps']} improvements shipped to USER APPS "
          f"({s['per_day_avg_user_apps']}/day), {s['shipped_to_self']} to {SELF_PROJECT}; "
          f"user-app share {s['user_app_share']:.0%}")
    print(f"shipped_metrics: last {t['window_days']}d — {t['created_total']} tasks created, "
          f"{t['self_share']:.0%} targeting {SELF_PROJECT}")
    for row in s["per_day_per_app"][:20]:
        print(f"  {row['day']}  {row['app']:<32} {row['shipped']}")
    # Persist so the owner report / dashboard can read a single honest number.
    _val = (f"{s['per_day_avg_user_apps']}/day to user apps over {s['window_days']}d; "
            f"user-app share {s['user_app_share']:.0%}; "
            f"self-targeted task share {t['self_share']:.0%}")[:500]
    try:
        # Dedicated table rather than fleet_config: fleet_config writes go through the policy
        # gateway (fleet_config_guard), which this read-only metric has no business bypassing.
        db.insert("shipped_telemetry", {
            "window_days": s["window_days"],
            "shipped_to_user_apps": s["shipped_to_user_apps"],
            "shipped_to_self": s["shipped_to_self"],
            "user_app_share": s["user_app_share"],
            "per_day_avg_user_apps": s["per_day_avg_user_apps"],
            "created_total": t["created_total"],
            "targeting_self": t["targeting_self"],
            "self_share": t["self_share"],
            "detail": {"summary": _val, "per_day_per_app": s["per_day_per_app"][:60]},
        })
    except Exception as e:
        print(f"shipped_metrics: could not persist ({e})")
    return {"shipped": s, "targeting": t}


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, default=str))
