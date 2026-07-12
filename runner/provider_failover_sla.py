#!/usr/bin/env python3
"""provider_failover_sla.py - SLA tracking/enforcement for provider failover."""
import datetime, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
AVAIL_THRESH = float(os.environ.get("ORCH_PROVIDER_SLA_AVAIL", "0.90"))
P95_LIMIT = int(os.environ.get("ORCH_PROVIDER_SLA_P95_MS", "30000"))
WINDOW_H = int(os.environ.get("ORCH_PROVIDER_SLA_WINDOW_H", "2"))
COOLDOWN = int(os.environ.get("ORCH_PROVIDER_SLA_COOLDOWN_MIN", "30"))
CK = "provider_sla_state"
def _recent_ops():
    since = (datetime.datetime.utcnow() - datetime.timedelta(hours=WINDOW_H)).isoformat()
    try: return db.select("operations", {"select": "provider,latency_ms,ok,error,created_at", "created_at": f"gte.{since}", "limit": "5000"}) or []
    except Exception: return []
def _compute_sla(ops):
    bp = {}
    for o in ops: bp.setdefault(o.get("provider") or "unknown", []).append(o)
    sla = {}
    for p, ol in bp.items():
        n = len(ol); ok = sum(1 for o in ol if o.get("ok")); av = round(ok/n, 4) if n else 1.0
        lats = sorted(int(o.get("latency_ms") or 0) for o in ol if o.get("ok"))
        p95 = lats[int(len(lats)*0.95)] if lats else 0
        sla[p] = {"total": n, "ok": ok, "avail": av, "p95": p95, "breach_avail": av < AVAIL_THRESH, "breach_lat": p95 > P95_LIMIT}
    return sla
def _load():
    try:
        r = db.select("controls", {"select": "value", "key": f"eq.{CK}", "limit": "1"})
        if r and r[0].get("value"): return json.loads(r[0]["value"])
    except Exception: pass
    return {"demoted": {}, "history": []}
def _save(s):
    try: db.upsert("controls", {"key": CK, "value": json.dumps(s, default=str), "updated_at": "now()"})
    except Exception: pass
def check_and_enforce():
    sla = _compute_sla(_recent_ops()); state = _load(); now = datetime.datetime.utcnow()
    dem = state.get("demoted") or {}
    for p, m in sla.items():
        br = m["breach_avail"] or m["breach_lat"]
        if br and p not in dem:
            dem[p] = {"since": now.isoformat(), "reason": "availability" if m["breach_avail"] else "latency"}
            try: db.upsert("fleet_config", {"key": f"ORCH_PROVIDER_DEMOTED_{p.upper()}", "value": "true"})
            except Exception: pass
        elif not br and p in dem:
            try: elapsed = (now - datetime.datetime.fromisoformat(dem[p]["since"])).total_seconds()/60
            except Exception: elapsed = COOLDOWN + 1
            if elapsed >= COOLDOWN:
                del dem[p]
                try: db.upsert("fleet_config", {"key": f"ORCH_PROVIDER_DEMOTED_{p.upper()}", "value": "false"})
                except Exception: pass
    state["demoted"] = dem; state["sla"] = sla; state["checked_at"] = now.isoformat()
    h = state.get("history") or []; h.append({"ts": now.isoformat(), "demoted": list(dem.keys())}); state["history"] = h[-100:]
    _save(state); return state
def is_demoted(provider): return provider in (_load().get("demoted") or {})
def run():
    s = check_and_enforce(); print(f"provider_sla: checked"); return s
if __name__ == "__main__": print(json.dumps(run(), indent=2, default=str))
