#!/usr/bin/env python3
"""
billing_guard.py - independent tripwire for direct Anthropic API spend.

Claude Code/CLI usage through the logged-in Max subscription account is expected, high-value
capacity and must not be treated as a billing incident. This guard only pauses the fleet for proven
direct API spend above the configured cap, or for explicit strict key-presence mode outside normal
subscription operation.

Checks every run:
  1. Residual Anthropic API keys in the env while API billing is blocked -> scrub and alert. This is
     common when a standalone scheduled process reloads runner/.env; key presence alone is not spend
     if subscription_guard can strip it before model execution.
  2. REAL direct-API $ from claude_cli's circuit-breaker ledger (real_usd; ~$0 in subscription mode).
     If real spend today exceeds the allowed cap, PAUSE everything and file a material approval.

Default behavior is still near-zero ($2) when API billing is not explicitly allowed. If
ORCH_ALLOW_API_BILLING=true, the trip cap becomes ORCH_API_DAILY_USD_CAP (or BILLING_TRIP_USD), so
paid fallback can operate inside a deliberate budget without becoming a user-facing pause.
"""
import os, sys, json, re, time, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
STATE_FILE = os.path.join(HOME, "billing_guard_state.json")


def _state_file():
    """Resolved per call, not at import, so a test (or a relocated fleet home) can point
    CLAUDE_ORCH_HOME somewhere else without having to re-import the module."""
    home = os.environ.get("CLAUDE_ORCH_HOME")
    if not home:
        return STATE_FILE
    return os.path.join(home, "billing_guard_state.json")

# Consecutive identical trips (same cause_key) tolerated before billing_guard stops
# re-pausing and hands the decision to a human via exactly one material approval card.
ESCALATE_AFTER = 3

# A streak only means something while it is *recent*. If the same cause reappears days
# later it is a new incident, not a re-trip, so the streak resets after this window.
STREAK_RESET_S = 6 * 3600


def _streak_reset_s():
    try:
        return float(os.environ.get("ORCH_BILLING_STREAK_RESET_S", STREAK_RESET_S))
    except Exception:
        return float(STREAK_RESET_S)


def _cause_key(findings):
    """Stable digest identifying WHY we tripped.

    Dollar amounts and other numbers are normalised out: "$41.10 > trip $2.00" and
    "$41.63 > trip $2.00" are the same underlying cause, and treating them as distinct
    is precisely what let a re-tripping guard evade every de-duplication attempt.
    """
    try:
        norm = sorted(re.sub(r"\d+(?:\.\d+)?", "#", str(f)) for f in (findings or []))
        return hashlib.sha1("|".join(norm).encode("utf-8")).hexdigest()[:16]
    except Exception:
        return "unknown"


def _load_state():
    """Fail-soft: a missing/corrupt state file must never stop the guard from running."""
    try:
        with open(_state_file()) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_state(state):
    """Fail-soft: streak metadata is advisory; kill_switch remains the source of truth."""
    try:
        path = _state_file()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def _trip_usd(api_allowed=False):
    if api_allowed:
        return float(os.environ.get("ORCH_API_DAILY_USD_CAP",
                                    os.environ.get("BILLING_TRIP_USD", "25.0")))
    return float(os.environ.get("BILLING_TRIP_USD", "2.0"))


def _strict_key_presence_pause():
    return os.environ.get("ORCH_BILLING_KEY_PRESENCE_PAUSES", "false").lower() in ("1", "true", "yes", "on")


