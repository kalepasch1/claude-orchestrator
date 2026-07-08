#!/usr/bin/env python3
"""
fleet_stuck_alarm.py - detects the exact shape of the 2026-07-08 outage: QUEUED work piling
up while nothing is RUNNING. slo_controller.py already enforces throughput SLOs (merge rate,
missing branches, recovery backlog); this is the simpler, more fundamental check underneath
all of those — "is the fleet moving at all" — because a global pause makes every one of those
throughput SLOs look like "no data" rather than "failing", so slo_controller never fired.

Condition: queued > 0 AND running == 0, sustained for ORCH_STUCK_ALARM_S (default 900s = 15min).

On trip:
  1. If the fleet is paused, ask pause_arbiter to recheck — this clears the pause immediately
     if the cause is a registered, now-resolved condition (e.g. billing_key_presence), instead
     of waiting for the pause's own periodic job to notice.
  2. Always files a single approval card (deduped by day) so a human sees it even if nothing
     could be auto-remediated (e.g. a genuinely dead runner process, which no periodic script
     running inside that same dead process can restart itself).

State (first-seen timestamp, last-alert date) lives in a small local JSON file, not the DB, so
this keeps working even if Supabase is degraded.
"""
import os, sys, json, time, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
# kill_switch is imported lazily inside run() so tests can patch sys.modules["kill_switch"].

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
STATE_FILE = os.path.join(HOME, "fleet_stuck_alarm_state.json")
STUCK_THRESHOLD_S = int(os.environ.get("ORCH_STUCK_ALARM_S", "900"))


def _load_state():
    try:
        return json.load(open(STATE_FILE))
    except Exception:
        return {}


def _save_state(state):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def _counts():
    try:
        import queue_counters
        exact = queue_counters.exact_counts(db_client=db)
        return int(exact.get("queued", 0) or 0), int(exact.get("running", 0) or 0)
    except Exception:
        queued = len(db.select("tasks", {"select": "id", "state": "eq.QUEUED", "limit": "5001"}) or [])
        running = len(db.select("tasks", {"select": "id", "state": "eq.RUNNING", "limit": "5001"}) or [])
        return queued, running


def run():
    state = _load_state()
    try:
        queued, running = _counts()
    except Exception as e:
        print(f"fleet_stuck_alarm: could not read task counts ({e})")
        return {"ok": True, "skipped": "db unavailable"}

    stuck_now = queued > 0 and running == 0
    if not stuck_now:
        if state.get("first_seen"):
            state.pop("first_seen", None)
            _save_state(state)
        try:
            db.insert("controls", {"key": "fleet_stuck_alarm",
                                   "value": json.dumps({"stuck": False, "queued": queued,
                                                        "running": running, "checked_at": time.time()}),
                                   "updated_at": "now()"}, upsert=True)
        except Exception:
            pass
        print(f"fleet_stuck_alarm: healthy (queued={queued}, running={running})")
        return {"ok": True, "stuck": False, "queued": queued, "running": running}

    first_seen = state.get("first_seen") or time.time()
    state["first_seen"] = first_seen
    _save_state(state)
    age_s = time.time() - first_seen

    if age_s < STUCK_THRESHOLD_S:
        print(f"fleet_stuck_alarm: queued={queued} running=0 for {age_s:.0f}s (< {STUCK_THRESHOLD_S}s threshold)")
        return {"ok": True, "stuck": True, "age_s": age_s, "queued": queued}

    # tripped: try auto-remediation, then always notify (deduped once per calendar day)
    remediation = "none"
    try:
        import kill_switch
        was_paused = kill_switch.is_paused()
        if was_paused:
            import pause_arbiter
            result = pause_arbiter.recheck(scope="global")
            remediation = f"pause_arbiter: {result.get('action')} ({result.get('reason')})"
        else:
            remediation = "not paused — runner process itself may be down (cannot self-restart from here)"
    except Exception as e:
        remediation = f"remediation check failed: {e}"

    today = datetime.date.today().isoformat()
    if state.get("last_alert_date") != today:
        try:
            db.insert("approvals", {"project": "PORTFOLIO", "kind": "material",
                "title": f"FLEET STUCK: {queued} queued, 0 running for {age_s/60:.0f}+ min",
                "why": f"queued>0 and running=0 sustained past the {STUCK_THRESHOLD_S}s SLO. remediation attempt: {remediation}",
                "value": "Catches silent overnight freezes (e.g. the 2026-07-08 billing_guard deadlock) within 15-20 minutes instead of ~10 hours.",
                "risk": "If this keeps re-firing, the runner process itself is likely down and needs a human to restart it on the Mac.",
                "command": ""})
            state["last_alert_date"] = today
            _save_state(state)
        except Exception as e:
            print(f"fleet_stuck_alarm: failed to file approval: {e}")

    try:
        db.insert("controls", {"key": "fleet_stuck_alarm",
                               "value": json.dumps({"stuck": True, "queued": queued,
                                                    "running": running, "age_s": age_s,
                                                    "remediation": remediation,
                                                    "checked_at": time.time()}),
                               "updated_at": "now()"}, upsert=True)
    except Exception:
        pass
    print(f"fleet_stuck_alarm: TRIPPED — queued={queued}, running=0, age={age_s:.0f}s, remediation={remediation}")
    return {"ok": False, "stuck": True, "queued": queued, "age_s": age_s, "remediation": remediation}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
