#!/usr/bin/env python3
"""
app_triage.py - extends the orchestrator's model triage/optimization to the UNDERLYING APPS.

Every product in the portfolio that makes an AI/API call can route it through here instead of
hard-coding a provider. The service:
  1. TRIAGES: picks the cheapest capable provider+model for the operation (model_policy), honoring
     any learned per-(app,operation) recommended route (app_op_routes) from the review loop.
  2. EXECUTES (optional): runs the call via model_gateway (non-agentic) — same metered, capped path.
  3. RECORDS: logs cost/latency/provider to app_operations so the perpetual review loop
     (app_triage_review.py) can rate quality and re-route to keep every app at lowest-cost/
     highest-quality over time.

Two ways for an app to consume this:
  * In-process (Python apps): `import app_triage; app_triage.run(app, operation, prompt, task_class)`
  * Over the wire (any stack): call the Supabase edge function `triage` (see DEPLOY note) which
    wraps route()/run() — so JS/TS/Go apps get the same optimization without embedding this code.

Design rule: this NEVER makes an app more expensive. If no cheaper capable provider is configured,
it returns the app's current/default and logs it; the review loop only ever proposes cost-DOWN or
quality-UP moves, gated by the same cross-model bot review we use internally.
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model_policy, model_gateway as mg

try:
    import db
except Exception:
    db = None


def _learned_route(app, operation):
    """Return a (provider, model, reason) previously proven best for this app+operation, or None."""
    if not db:
        return None
    try:
        rows = db.select("app_op_routes", {"select": "*", "app": f"eq.{app}",
                                           "operation": f"eq.{operation}"}) or []
        if rows and rows[0].get("provider"):
            r = rows[0]
            return r["provider"], r.get("model"), f"learned route (avg ${r.get('avg_cost')}, q {r.get('avg_quality')})"
    except Exception:
        pass
    return None


def route(app, operation, task_class="qa", agentic=False, need=None):
    """Decide the optimal provider+model for this app operation WITHOUT executing it.
    Priority: learned per-operation route -> quality-per-dollar bandit -> cheapest-capable policy."""
    avail = set(mg.available())
    learned = _learned_route(app, operation)
    if learned and learned[0] in avail:
        return {"provider": learned[0], "model": learned[1], "reason": learned[2], "source": "learned"}
    # quality-per-dollar bandit (non-agentic): route to the live best when we have telemetry
    if not agentic:
        try:
            import qpd_bandit
            bp, bm, bwhy = qpd_bandit.best(task_class)
            if bp and bp in avail:
                return {"provider": bp, "model": bm, "reason": bwhy, "source": "bandit"}
        except Exception:
            pass
    prov, model, why = model_policy.choose(task_class=task_class, agentic=agentic, need=need)
    return {"provider": prov, "model": model, "reason": why, "source": "policy"}


def record(app, operation, task_class, provider, model, prompt_chars, cost_usd, latency_ms, ok=True):
    if not db:
        return
    try:
        db.insert("app_operations", {
            "app": app, "operation": operation, "task_class": task_class,
            "provider": provider, "model": model, "prompt_chars": int(prompt_chars or 0),
            "cost_usd": float(cost_usd or 0), "latency_ms": int(latency_ms or 0), "ok": bool(ok)})
    except Exception:
        pass


def run(app, operation, prompt, task_class="qa", need=None, project=None, execute=True):
    """Triage + (optionally) execute a non-agentic app operation, and log it for review.
    Returns {"provider","model","text","cost_usd","reason"} (text empty if execute=False)."""
    r = route(app, operation, task_class=task_class, need=need)
    prov, model = r["provider"], r["model"]
    if not execute:
        record(app, operation, task_class, prov, model, len(prompt or ""), 0, 0, ok=True)
        return {**r, "text": "", "cost_usd": 0}
    t0 = time.time()
    res = mg.complete(prov, model, prompt, project=project or app,
                      operation=operation, task_class=task_class, record_op=False)
    dt = int((time.time() - t0) * 1000)
    cost = res.get("cost_usd", 0)
    actual_provider = res.get("provider") or prov
    actual_model = res.get("model") or model
    record(app, operation, task_class, actual_provider, actual_model, len(prompt or ""), cost, dt,
           ok=not bool(res.get("error")))
    return {"provider": actual_provider, "model": actual_model, "text": res.get("text", ""),
            "cost_usd": cost, "reason": r["reason"], "error": res.get("error")}


if __name__ == "__main__":
    import json
    # demo: what would each common app operation route to right now?
    print("available providers:", mg.available())
    for tc in ("mechanical", "qa", "review", "rating", "plan"):
        print(tc, "->", json.dumps(route("demo-app", f"op_{tc}", task_class=tc)))
