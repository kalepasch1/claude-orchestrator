#!/usr/bin/env python3
"""
ev_scheduler.py - EV-per-token task ordering. Scores every QUEUED task by expected value
per token spent, so the swarm burns budget on work that plausibly moves revenue first.

score(task, ctx) heuristic (deterministic, unit-testable):
    base   = log10(1 + MRR of the task's project)           # revenue-weighted
    s      = base * success_rate / (avg_usd + 0.5)          # discount by cost + failure odds
    s     *= (1 + min(kind_delta, 100)/100) if that task KIND has shown positive
             revenue-per-merge in ctx["surface_returns"] (from revenue_attribution.kind_roi)
    s     *= 1.5  if kind == 'build' and prompt mentions revenue/pricing/growth/conversion
    s     *= 2.0  if slug is an APPROVED business-model check (ctx["approved_slugs"])
    s     *= 0.3  if transient_retries >= 2                  # flaky work is discounted

ctx = {"revenue_by_project": {name: mrr}, "surface_returns": {kind: avg_delta},
       "outcome_stats": {project: {"success_rate", "avg_usd"}}, "approved_slugs": set()}

PRIORITY STORAGE CHOICE (apply_ranking):
    1. If tasks has a real 'priority' column (probed via select=priority&limit=1 in
       try/except — PostgREST 400s on unknown columns), write rank 1..50 there (lower
       = claimed first, matching claim_task's ascending priority sort).
    2. Otherwise write ONE 'controls' row: insert({"key":"ev_ranking","value":<json of
       top-100 ids>}, upsert=True) — a single advisory row the claim loop can consult,
       zero schema risk to tasks.
    3. If controls rejects key/value too (the live controls table is scope/paused-shaped,
       see kill_switch.py), last-resort: write a 0..1 rank score into tasks.confidence
       for the top 50 (higher = better). Chosen because 'confidence' already exists and
       is numeric; the cascade guarantees SOME storage works without schema changes.

park_zero_ev(): legacy name. It no longer blocks work; tasks scoring < 0.01 are annotated
and deprioritized, but remain QUEUED so the implementation pipeline continues.
"""
import os, sys, json, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import thermal_map

TOP_N = 50                 # tasks that receive an explicit priority write
CONTROLS_TOP = 100         # ids stored in the controls ev_ranking row
PARK_CAP = 20              # max tasks parked per run
ZERO_EV = 0.01             # scores below this are "near-zero"
PARK_NOTE = "[ev-low-priority: near-zero expected value — keep queued, run when capacity allows]"
BOOST_KINDS = ("build",)
REVENUE_WORDS = ("revenue", "pricing", "growth", "conversion")


def score(task, ctx):
    """Expected value per token for one task. Pure + deterministic."""
    project = task.get("project") or ""
    mrr = float((ctx.get("revenue_by_project") or {}).get(project, 0) or 0)
    stats = (ctx.get("outcome_stats") or {}).get(project, {}) or {}
    success_rate = float(stats.get("success_rate", 0.7))
    avg_usd = float(stats.get("avg_usd", 0) or 0)

    s = math.log10(1 + max(0.0, mrr)) * success_rate / (avg_usd + 0.5)

    kind = (task.get("kind") or "").lower()
    delta = (ctx.get("surface_returns") or {}).get(kind)
    if delta and float(delta) > 0:
        s *= 1 + min(float(delta), 100.0) / 100.0

    prompt = (task.get("prompt") or "").lower()
    if kind in BOOST_KINDS and any(w in prompt for w in REVENUE_WORDS):
        s *= 1.5
    if task.get("slug") and task.get("slug") in (ctx.get("approved_slugs") or set()):
        s *= 2.0
    if int(task.get("transient_retries") or 0) >= 2:
        s *= 0.3

    # App-signal adjustments from telemetry_ingest: error spikes boost fix-kind tasks,
    # rising usage boosts feature tasks, dead apps sink. Missing signal = neutral.
    app_signals = (ctx.get("app_signals") or {}).get(project, {})
    if app_signals:
        error_rate = float(app_signals.get("error_rate", 0))
        usage_trend = float(app_signals.get("usage_trend", 0))
        if error_rate > 0.3 and kind in ("bugfix", "fix", "hotfix", "build"):
            s *= 1 + min(error_rate, 1.0)  # up to 2x for high error rates
        if usage_trend > 0.2 and kind in ("build", "feature"):
            s *= 1 + min(usage_trend, 1.0) * 0.5  # up to 1.5x for growing apps
        if usage_trend < -0.5 and error_rate < 0.1:
            s *= 0.5  # dead/declining app with no errors: deprioritize

    # ORCHESTRATOR-FIRST (owner directive): self-improvements to the orchestration layer have no
    # direct MRR but compound across the WHOLE fleet (a better orchestrator ships every app better),
    # so give them a high synthetic EV to rank them at the front of the queue.
    if project in ("beethoven", "orchestrator", "ORCHESTRATOR"):
        s = max(s, 20.0) * float(os.environ.get("ORCH_SELF_IMPROVE_BOOST", "3.0"))
    return s


def thermal_score(task, ctx):
    """Expected merged value per minute. This is the queue's primary heat signal."""
    return thermal_map.score(task, ctx)


