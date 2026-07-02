#!/usr/bin/env python3
"""
objective_optimizer.py - the meta-controller. Gives the whole orchestrator ONE north-star to optimize
(default: value_per_compute_dollar = merged-value ÷ real+notional compute), measures it each cycle, and
nudges the system's knobs to improve it — keeping changes that help and reverting ones that regress.

It closes the outer loop on top of self_tune / governor / cost_slo: instead of each loop optimizing its
own local metric, this one optimizes the SINGLE portfolio objective and coordinates the knobs toward it.

  measure()  -> compute the objective now (merges × value ÷ compute) and log to north_star.
  step()     -> propose one bounded knob change (Opus bias, diversify, concurrency weights, confidence),
                apply it, and let the NEXT measure() judge it; auto-revert if the objective dropped.

Bounded + fully logged (tuning_log) + reversible. Schedule ~hourly. Never touches safety knobs
(billing firewall, kill switch, RAM gate) — only performance/economics knobs.
"""
import os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

WINDOW_H = int(os.environ.get("OBJECTIVE_WINDOW_H", "6"))


def _metric():
    r = db.select("objective_config", {"select": "metric", "id": "eq.1"}) or [{}]
    return r[0].get("metric", "value_per_compute_dollar")


def measure():
    since = (datetime.datetime.utcnow() - datetime.timedelta(hours=WINDOW_H)).isoformat()
    outs = db.select("outcomes", {"select": "integrated,usd,project", "created_at": f"gte.{since}",
                                  "limit": "2000"}) or []
    merges = sum(1 for o in outs if o.get("integrated"))
    compute = sum(float(o.get("usd") or 0) for o in outs) or 0.0
    # value weight per merge from revenue (app_revenue MRR, log-scaled), default 1
    mrr = {r["app"]: float(r.get("mrr_usd") or 0) for r in (db.select("app_revenue", {"select": "*"}) or [])}
    import math
    value = sum(1 + math.log10(1 + mrr.get(o.get("project"), 0)) for o in outs if o.get("integrated"))
    # objective: value delivered per compute dollar (notional ok; +eps so early $0 doesn't divide by zero)
    obj = round(value / (compute + 0.5), 4)
    db.insert("north_star", {"metric": _metric(), "value": obj,
              "detail": {"merges": merges, "compute": round(compute, 2), "value": round(value, 2),
                         "window_h": WINDOW_H}})
    return obj, {"merges": merges, "compute": round(compute, 2), "value": round(value, 2)}


def _last_two():
    rows = db.select("north_star", {"select": "value", "order": "created_at.desc", "limit": "2"}) or []
    return [float(r["value"]) for r in rows if r.get("value") is not None]


def step():
    """Measure, judge the last change, then propose one new bounded tweak."""
    obj, comp = measure()
    # 1) judge the most recent un-scored tuning change against the objective delta
    pend = db.select("tuning_log", {"select": "*", "kept": "is.null",
                                    "order": "created_at.desc", "limit": "1"}) or []
    if pend:
        t = pend[0]
        before = float(t.get("objective_before") or 0)
        kept = obj >= before        # keep if objective held or improved
        db.update("tuning_log", {"id": t["id"]}, {"objective_after": obj, "kept": kept})
        if not kept:
            _revert(t)
            print(f"objective_optimizer: reverted {t['knob']} (obj {before}->{obj})")
            return {"obj": obj, "action": "reverted", **comp}
    # 2) propose one new tweak toward the objective
    change = _propose(obj)
    if change:
        db.insert("tuning_log", {"knob": change["knob"], "old_value": str(change["old"]),
                  "new_value": str(change["new"]), "objective_before": obj, "reason": change["reason"]})
        _apply(change)
        print(f"objective_optimizer: obj={obj} ({comp}); tuned {change['knob']} {change['old']}->{change['new']}")
        return {"obj": obj, "action": "tuned", "knob": change["knob"], **comp}
    print(f"objective_optimizer: obj={obj} ({comp}); no change")
    return {"obj": obj, "action": "hold", **comp}


def _propose(obj):
    """Pick ONE bounded knob to move. Alternates levers so it explores the space over time."""
    hist = db.select("tuning_log", {"select": "knob", "order": "created_at.desc", "limit": "4"}) or []
    recent = {h["knob"] for h in hist}
    # candidate levers (env-backed, read live by hot_reload) — try one not tried recently
    levers = [
        ("ORCH_OPUS_MAX_SHARE", lambda v: round(min(0.15, float(v or 0.10) + 0.02), 2), "allow slightly more Opus if value/$ is high"),
        ("ORCH_DIVERSIFY_MODELS", lambda v: "true" if (v or "true") == "false" else "true", "keep provider diversification on"),
        ("MERGE_TRAIN_MAX", lambda v: str(min(12, int(v or 8) + 2)), "bigger merge trains = more throughput/$"),
        ("SELFTUNE_STEP", lambda v: str(round(min(0.1, float(v or 0.05) + 0.01), 2)), "faster confidence adaptation"),
    ]
    for env, fn, reason in levers:
        if env in recent:
            continue
        old = os.environ.get(env, "")
        try:
            new = fn(old)
        except Exception:
            continue
        if str(new) != str(old):
            return {"knob": env, "old": old or "(default)", "new": new, "reason": reason}
    return None


def _apply(change):
    # write to .env (non-secret perf knob) so it persists + hot_reload picks it up live
    _set_env_file(change["knob"], str(change["new"]))
    os.environ[change["knob"]] = str(change["new"])


def _revert(t):
    old = t.get("old_value")
    if old and old != "(default)":
        _set_env_file(t["knob"], old); os.environ[t["knob"]] = old


def _set_env_file(key, val):
    env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    try:
        lines = open(env).read().splitlines()
        found = False
        for i, ln in enumerate(lines):
            if ln.startswith(key + "="):
                lines[i] = f"{key}={val}"; found = True; break
        if not found:
            lines.append(f"{key}={val}")
        open(env, "w").write("\n".join(lines) + "\n")
    except Exception:
        pass


def run():
    return step()


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, default=str))
