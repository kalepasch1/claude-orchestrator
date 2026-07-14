#!/usr/bin/env python3
"""provider_failover_sla.py - SLA tracking/enforcement with qpd_bandit self-healing.

Slice-3: when a provider's error rate or latency spikes, the qpd bandit demotes it
automatically; on recovery (sustained good metrics past cooldown), it re-promotes.
This makes failover self-healing rather than requiring manual intervention.
"""
import datetime, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

AVAIL_THRESH = float(os.environ.get("ORCH_PROVIDER_SLA_AVAIL", "0.90"))
P95_LIMIT = int(os.environ.get("ORCH_PROVIDER_SLA_P95_MS", "30000"))
WINDOW_H = int(os.environ.get("ORCH_PROVIDER_SLA_WINDOW_H", "2"))
COOLDOWN = int(os.environ.get("ORCH_PROVIDER_SLA_COOLDOWN_MIN", "30"))
CK = "provider_sla_state"


def _local_path():
    home = os.environ.get("CLAUDE_ORCH_HOME",
                          os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".runtime"))
    return os.path.join(home, "provider_sla_state.json")


def _recent_ops():
    since = (datetime.datetime.utcnow() - datetime.timedelta(hours=WINDOW_H)).isoformat()
    try:
        return db.select("operations", {
            "select": "provider,latency_ms,ok,error,created_at",
            "created_at": f"gte.{since}", "limit": "5000"
        }) or []
    except Exception:
        return []


def _compute_sla(ops):
    bp = {}
    for o in ops:
        bp.setdefault(o.get("provider") or "unknown", []).append(o)
    sla = {}
    for p, ol in bp.items():
        n = len(ol)
        ok = sum(1 for o in ol if o.get("ok"))
        av = round(ok / n, 4) if n else 1.0
        lats = sorted(int(o.get("latency_ms") or 0) for o in ol if o.get("ok"))
        p95 = lats[int(len(lats) * 0.95)] if lats else 0
        sla[p] = {"total": n, "ok": ok, "avail": av, "p95": p95,
                  "breach_avail": av < AVAIL_THRESH, "breach_lat": p95 > P95_LIMIT}
    return sla


def _load():
    local = {"demoted": {}, "history": []}
    try:
        with open(_local_path()) as f:
            local = json.load(f)
    except Exception:
        pass
    try:
        r = db.select("controls", {"select": "value", "key": f"eq.{CK}", "limit": "1"})
        if r and r[0].get("value"):
            remote = json.loads(r[0]["value"])
            # Local auth failures take precedence when the control-plane write
            # was unavailable; remote state adds fleet-wide demotions.
            remote["demoted"] = {**(remote.get("demoted") or {}),
                                 **(local.get("demoted") or {})}
            return remote
    except Exception:
        pass
    return local


def _save(s):
    try:
        os.makedirs(os.path.dirname(_local_path()), exist_ok=True)
        tmp = _local_path() + ".tmp"
        with open(tmp, "w") as f:
            json.dump(s, f, default=str)
        os.replace(tmp, _local_path())
    except Exception:
        pass
    try:
        db.upsert("controls", {"key": CK, "value": json.dumps(s, default=str), "updated_at": "now()"})
    except Exception:
        pass


# ── Slice-3: qpd_bandit integration for self-healing ────────────────────────

def _notify_bandit_demote(provider, reason):
    """Tell the qpd_bandit to penalize a provider so it routes traffic away."""
    try:
        import qpd_bandit
        qpd_bandit.penalize(provider, reason)
    except (ImportError, AttributeError):
        pass  # bandit not available or missing penalize — config flag still works


def _notify_bandit_promote(provider):
    """Tell the qpd_bandit the provider is healthy again."""
    try:
        import qpd_bandit
        qpd_bandit.restore(provider)
    except (ImportError, AttributeError):
        pass


def demote(provider, reason="manual", immediate=True):
    """Immediately quarantine an auth-invalid provider from optimization routes."""
    state = _load()
    dem = state.get("demoted") or {}
    dem[provider] = {"since": datetime.datetime.utcnow().isoformat(),
                     "reason": reason, "avail": 0.0, "p95": 0,
                     "immediate": bool(immediate)}
    state["demoted"] = dem
    _save(state)
    try:
        db.upsert("fleet_config", {
            "key": f"ORCH_PROVIDER_DEMOTED_{provider.upper()}", "value": "true"
        })
    except Exception:
        pass
    _notify_bandit_demote(provider, reason)
    return dem[provider]


def check_and_enforce():
    """Check SLA for all providers; demote/promote via fleet_config AND qpd_bandit."""
    sla = _compute_sla(_recent_ops())
    state = _load()
    now = datetime.datetime.utcnow()
    dem = state.get("demoted") or {}

    for p, m in sla.items():
        br = m["breach_avail"] or m["breach_lat"]
        if br and p not in dem:
            # Demote: set config flag AND notify bandit
            reason = "availability" if m["breach_avail"] else "latency"
            dem[p] = {"since": now.isoformat(), "reason": reason,
                      "avail": m["avail"], "p95": m["p95"]}
            try:
                db.upsert("fleet_config", {
                    "key": f"ORCH_PROVIDER_DEMOTED_{p.upper()}", "value": "true"
                })
            except Exception:
                pass
            _notify_bandit_demote(p, reason)

        elif not br and p in dem:
            # Recovery check: sustained good metrics past cooldown → re-promote
            try:
                elapsed = (now - datetime.datetime.fromisoformat(dem[p]["since"])).total_seconds() / 60
            except Exception:
                elapsed = COOLDOWN + 1
            if elapsed >= COOLDOWN:
                del dem[p]
                try:
                    db.upsert("fleet_config", {
                        "key": f"ORCH_PROVIDER_DEMOTED_{p.upper()}", "value": "false"
                    })
                except Exception:
                    pass
                _notify_bandit_promote(p)

    state["demoted"] = dem
    state["sla"] = sla
    state["checked_at"] = now.isoformat()
    h = state.get("history") or []
    h.append({"ts": now.isoformat(), "demoted": list(dem.keys())})
    state["history"] = h[-100:]
    _save(state)
    return state


def is_demoted(provider):
    return provider in (_load().get("demoted") or {})


def run():
    s = check_and_enforce()
    print(f"provider_sla: checked")
    return s


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
