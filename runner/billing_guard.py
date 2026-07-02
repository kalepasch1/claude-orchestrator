#!/usr/bin/env python3
"""
billing_guard.py - independent tripwire that watches for ANY real (billable) API spend and slams the
global kill switch if it appears. Defense-in-depth behind subscription_guard: even if a key leaked in
somehow, this catches spend early instead of at invoice time.

Checks every run:
  1. Residual API keys in the env while API billing is blocked -> shouldn't happen post-enforce();
     if it does, alert (a subprocess got a key it shouldn't have).
  2. REAL billable $ from claude_cli's circuit-breaker ledger (real_usd; ~$0 in subscription mode).
     If real spend today exceeds BILLING_TRIP_USD, PAUSE everything and file a material approval.

This is intentionally a near-zero threshold ($2 default): on Max subscriptions real API $ should be
$0, so any real spend at all is an anomaly worth stopping for. Schedule every ~5 min; safe when paused
(it only reads + can pause, never spends).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TRIP_USD = float(os.environ.get("BILLING_TRIP_USD", "2.0"))


def run():
    findings = []
    # 1) key-leak check
    try:
        import subscription_guard
        a = subscription_guard.audit()
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
        if real_day > TRIP_USD:
            findings.append(f"REAL API spend today ${real_day:.2f} > trip ${TRIP_USD:.2f}")
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
