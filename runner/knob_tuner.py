#!/usr/bin/env python3
"""knob_tuner.py - closed-loop hill-climb tuner for fleet operational knobs."""
import datetime, json, os, random, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
KNOBS = {
    "ORCH_EASY_OFFLOAD_SHARE": {"lo": 0.5, "hi": 1.0, "step": 0.05, "type": float},
    "MERGE_TRAIN_LOW_RISK_BATCH": {"lo": 4, "hi": 16, "step": 2, "type": int},
    "ORCH_MICROBATCH_SIZE": {"lo": 10, "hi": 50, "step": 5, "type": int},
    "ORCH_PER_PROJECT_CODE_LANES": {"lo": 1, "hi": 4, "step": 1, "type": int},
    "RELEASE_MIN_BATCH": {"lo": 3, "hi": 10, "step": 1, "type": int},
}
STATE_KEY = "knob_tuner_state"
def _scoreboard_metrics():
    try:
        import scoreboard; return scoreboard.compute().get("overall", {})
    except Exception: return {}
def _read_knob(name):
    raw = os.environ.get(name)
    if raw is None: return None
    try: return KNOBS[name]["type"](raw)
    except (KeyError, ValueError): return None
def _write_knob(name, value):
    try: db.upsert("fleet_config", {"key": name, "value": str(value)})
    except Exception: pass
    os.environ[name] = str(value)
def _clamp(name, val):
    k = KNOBS[name]; return max(k["lo"], min(k["hi"], k["type"](val)))
def _step_value(name, current, direction):
    k = KNOBS[name]; return _clamp(name, current + direction * k["step"])
def _pick_knob(state):
    last = state.get("last_knob")
    candidates = [k for k in KNOBS if k != last]
    if not candidates: candidates = list(KNOBS.keys())
    return random.choice(candidates)
def _load_state():
    try:
        r = db.select("controls", {"select": "value", "key": f"eq.{STATE_KEY}", "limit": "1"})
        if r and r[0].get("value"): return json.loads(r[0]["value"])
    except Exception: pass
    return {"history": [], "last_knob": None, "pending": None}
def _save_state(s):
    try: db.upsert("controls", {"key": STATE_KEY, "value": json.dumps(s, default=str), "updated_at": "now()"})
    except Exception: pass
def plan_adjustment():
    state = _load_state(); metrics = _scoreboard_metrics()
    merged_per_day = metrics.get("merged_per_day", 0)
    usd_per_merge = metrics.get("usd_per_merge", 999)
    pending = state.get("pending")
    if pending:
        prev_mpd = pending.get("merged_per_day", 0); prev_upm = pending.get("usd_per_merge", 999)
        old_score = prev_mpd / max(prev_upm, 0.01); new_score = merged_per_day / max(usd_per_merge, 0.01)
        if new_score < old_score * 0.95:
            _write_knob(pending["knob"], pending["old_value"])
            state["history"].append({"ts": datetime.datetime.utcnow().isoformat(), "knob": pending["knob"], "action": "revert", "old": pending["new_value"], "new": pending["old_value"], "reason": f"score {new_score:.3f} < {old_score:.3f}"})
            state["pending"] = None; _save_state(state); return None
        else:
            state["history"].append({"ts": datetime.datetime.utcnow().isoformat(), "knob": pending["knob"], "action": "accept", "value": pending["new_value"], "score_before": round(old_score, 4), "score_after": round(new_score, 4)})
            state["pending"] = None
    knob = _pick_knob(state); current = _read_knob(knob)
    if current is None:
        k = KNOBS[knob]; current = k["type"]((k["lo"] + k["hi"]) / 2)
    direction = random.choice([-1, 1]); new_val = _step_value(knob, current, direction)
    if new_val == current: direction = -direction; new_val = _step_value(knob, current, direction)
    if new_val == current: _save_state(state); return None
    state["last_knob"] = knob
    state["pending"] = {"knob": knob, "old_value": current, "new_value": new_val, "direction": direction, "merged_per_day": merged_per_day, "usd_per_merge": usd_per_merge, "ts": datetime.datetime.utcnow().isoformat()}
    state["history"] = state.get("history", [])[-50:]; _save_state(state)
    return (knob, current, new_val, direction)
def apply_adjustment(plan):
    if plan is None: return
    knob, old_val, new_val, direction = plan
    _write_knob(knob, new_val)
    try: db.insert("approvals", {"title": f"knob_tuner: {knob} {old_val} -> {new_val}", "kind": "ops_card", "status": "info", "detail": json.dumps({"knob": knob, "old": old_val, "new": new_val, "direction": direction, "ts": datetime.datetime.utcnow().isoformat()}, default=str)})
    except Exception: pass
def run():
    plan = plan_adjustment()
    if plan: apply_adjustment(plan); print(f"knob_tuner: adjusted {plan[0]} {plan[1]} -> {plan[2]}")
    else: print("knob_tuner: no adjustment this cycle")
    return plan
if __name__ == "__main__": run()