def load_ctx():
    """Build the scoring context from db. Every read is fail-soft."""
    ctx = {"revenue_by_project": {}, "surface_returns": {}, "outcome_stats": {},
           "approved_slugs": set()}
    try:
        for r in db.select("app_revenue", {"select": "app,mrr_usd"}) or []:
            ctx["revenue_by_project"][r.get("app")] = float(r.get("mrr_usd") or 0)
    except Exception:
        pass
    try:
        agg = {}
        for r in db.select("outcomes", {"select": "project,usd,integrated",
                                        "limit": "5000"}) or []:
            a = agg.setdefault(r.get("project") or "?", [0.0, 0, 0])
            a[0] += float(r.get("usd") or 0); a[1] += 1
            a[2] += 1 if r.get("integrated") else 0
        for p, (usd, n, ok) in agg.items():
            if n:
                ctx["outcome_stats"][p] = {"success_rate": ok / n, "avg_usd": usd / n}
    except Exception:
        pass
    try:
        agg = {}
        for r in db.select("merge_revenue", {"select": "kind,revenue_delta"}) or []:
            a = agg.setdefault((r.get("kind") or "?").lower(), [0.0, 0])
            a[0] += float(r.get("revenue_delta") or 0); a[1] += 1
        ctx["surface_returns"] = {k: v[0] / v[1] for k, v in agg.items() if v[1]}
    except Exception:
        pass
    try:
        for r in db.select("approvals", {"select": "slug,title,status,radar_tag",
                                         "radar_tag": "not.is.null",
                                         "status": "eq.approved"}) or []:
            slug = r.get("slug") or (r.get("title") or "").rsplit(": ", 1)[-1]
            if slug:
                ctx["approved_slugs"].add(slug)
    except Exception:
        pass
    return ctx


def _scored_queue(limit=500, ctx=None):
    """[(score, task), ...] sorted desc by score (created_at, id break ties)."""
    ctx = ctx if ctx is not None else load_ctx()
    tasks = db.select("tasks", {"select": "*", "state": "eq.QUEUED",
                                "limit": str(limit)}) or []
    names = {}
    try:
        names = {p["id"]: p["name"] for p in
                 db.select("projects", {"select": "id,name"}) or []}
    except Exception:
        pass
    for t in tasks:
        if not t.get("project"):
            t["project"] = names.get(t.get("project_id"), "")
    scored = [(thermal_score(t, ctx), t) for t in tasks]
    scored.sort(key=lambda p: (-p[0], p[1].get("created_at") or "", str(p[1].get("id"))))
    return scored


def rank_queue(limit=500, ctx=None):
    """Task ids for all QUEUED tasks, best expected value first."""
    return [t["id"] for _, t in _scored_queue(limit=limit, ctx=ctx)]


def _has_priority_column():
    try:
        db.select("tasks", {"select": "priority", "limit": "1"})
        return True
    except Exception:
        return False


def apply_ranking(scored=None):
    """Persist the ranking (storage cascade documented in module docstring)."""
    scored = scored if scored is not None else _scored_queue()
    top = scored[:TOP_N]
    if _has_priority_column():
        n = 0
        for idx, (heat, t) in enumerate(top):
            try:
                db.update("tasks", {"id": t["id"]},
                          {"priority": idx + 1,
                           "thermal_score": round(float(heat), 6),
                           "estimated_minutes": round(thermal_map.estimate_minutes(t), 2)})
                n += 1
            except Exception:
                try:
                    db.update("tasks", {"id": t["id"]}, {"priority": idx + 1})
                    n += 1
                except Exception:
                    pass
        return {"storage": "priority", "count": n}
    try:
        ids = [t["id"] for _, t in scored[:CONTROLS_TOP]]
        db.insert("controls", {"key": "thermal_ranking", "value": json.dumps(ids)}, upsert=True)
        return {"storage": "controls", "count": len(ids)}
    except Exception:
        pass
    n = 0
    for idx, (_, t) in enumerate(top):
        try:
            db.update("tasks", {"id": t["id"]},
                      {"confidence": round(max(0.0, 1.0 - idx / float(TOP_N)), 4)})
            n += 1
        except Exception:
            pass
    return {"storage": "confidence", "count": n}


def park_zero_ev(scored=None):
    """Annotate near-zero-EV tasks without blocking them (cap PARK_CAP/run)."""
    scored = scored if scored is not None else _scored_queue()
    parked = 0
    for s, t in scored:
        if parked >= PARK_CAP:
            break
        if s < ZERO_EV and int(t.get("attempt") or 0) >= 2:
            try:
                db.update("tasks", {"id": t["id"]},
                          {"note": PARK_NOTE, "updated_at": "now()"})
                parked += 1
            except Exception:
                pass
    return parked


def run():
    try:
        scored = _scored_queue()
        applied = apply_ranking(scored)
        parked = park_zero_ev(scored)
        print(f"ev_scheduler: ranked {len(scored)} queued tasks "
              f"(storage={applied['storage']}, wrote {applied['count']}), parked {parked}")
        return {"ranked": len(scored), **applied, "parked": parked}
    except Exception as e:
        print(f"ev_scheduler: skipped ({e})")
        return {"ranked": 0, "error": str(e)}


if __name__ == "__main__":
    run()