def _maybe_resume_own_pause(findings, state=None):
    """Undo billing_guard's OWN pause once the hard condition is gone.

    Delegates to pause_arbiter, which owns typed pause/resume + TTL for the whole fleet
    (see pause_arbiter.py). billing_guard used to hand-roll this check-and-clear itself,
    which is exactly the kind of one-off logic that let the 2026-07-08 deadlock sit for
    ~10 hours with nobody re-checking; now every guard shares one arbiter and one test.

    OWNERSHIP GATE (2026-08): this used to call pause_arbiter.recheck() unconditionally on
    every clean run. recheck() lifts whatever global pause it finds metadata for — so a
    clean billing run could silently un-pause a fleet that the waste guard, the cost
    circuit, or a human STOP had paused for an entirely unrelated reason. billing_guard
    now only asks the arbiter to recheck when its own state says billing_guard is the
    caller currently holding a pause. Any pause we did not place is left strictly alone.
    """
    if findings:
        return False
    st = _load_state() if state is None else state
    if not st.get("holding_pause"):
        return False
    if st.get("pause_by") not in (None, "billing_guard"):
        return False
    try:
        import pause_arbiter
        result = pause_arbiter.recheck(scope="global")
        if result.get("action") == "lifted":
            print(f"billing_guard: {result.get('reason')}")
            return True
    except Exception:
        pass
    return False


def _file_escalation_approval(findings, cause_key, streak):
    """Exactly one material card per escalation. Fail-soft: never blocks the guard."""
    try:
        import db
        db.insert("approvals", {"project": "PORTFOLIO", "kind": "material",
            "title": f"BILLING GUARD re-tripped {streak}x on the same cause — auto-pause suspended",
            "why": (f"cause_key={cause_key}; {'; '.join(findings)}\n\n"
                    f"This identical cause has tripped {streak} times consecutively. "
                    f"billing_guard will stop re-pausing on it until a human resolves the "
                    f"root cause; re-pausing every cycle only hides the underlying problem."),
            "value": "Replaces silent infinite re-pausing with one decision a human can act on.",
            "risk": ("billing_guard is no longer auto-pausing for this cause. If it is real "
                     "direct-API spend, that spend continues until the cause is fixed."),
            "command": ""})
        return True
    except Exception:
        return False


