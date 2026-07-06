#!/usr/bin/env python3
"""
billing_guard.py - independent tripwire that watches for ANY real (billable) API spend and slams the
global kill switch if it appears. Defense-in-depth behind subscription_guard: even if a key leaked in
somehow, this catches spend early instead of at invoice time.

Checks every run:
  1. Residual API keys in the env while API billing is blocked -> shouldn't happen post-enforce();
     if it does, alert (a subprocess got a key it shouldn't have).
  2. REAL billable $ from claude_cli's circuit-breaker ledger (real_usd; ~$0 in subscription mode).
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


def run():
    findings = []
    # 1) key-leak check
    api_allowed = False
    try:
        import subscription_guard
        a = subscription_guard.audit()
        api_allowed = bool(a["api_allowed"])
        if a["api_keys_present"] and not a["api_allowed"]:
            findings.append(f"API key(s) present in env while billing blocked: {a['api_keys_present']}")
    except Exception as e:
        findings.append(f"subscription_guard audit failed: {e}")

    # 2) real billable spend check (subscription real_usd should be 0)
    real_day = 0.0
    try:
        import claude_cli
        s = claude_cli.status()
        real_day = float(s.get("usd_last_day", 0) or 0)
        trip = _trip_usd(api_allowed)
        if real_day > trip:
            findings.append(f"REAL API spend today ${real_day:.2f} > trip ${trip:.2f}")
    except Exception as e:
        findings.append(f"claude_cli status failed: {e}")

    if not findings:
        print(f"billing_guard: clean (real API $ today ~${real_day:.2f})")
        return {"ok": True, "real_day": real_day}

    # trip: pause everything + escalate
    try:
        import kill_switch
        kill_switch.pause(scope="global", reason="billing_guard: " + "; ".join(findings)[:200],
                          by="billing_guard")
    except Exception:
        pass
    try:
        import db
        db.insert("approvals", {"project": "PORTFOLIO", "kind": "material",
            "title": "BILLING TRIPWIRE: real API spend/key detected — everything paused",
            "why": "; ".join(findings),
            "value": "Stops a repeat of the ~$500 API invoice at the first sign of billable spend.",
            "risk": "Work is paused until you clear the cause and un-pause.",
            "command": ""})
    except Exception:
        pass
    print("billing_guard: TRIPPED ->", "; ".join(findings))
    return {"ok": False, "findings": findings}


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, default=str))
