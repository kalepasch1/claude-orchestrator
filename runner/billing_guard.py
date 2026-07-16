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
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _trip_usd(api_allowed=False):
    if api_allowed:
        return float(os.environ.get("ORCH_API_DAILY_USD_CAP",
                                    os.environ.get("BILLING_TRIP_USD", "25.0")))
    return float(os.environ.get("BILLING_TRIP_USD", "2.0"))


def _strict_key_presence_pause():
    return os.environ.get("ORCH_BILLING_KEY_PRESENCE_PAUSES", "false").lower() in ("1", "true", "yes", "on")


def _maybe_resume_own_pause(findings):
    """Undo billing_guard's own pause once the hard condition is gone.

    Delegates to pause_arbiter, which owns typed pause/resume + TTL for the whole fleet
    (see pause_arbiter.py). billing_guard used to hand-roll this check-and-clear itself,
    which is exactly the kind of one-off logic that let the 2026-07-08 deadlock sit for
    ~10 hours with nobody re-checking; now every guard shares one arbiter and one test.
    """
    if findings:
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

    if not findings:
        resumed = _maybe_resume_own_pause(findings)
        suffix = f"; warnings: {'; '.join(warnings)}" if warnings else ""
        print(f"billing_guard: clean (real API $ today ~${real_day:.2f}){suffix}")
        return {"ok": True, "real_day": real_day, "warnings": warnings, "resumed": resumed}

    # trip: pause everything + escalate. Key-presence-only trips (strict mode, or subscription
    # mode somehow off) are a self-clearing condition — route through pause_arbiter with a TTL
    # so it lifts itself the moment the key is gone, instead of requiring a human to notice.
    # Real spend / audit-failure trips are NOT auto-clearable: no TTL, stays paused for a human.
    try:
        import pause_arbiter
        if key_presence_only and len(findings) == 1:
            pause_arbiter.pause("billing_key_presence", "; ".join(findings)[:200],
                                by="billing_guard", ttl_s=900)
        else:
            pause_arbiter.pause("billing_real_spend_or_audit_failure", "; ".join(findings)[:200],
                                by="billing_guard", ttl_s=None)
    except Exception:
        try:
            import kill_switch
            kill_switch.pause(scope="global", reason="billing_guard: " + "; ".join(findings)[:200],
                              by="billing_guard")
        except Exception:
            pass
    try:
        import db
        db.insert("approvals", {"project": "PORTFOLIO", "kind": "material",
            "title": "DIRECT API SPEND TRIPWIRE: everything paused",
            "why": "; ".join(findings),
            "value": "Stops unintended direct Anthropic API spend while preserving Claude Max subscription usage.",
            "risk": "Work is paused until you clear the cause and un-pause.",
            "command": ""})
    except Exception:
        pass
    print("billing_guard: TRIPPED ->", "; ".join(findings))
    return {"ok": False, "findings": findings}


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, default=str))