def run():
    findings = []
    warnings = []
    key_presence_only = False
    # 1) key-leak check
    api_allowed = False
    try:
        import subscription_guard
        a = subscription_guard.audit()
        api_allowed = bool(a["api_allowed"])
        # Subscription-primary + exhaustion-only overflow legitimately RETAINS the key so
        # swarm_executor can serve the fallback (subscription_guard.overflow_enabled()).
        # Treat that as expected billing: otherwise the key reads as a leak, and the spend
        # trips the $2 subscription tripwire into a no-TTL fleet pause.
        billing_expected = api_allowed or bool(a.get("overflow"))
        if a["api_keys_present"] and not billing_expected:
            g = subscription_guard.enforce()
            msg = f"API key(s) present in env while billing blocked: {a['api_keys_present']}"
            if _strict_key_presence_pause() or not a.get("subscription_mode"):
                findings.append(msg)
                key_presence_only = True
            else:
                warnings.append(msg + f"; stripped={g.get('stripped', [])}")
    except Exception as e:
        findings.append(f"subscription_guard audit failed: {e}")
        billing_expected = False

    # 2) real billable spend check (subscription real_usd should be 0)
    real_day = 0.0
    try:
        import claude_cli
        s = claude_cli.status()
        real_day = float(s.get("usd_last_day", 0) or 0)
        trip = _trip_usd(billing_expected)
        if real_day > trip:
            findings.append(f"REAL API spend today ${real_day:.2f} > trip ${trip:.2f}")
            key_presence_only = False
    except Exception as e:
        findings.append(f"claude_cli status failed: {e}")
        key_presence_only = False

    state = _load_state()

    if not findings:
        # Cause cleared. Lift only if WE are the caller holding the pause, then drop the
        # holding flag. The streak survives a clean run on purpose: trip -> auto-resume ->
        # trip is exactly the pathological loop the escalation counter exists to catch, so
        # a single clean cycle in between must not reset it back to zero.
        resumed = _maybe_resume_own_pause(findings, state)
        if state:
            state["holding_pause"] = False
            state.pop("pause_by", None)
            _save_state(state)
        suffix = f"; warnings: {'; '.join(warnings)}" if warnings else ""
        print(f"billing_guard: clean (real API $ today ~${real_day:.2f}){suffix}")
        return {"ok": True, "real_day": real_day, "warnings": warnings, "resumed": resumed}

    # A trip. First work out whether this is the SAME cause as last time. Streaks are keyed
    # on a normalised digest of the findings, so a spend figure that drifts by a few cents
    # between cycles still counts as one repeating cause rather than a fresh incident.
    cause_key = _cause_key(findings)
    now = time.time()
    same_cause = (state.get("cause_key") == cause_key
                  and (now - float(state.get("last_trip") or 0)) <= _streak_reset_s())
    streak = int(state.get("streak") or 0) + 1 if same_cause else 1
    escalated = bool(state.get("escalated")) if same_cause else False

    # After ESCALATE_AFTER identical consecutive trips, re-pausing has stopped being useful:
    # something upstream keeps re-triggering the same condition and each new pause just buries
    # the previous one. Stop re-tripping, file exactly ONE material approval, and leave it to a
    # human. Subsequent identical trips are suppressed silently (no pause, no second card).
    if streak >= ESCALATE_AFTER:
        filed = False
        if not escalated:
            filed = _file_escalation_approval(findings, cause_key, streak)
            escalated = True
        _save_state({"cause_key": cause_key, "streak": streak, "escalated": True,
                     "holding_pause": bool(state.get("holding_pause")),
                     "pause_by": state.get("pause_by", "billing_guard"),
                     "last_trip": now})
        print(f"billing_guard: SUPPRESSED (cause_key={cause_key} tripped {streak}x; "
              f"escalated to a human, not re-pausing) ->", "; ".join(findings))
        return {"ok": False, "findings": findings, "cause_key": cause_key, "streak": streak,
                "escalated": True, "suppressed": True, "escalation_filed": filed}

    # Normal trip: pause everything + escalate. Key-presence-only trips (strict mode, or
    # subscription mode somehow off) are a self-clearing condition — route through
    # pause_arbiter with a TTL so it lifts itself the moment the key is gone, instead of
    # requiring a human to notice. Real spend / audit-failure trips are NOT auto-clearable:
    # no TTL, stays paused for a human. Every pause carries by="billing_guard" and the
    # cause_key so the arbiter — and the next billing_guard run — can tell whose pause it is.
    scoped_msg = f"[cause={cause_key}] " + "; ".join(findings)
    paused = False
    try:
        import pause_arbiter
        if key_presence_only and len(findings) == 1:
            pause_arbiter.pause("billing_key_presence", scoped_msg[:200],
                                by="billing_guard", ttl_s=900)
        else:
            pause_arbiter.pause("billing_real_spend_or_audit_failure", scoped_msg[:200],
                                by="billing_guard", ttl_s=None)
        paused = True
    except Exception:
        try:
            import kill_switch
            kill_switch.pause(scope="global", reason="billing_guard: " + scoped_msg[:200],
                              by="billing_guard")
            paused = True
        except Exception:
            pass
    try:
        import db
        db.insert("approvals", {"project": "PORTFOLIO", "kind": "material",
            "title": "DIRECT API SPEND TRIPWIRE: everything paused",
            "why": f"cause_key={cause_key}; " + "; ".join(findings),
            "value": "Stops unintended direct Anthropic API spend while preserving Claude Max subscription usage.",
            "risk": "Work is paused until you clear the cause and un-pause.",
            "command": ""})
    except Exception:
        pass
    # Record ownership: only a pause we actually placed may later be auto-resumed by us.
    _save_state({"cause_key": cause_key, "streak": streak, "escalated": False,
                 "holding_pause": paused, "pause_by": "billing_guard" if paused else None,
                 "last_trip": now})
    print("billing_guard: TRIPPED ->", "; ".join(findings))
    return {"ok": False, "findings": findings, "cause_key": cause_key, "streak": streak,
            "escalated": False, "suppressed": False}


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, default=str))
