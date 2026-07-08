#!/usr/bin/env python3
"""
integrate_kpi.py — per-app integrate-time health, so you can SEE the build self-heal working.

Mirrors release_kpi.py but one stage earlier (integrate() into the staging branch, not release to
prod). For each app over a window it reports:
  * merge_rate   = integrated outcomes / post-QA eligible outcomes (tests_passed or integrated,
                   churn excluded). Failed drafting attempts are tracked as attempt yield, not as
                   mergeable work, so the headline number reflects the integration train.
  * build_fail_open   = tasks currently carrying an unresolved integrate build failure (build_fail_count>0)
  * coder_switched    = tasks escalated to a different coder after repeated red builds (force_coder set)

Writes one KPI heartbeat row (table optional; fail-soft) and prints a per-app line. Pure reads + no
model spend. Schedule every ~30 min. Consumed by Mission Control (v_integrate_kpi / the web card).
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

WINDOW_H = int(os.environ.get("INTEGRATE_KPI_WINDOW_H", "24"))


def _is_churn(slug):
    s = str(slug or "")
    return s.startswith("cont-") or s.startswith("batch-mech")


def compute():
    since = f"now()-interval '{WINDOW_H} hours'"
    # PostgREST can't do now()-interval in a filter param, so pull recent rows and filter in Python.
    import datetime
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(hours=WINDOW_H)).isoformat()
    outs = db.select("outcomes", {"select": "project,slug,tests_passed,integrated,usd,created_at",
                                  "created_at": f"gte.{cutoff}", "limit": "5000"}) or []
    by = {}
    for o in outs:
        if _is_churn(o.get("slug")):
            continue
        p = o.get("project") or "?"
        d = by.setdefault(p, {"completed": 0, "integrated": 0, "attempts": 0, "attempt_integrated": 0, "usd": 0.0})
        d["attempts"] += 1
        d["usd"] += float(o.get("usd") or 0)
        if o.get("integrated"):
            d["attempt_integrated"] += 1
        if not (o.get("tests_passed") or o.get("integrated")):
            continue
        d["completed"] += 1
        if o.get("integrated"):
            d["integrated"] += 1
    # self-heal activity (current, not windowed) — how much the coder-switch is engaging
    heal = {}
    try:
        for t in (db.select("tasks", {"select": "project_id,build_fail_count,force_coder",
                                      "build_fail_count": "gt.0", "limit": "5000"}) or []):
            pid = t.get("project_id")
            h = heal.setdefault(pid, {"build_fail_open": 0, "coder_switched": 0})
            h["build_fail_open"] += 1
            if t.get("force_coder"):
                h["coder_switched"] += 1
    except Exception:
        pass
    pid2name = {}
    try:
        pid2name = {p["id"]: p["name"] for p in (db.select("projects", {"select": "id,name"}) or [])}
    except Exception:
        pass
    out = {}
    for p, d in by.items():
        rate = round(d["integrated"] / d["completed"], 3) if d["completed"] else None
        # NORTH STAR: $ per merged change. Infinite/None when nothing merges — the number to drive down.
        usd_per_merge = round(d["usd"] / d["integrated"], 3) if d["integrated"] else None
        attempt_yield = round(d["attempt_integrated"] / d["attempts"], 3) if d["attempts"] else None
        out[p] = {"completed": d["completed"], "integrated": d["integrated"], "merge_rate": rate,
                  "attempts": d["attempts"], "attempt_yield": attempt_yield,
                  "usd": round(d["usd"], 2), "usd_per_merge": usd_per_merge}
    for pid, h in heal.items():
        nm = pid2name.get(pid, str(pid))
        out.setdefault(nm, {"completed": 0, "integrated": 0, "merge_rate": None,
                            "attempts": 0, "attempt_yield": None})
        out[nm].update(h)
    return out


def run():
    kpi = compute()
    tot_c = sum(v.get("completed", 0) for v in kpi.values())
    tot_i = sum(v.get("integrated", 0) for v in kpi.values())
    tot_usd = sum(v.get("usd", 0) for v in kpi.values())
    tot_attempts = sum(v.get("attempts", 0) for v in kpi.values())
    overall = round(tot_i / tot_c, 3) if tot_c else None
    overall_usd_per_merge = round(tot_usd / tot_i, 3) if tot_i else None
    switched = sum(v.get("coder_switched", 0) for v in kpi.values())
    open_bf = sum(v.get("build_fail_open", 0) for v in kpi.values())
    try:
        db.insert("integrate_kpi", {"overall_merge_rate": overall, "completed": tot_c,
                                    "integrated": tot_i, "coder_switched": switched,
                                    "build_fail_open": open_bf, "usd": round(tot_usd, 2),
                                    "usd_per_merge": overall_usd_per_merge, "by_project": kpi})
    except Exception:
        pass
    print(f"integrate_kpi: post-QA merge_rate {overall} ({tot_i}/{tot_c} eligible, {WINDOW_H}h; "
          f"{tot_attempts} attempts) · "
          f"${overall_usd_per_merge}/merge (north star) · ${round(tot_usd,2)} spent · "
          f"build-fixes open={open_bf}, coder-switched={switched}")
    return {"overall_merge_rate": overall, "completed": tot_c, "integrated": tot_i,
            "usd": round(tot_usd, 2), "usd_per_merge": overall_usd_per_merge,
            "coder_switched": switched, "build_fail_open": open_bf, "by_project": kpi}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
