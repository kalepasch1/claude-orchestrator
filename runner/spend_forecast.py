#!/usr/bin/env python3
"""
spend_forecast.py - catch a runaway in minutes, not at invoice time. Projects end-of-day spend from the
current burn rate and alerts BEFORE a threshold is crossed (the opposite of the June invoice, which was
only visible after the fact).

Tracks TWO numbers:
  * REAL billable $ (claude_cli circuit-breaker ledger + key_broker ledger) — should be ~$0 on Max.
  * NOTIONAL subscription-equivalent $ (provider_usage) — for visibility / efficiency, not billing.

If projected real $/day would exceed FORECAST_REAL_TRIP (default $3), it PAUSES (defense-in-depth with
billing_guard). If projected notional is anomalously high vs the trailing baseline, it just alerts (free
work, but a spike often signals a loop). Schedule every ~10 min.
"""
import os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

FORECAST_REAL_TRIP = float(os.environ.get("FORECAST_REAL_TRIP", "3.0"))
NOTIONAL_SPIKE_X = float(os.environ.get("NOTIONAL_SPIKE_X", "3.0"))


def _seconds_into_day():
    now = datetime.datetime.utcnow()
    return max(60, (now - now.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds())


def _real_today():
    real = 0.0
    try:
        import claude_cli
        real += float(claude_cli.status().get("usd_last_day", 0) or 0)
    except Exception:
        pass
    try:
        import key_broker
        real += float(key_broker._today_spend())
    except Exception:
        pass
    return real


def _notional_today():
    rows = db.select("provider_usage",
                     {"select": "usd", "created_at": f"gte.{datetime.date.today().isoformat()}"}) or []
    return sum(float(r.get("usd") or 0) for r in rows)


def _notional_baseline():
    """Avg daily notional over the prior 7 days (excludes today)."""
    start = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    end = datetime.date.today().isoformat()
    rows = db.select("provider_usage", {"select": "usd,created_at",
                                        "created_at": f"gte.{start}"}) or []
    days = {}
    for r in rows:
        d = (r.get("created_at") or "")[:10]
        if d and d < end:
            days[d] = days.get(d, 0) + float(r.get("usd") or 0)
    return (sum(days.values()) / len(days)) if days else 0.0


def run():
    frac = _seconds_into_day() / 86400.0
    real = _real_today()
    proj_real = real / frac
    notional = _notional_today()
    proj_notional = notional / frac
    base = _notional_baseline()
    alerts = []

    if proj_real > FORECAST_REAL_TRIP:
        alerts.append(f"projected REAL API ${proj_real:.2f}/day > trip ${FORECAST_REAL_TRIP}")
        try:
            import kill_switch
            kill_switch.pause(scope="global", reason=f"spend_forecast: real ${proj_real:.2f}/day projected",
                              by="spend_forecast")
        except Exception:
            pass
    if base > 0 and proj_notional > base * NOTIONAL_SPIKE_X:
        alerts.append(f"notional spike: projected ${proj_notional:.0f}/day vs baseline ${base:.0f} "
                      f"(>{NOTIONAL_SPIKE_X}x) — possible loop")

    if alerts:
        db.insert("approvals", {"project": "PORTFOLIO",
                  "kind": "material" if proj_real > FORECAST_REAL_TRIP else "self",
                  "title": "Spend forecast alert", "why": "; ".join(alerts),
                  "value": "Catch a runaway before it lands on an invoice.",
                  "risk": "Real-$ projection also paused the fleet." if proj_real > FORECAST_REAL_TRIP
                          else "Notional spike is free but often signals a loop.", "command": ""})
    print(f"spend_forecast: real today ${real:.2f} (proj ${proj_real:.2f}), "
          f"notional ${notional:.0f} (proj ${proj_notional:.0f}, base ${base:.0f}); {len(alerts)} alert(s)")
    return {"real_today": real, "proj_real": proj_real, "proj_notional": proj_notional, "alerts": alerts}


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, default=str))
