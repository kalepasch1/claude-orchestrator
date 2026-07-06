#!/usr/bin/env python3
"""
improvement_measure.py - closes the loop on the 20-500X miner: it doesn't just GENERATE ideas, it learns
which KINDS actually pay off, and biases future mining toward them.

  1. mark shipped: any improvement_proposal whose task merged -> status='shipped'.
  2. attribute: link shipped improvements to the app's revenue/usage movement (merge_revenue).
  3. surface returns: avg realized delta per SURFACE (feature/ux/api/backend/orchestration/swarm/...),
     written to surface_returns so improvement_miner can weight high-return surfaces higher next cycle.
  4. stage_metrics: track cycle_time and first_try_yield per project/kind over rolling windows (5/30/90d).
Schedule daily. Read-only except status + the returns/stage_metrics tables.
"""
import os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def mark_shipped():
    merged = {t["slug"] for t in (db.select("tasks", {"select": "slug", "state": "eq.MERGED"}) or [])}
    n = 0
    for p in db.select("improvement_proposals", {"select": "id,task_slug,status", "status": "eq.queued"}) or []:
        if p.get("task_slug") in merged:
            db.update("improvement_proposals", {"id": p["id"]}, {"status": "shipped"})
            n += 1
    return n


def surface_returns():
    """avg realized revenue delta per surface (from merge_revenue joined by slug)."""
    shipped = db.select("improvement_proposals", {"select": "surface,task_slug", "status": "eq.shipped"}) or []
    rev = {r["slug"]: float(r.get("revenue_delta") or 0)
           for r in (db.select("merge_revenue", {"select": "slug,revenue_delta"}) or [])}
    agg = {}
    for p in shipped:
        d = rev.get(p.get("task_slug"))
        if d is None:
            continue
        a = agg.setdefault(p["surface"], [0.0, 0]); a[0] += d; a[1] += 1
    out = {}
    for surface, (tot, cnt) in agg.items():
        if cnt:
            avg = round(tot / cnt, 2)
            out[surface] = avg
            db.insert("surface_returns", {"surface": surface, "avg_delta": avg, "n": cnt,
                      "updated_at": "now()"}, upsert=True)
    return out


def stage_metrics():
    """Measure cycle_time (seconds) and first_try_yield per project/kind over rolling windows.
    Rolling windows: 5, 30, 90 days. Writes to stage_metrics table for meta_loop tuning.
    Returns summary dict."""
    now = datetime.datetime.utcnow()
    windows = [5, 30, 90]  # days

    merged = db.select("tasks", {"select": "id,slug,project_id,kind,created_at,remediation_count,state",
                                 "state": "eq.MERGED", "order": "created_at.desc", "limit": "5000"}) or []
    outcomes_map = {o["task_id"]: o for o in (db.select("outcomes", {"select": "task_id,created_at,wall_ms"}) or [])}

    metrics_by_key = {}  # (project_id, kind, window_days) -> {"cycle_times": [...], "first_try": [...]}

    for t in merged:
        proj = t.get("project_id")
        kind = t.get("kind") or "unknown"
        created = t.get("created_at")
        rc = int(t.get("remediation_count") or 0)
        first_try = (rc == 0)

        # parse created_at ISO string to datetime
        try:
            if isinstance(created, str):
                created_dt = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
            else:
                created_dt = created
        except (ValueError, AttributeError):
            continue

        outcome = outcomes_map.get(t["id"])
        if not outcome:
            continue

        # parse completion time from outcome
        try:
            completed = outcome.get("created_at")
            if isinstance(completed, str):
                completed_dt = datetime.datetime.fromisoformat(completed.replace("Z", "+00:00"))
            else:
                completed_dt = completed
        except (ValueError, AttributeError):
            continue

        # cycle_time in seconds
        try:
            cycle_seconds = (completed_dt - created_dt).total_seconds()
            if cycle_seconds <= 0:
                continue
        except Exception:
            continue

        # classify by window
        for window_days in windows:
            days_ago = (now - created_dt).days
            if days_ago > window_days:
                continue
            key = (proj, kind, window_days)
            if key not in metrics_by_key:
                metrics_by_key[key] = {"cycle_times": [], "first_try": []}
            metrics_by_key[key]["cycle_times"].append(cycle_seconds)
            metrics_by_key[key]["first_try"].append(first_try)

    # aggregate and persist
    written = 0
    for (proj, kind, window_days), data in metrics_by_key.items():
        cycles = data["cycle_times"]
        tries = data["first_try"]
        if not cycles or not tries:
            continue

        avg_cycle = round(sum(cycles) / len(cycles), 1)
        yield_pct = round(100 * sum(tries) / len(tries), 1)
        n = len(cycles)

        try:
            db.insert("stage_metrics", {
                "project_id": proj, "kind": kind, "window_days": window_days,
                "avg_cycle_time_seconds": avg_cycle, "first_try_yield_pct": yield_pct,
                "sample_count": n, "updated_at": "now()"
            }, upsert=True)
            written += 1
        except Exception as e:
            print(f"improvement_measure: stage_metrics insert failed: {e}")

    return {"stage_metrics_written": written}


def run():
    shipped = mark_shipped()
    returns = surface_returns()
    metrics = stage_metrics()
    print(f"improvement_measure: marked {shipped} shipped; surface returns -> {returns}; {metrics}")
    return {"shipped": shipped, "returns": returns, **metrics}


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, default=str))
