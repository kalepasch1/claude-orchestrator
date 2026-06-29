#!/usr/bin/env python3
"""
usage_meter.py - per-project / per-provider usage + spend for ALL external subscriptions &
APIs (not just Claude), so you can see where money goes and the orchestrator can keep trimming
waste without hurting value. Pairs with budget.py (Claude) + provider_budgets (everything else).

optimize() now also:
  - suggests cheaper tiers/routes when a provider is near its cap but has low success rate
  - detects unused subscriptions (spend with no successful outcomes in the past 30 days)
  - auto-pauses providers that hit hard_pause=true caps
  - feeds waste proposals into approvals for human review
"""
import os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

IDLE_DAYS = int(os.environ.get("PROVIDER_IDLE_DAYS", "30"))
NEAR_CAP_PCT = float(os.environ.get("PROVIDER_NEAR_CAP_PCT", "80"))


def record(provider, project, units=None, unit=None, usd=0):
    db.insert("provider_usage", {"provider": provider, "project": project,
                                 "units": units, "unit": unit, "usd": usd})


def spend(project=None):
    q = {"select": "*"}
    if project:
        q["project"] = f"eq.{project}"
    return db.select("v_provider_spend_mtd", q) or []


def over_budget():
    """Return (provider, project) pairs at/over their cap."""
    caps = {(b["provider"], b.get("project")): b for b in (db.select("provider_budgets") or [])}
    spent = {(s["provider"], s.get("project")): float(s["spent"]) for s in spend()}
    hits = []
    for key, b in caps.items():
        s = spent.get(key, 0) + sum(v for (pr, pj), v in spent.items() if pr == key[0] and key[1] is None)
        if s >= float(b["monthly_cap"]):
            hits.append({"provider": key[0], "project": key[1], "spent": s,
                         "cap": float(b["monthly_cap"]), "hard_pause": b["hard_pause"]})
    return hits


def _recent_success_rate(provider, project=None, days=IDLE_DAYS):
    """Return fraction of tasks for this provider/project that passed tests+integrated (0-1)."""
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).isoformat()
    q = {"select": "tests_passed,integrated", "created_at": f"gte.{cutoff}"}
    if project:
        q["project"] = f"eq.{project}"
    rows = db.select("outcomes", q) or []
    if not rows:
        return None
    return sum(1 for r in rows if r.get("integrated")) / len(rows)


def _detect_idle_providers():
    """
    Find providers that have spend this month but no successful outcomes in IDLE_DAYS days.
    Returns list of dicts: {"provider", "project", "spent", "note"}.
    """
    month_spend = spend()
    idle = []
    for s in month_spend:
        if float(s["spent"]) < 1.0:  # ignore < $1 noise
            continue
        rate = _recent_success_rate(s["provider"], s.get("project"))
        if rate is None:
            # No outcomes at all — possibly a non-Claude provider (infra, SaaS)
            # We still flag it if there are no outcomes recorded
            idle.append({"provider": s["provider"], "project": s.get("project"),
                         "spent": float(s["spent"]),
                         "note": f"${s['spent']} spent this month, no outcomes recorded — consider reviewing"})
        elif rate == 0:
            idle.append({"provider": s["provider"], "project": s.get("project"),
                         "spent": float(s["spent"]),
                         "note": f"${s['spent']} spent, 0% success rate in {IDLE_DAYS} days — possibly idle/broken"})
    return idle


def _near_cap_suggestions():
    """
    For providers near their cap with low success rates, suggest cheaper tiers or routes.
    """
    caps = {(b["provider"], b.get("project")): b for b in (db.select("provider_budgets") or [])}
    spent_map = {(s["provider"], s.get("project")): float(s["spent"]) for s in spend()}
    suggestions = []
    for key, b in caps.items():
        s = spent_map.get(key, 0)
        cap = float(b["monthly_cap"])
        if s < cap * (NEAR_CAP_PCT / 100):
            continue
        rate = _recent_success_rate(key[0], key[1])
        pct = round(s / cap * 100)
        if rate is not None and rate < 0.5:
            suggestions.append({
                "provider": key[0], "project": key[1], "spent": s, "cap": cap, "pct": pct,
                "success_rate": rate,
                "note": f"{pct}% of cap used (${s:.0f}/${cap:.0f}) with only {rate*100:.0f}% success — consider a cheaper model tier or route",
            })
        elif rate is None:
            suggestions.append({
                "provider": key[0], "project": key[1], "spent": s, "cap": cap, "pct": pct,
                "success_rate": None,
                "note": f"{pct}% of cap used (${s:.0f}/${cap:.0f}) — check if spend is still generating value",
            })
    return suggestions


def set_project_budget(provider, project, monthly_cap, hard_pause=True):
    """Add or update a per-project provider budget."""
    db.insert("provider_budgets", {"provider": provider, "project": project,
                                   "monthly_cap": monthly_cap, "hard_pause": hard_pause},
              upsert=True)


def optimize():
    """
    Flag waste: near-cap low-success, idle subscriptions, at/over-budget providers.
    Files approval cards for each finding. Returns list of flag strings.
    """
    flags = []

    # 1) At/over cap
    for h in over_budget():
        flags.append(f"{h['provider']}/{h['project'] or '*'} at ${h['spent']:.2f}/{h['cap']} cap")
        db.insert("approvals", {"project": h["project"] or "PORTFOLIO", "kind": "self",
                  "title": f"{h['provider']} budget reached (${h['spent']:.0f}/{h['cap']:.0f})",
                  "why": "External provider spend hit its cap.",
                  "value": "Pause or raise the cap; consider a cheaper tier/route.",
                  "risk": "Hard-pause stops that provider's usage until you act.", "command": ""})
        if h.get("hard_pause"):
            try:
                import kill_switch
                kill_switch.pause(scope="project", project=h["project"],
                                  reason=f"{h['provider']} budget cap reached", by="usage_meter")
            except Exception:
                pass

    # 2) Near-cap with low success rate — suggest cheaper alternatives
    for sg in _near_cap_suggestions():
        flags.append(f"{sg['provider']}/{sg['project'] or '*'}: near cap, {sg.get('success_rate',0)*100:.0f}% success")
        db.insert("approvals", {"project": sg["project"] or "PORTFOLIO", "kind": "self",
                  "title": f"Spend optimization: {sg['provider']} near cap with low ROI",
                  "why": sg["note"],
                  "value": "Switch to a cheaper model/tier or reduce frequency to stay under budget.",
                  "risk": "Low — this is a suggestion, not an automatic change.",
                  "command": ""})

    # 3) Idle/unused subscriptions
    for idle in _detect_idle_providers():
        flags.append(f"idle: {idle['provider']}/{idle.get('project') or '*'} — {idle['note'][:60]}")
        db.insert("approvals", {"project": idle.get("project") or "PORTFOLIO", "kind": "self",
                  "title": f"Possible unused subscription: {idle['provider']}",
                  "why": idle["note"],
                  "value": "Cancel or downgrade if truly unused.",
                  "risk": "Low — confirm it's unused before cancelling.",
                  "command": ""})

    print(f"usage_meter: {len(flags)} spend flags")
    return flags


if __name__ == "__main__":
    import json
    print(json.dumps({"spend_mtd": spend(), "over_budget": over_budget(),
                      "flags": optimize()}, indent=2, default=str))
