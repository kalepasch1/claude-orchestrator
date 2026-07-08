#!/usr/bin/env python3
"""
pause_arbiter.py - single owner of "why is the fleet paused and when should that lift".

Before this module, every guard (billing_guard, waste guard, security panic, cost circuit)
called kill_switch.pause() directly with a free-text reason and nothing ever un-paused it
except a human noticing and running `kill_switch.py resume`. That is exactly how the fleet
sat globally paused for ~10 hours on 2026-07-08: billing_guard tripped on a self-inflicted
key-presence bug, paused everything, and nothing was watching to lift it once the cause
(db.py re-injecting ANTHROPIC_API_KEY past the firewall) was fixed.

pause_arbiter gives every pause a TYPED reason_code + optional TTL, and owns a small
registry of "is this cause still true?" checks. recheck() (run every 5 min, safe-when-paused)
re-evaluates the current pause and lifts it the moment its registered check reports clean,
or once its TTL expires for causes explicitly marked auto-expirable. Pauses with no
registered checker (e.g. a manual dashboard STOP, or a real-spend/security trip) are NEVER
auto-lifted — only a human or an explicit resume() call clears those. This is deliberately
conservative: silence (no check, no TTL) always means "stay paused until a human looks."

Usage:
    pause_arbiter.pause("billing_key_presence", "stray ANTHROPIC_API_KEY in env",
                         by="billing_guard", ttl_s=900, project=None)
    pause_arbiter.recheck()   # periodic job; lifts only causes it can verify are clear
    pause_arbiter.resume(by="operator")  # human override, always allowed
"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# kill_switch is imported lazily inside each function (not at module load time) so tests can
# patch sys.modules["kill_switch"] per-test, matching the rest of this codebase's convention.

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
STATE_FILE = os.path.join(HOME, "pause_arbiter_state.json")

# reason_code -> (clear_check() -> bool, auto_expirable: bool)
# clear_check returning True means "the condition that caused this pause is gone; safe to lift".
# auto_expirable means: if clear_check itself errors or the module can't be imported, still
# lift once the TTL passes rather than freezing forever on a broken checker.
_REGISTRY = {}


def register(reason_code, clear_check, auto_expirable=True):
    _REGISTRY[reason_code] = (clear_check, auto_expirable)


def _billing_key_presence_clear():
    import subscription_guard
    a = subscription_guard.audit()
    return not a.get("api_keys_present")


# Registered at import time so recheck() works out of the box for the exact cause that
# deadlocked the fleet on 2026-07-08.
register("billing_key_presence", _billing_key_presence_clear, auto_expirable=True)
# Real billable spend and security panics are never auto-cleared: no checker registered,
# so recheck() leaves them alone until a human calls resume() explicitly.


def _load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass  # fail-soft: metadata is best-effort, kill_switch is still the source of truth


ESCALATE_AFTER = 3  # consecutive identical trips (auto-lifted in between) before we stop
                     # auto-resuming and hand the decision to a human. Below this, a cause
                     # that trips-clears-trips-clears is assumed genuinely self-healing.


def pause(reason_code, message, by="pause_arbiter", ttl_s=None, scope="global", project=None):
    """Pause with a typed, trackable reason. Always writes the real kill switch (source of
    truth for is_paused()); the JSON metadata is advisory, used only by recheck().

    Tracks a consecutive-identical-trip streak per (scope, project, reason_code): if the same
    cause trips, gets auto-lifted, and trips again ESCALATE_AFTER times in a row, that is not
    a self-healing condition — something upstream keeps re-triggering it (this is exactly how
    billing_guard silently re-paused the fleet 878 times on 2026-07-08). Once escalated, the
    pause is marked sticky: recheck() stops auto-lifting it and one material approval is filed
    so a human sees it, instead of the guard trip re-tripping forever unnoticed.
    """
    import kill_switch
    reason = f"[{reason_code}] {message}"
    result = kill_switch.pause(scope=scope, project=project, reason=reason, by=by)
    key = f"{scope}:{project or ''}"
    state = _load_state()
    prev = state.get(key) or {}
    streak = prev.get("streak", 0) + 1 if prev.get("reason_code") == reason_code else 1
    entry = {"reason_code": reason_code, "message": message, "by": by,
              "paused_at": time.time(), "ttl_s": ttl_s, "streak": streak}
    escalated = streak >= ESCALATE_AFTER
    entry["escalated"] = escalated
    state[key] = entry
    _save_state(state)
    if escalated and not prev.get("escalated"):
        _file_escalation_approval(reason_code, message, scope, project, streak)
    return result


def _file_escalation_approval(reason_code, message, scope, project, streak):
    """Fail-soft: escalation is best-effort visibility, never blocks the pause itself."""
    try:
        import db
        db.insert("approvals", {
            "project": project or "PORTFOLIO",
            "kind": "material",
            "title": f"pause_arbiter: '{reason_code}' has re-tripped {streak}x in a row",
            "detail": (f"{message}\n\nThis cause was auto-lifted and re-tripped {streak} times "
                       f"consecutively (scope={scope}). pause_arbiter will no longer auto-lift "
                       f"it — the fleet stays paused until a human resolves the root cause and "
                       f"calls pause_arbiter.resume()."),
        })
    except Exception:
        pass


def resume(scope="global", project=None, by="operator"):
    import kill_switch
    key = f"{scope}:{project or ''}"
    state = _load_state()
    state.pop(key, None)
    _save_state(state)
    return kill_switch.resume(scope=scope, project=project, by=by)


def recheck(scope="global", project=None):
    """Periodic entry point. Returns a dict describing what it found/did. Never raises."""
    import kill_switch
    key = f"{scope}:{project or ''}"
    try:
        if not kill_switch.is_paused(project if scope == "project" else None):
            _load_state()  # no-op read, keeps behavior symmetric
            state = _load_state()
            if key in state:
                state.pop(key, None)
                _save_state(state)
            return {"paused": False, "action": "none"}
    except Exception as e:
        return {"paused": None, "action": "none", "error": f"is_paused failed: {e}"}

    state = _load_state()
    meta = state.get(key)
    if not meta:
        # Paused, but not through the arbiter (manual STOP, or a pre-arbiter pause) — never
        # touch a pause we don't have typed metadata for.
        return {"paused": True, "action": "none", "reason": "no arbiter metadata (manual/unknown pause)"}

    reason_code = meta.get("reason_code")
    if meta.get("escalated"):
        return {"paused": True, "action": "none",
                "reason": f"{reason_code} escalated after {meta.get('streak')} consecutive trips; awaiting human resume()"}
    entry = _REGISTRY.get(reason_code)
    ttl_s = meta.get("ttl_s")
    age_s = time.time() - meta.get("paused_at", time.time())

    if entry:
        clear_check, auto_expirable = entry
        try:
            if clear_check():
                resume(scope=scope, project=project, by="pause_arbiter")
                return {"paused": True, "action": "lifted", "reason": f"{reason_code} cleared"}
        except Exception as e:
            if auto_expirable and ttl_s is not None and age_s >= float(ttl_s):
                resume(scope=scope, project=project, by="pause_arbiter")
                return {"paused": True, "action": "lifted",
                        "reason": f"{reason_code} checker errored ({e}) and TTL {ttl_s}s expired"}
            return {"paused": True, "action": "none", "reason": f"{reason_code} checker errored: {e}"}

    if ttl_s is not None and age_s >= float(ttl_s) and reason_code in _REGISTRY and _REGISTRY[reason_code][1]:
        resume(scope=scope, project=project, by="pause_arbiter")
        return {"paused": True, "action": "lifted", "reason": f"{reason_code} TTL {ttl_s}s expired"}

    return {"paused": True, "action": "none", "reason": f"{reason_code} not clear yet (age={age_s:.0f}s)"}


def run():
    """Periodic job entry: recheck the global pause (project-scoped guards call recheck()
    themselves at the point they'd otherwise pause)."""
    result = recheck(scope="global")
    print(f"pause_arbiter: {result}")
    return result


if __name__ == "__main__":
    import sys as _sys
    if len(_sys.argv) > 1 and _sys.argv[1] == "resume":
        print(resume(by="manual"))
    else:
        print(json.dumps(run(), indent=2, default=str))
