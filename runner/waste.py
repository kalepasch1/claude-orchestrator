#!/usr/bin/env python3
"""
waste.py - "spend with nothing to show for it" detector. The $400 incident was an
autonomous loop that burned money and improved NOTHING. This guard catches that
pattern early, per-project, and pauses + files an approval the moment it appears.

Two signatures, both checked on a rolling window:
  1. SPEND-NO-SHIP : >= WASTE_USD spent in the window but ZERO merged/integrated outcomes.
  2. REPEAT-FAIL   : the last WASTE_STREAK outcomes all failed (no tests pass, no integrate).

It only blocks the offending project (not the whole fleet), so healthy projects keep moving.
Tunable via env: WASTE_USD (default 5), WASTE_WINDOW_HOURS (6), WASTE_STREAK (5).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

WASTE_USD = float(os.environ.get("WASTE_USD", "5"))
WINDOW_H = float(os.environ.get("WASTE_WINDOW_HOURS", "6"))
STREAK = int(os.environ.get("WASTE_STREAK", "5"))


def _recent(project, limit=50):
    import datetime
    since = (datetime.datetime.utcnow() - datetime.timedelta(hours=WINDOW_H)).isoformat()
    return db.select("outcomes", {
        "select": "usd,integrated,tests_passed,created_at",
        "project": f"eq.{project}", "created_at": f"gte.{since}",
        "order": "created_at.desc", "limit": str(limit)}) or []


def check(project):
    """Return a human-readable waste reason, or None if the project looks productive."""
    try:
        rows = _recent(project)
    except Exception:
        return None  # never block on a telemetry hiccup
    if not rows:
        return None
    spent = sum(float(r.get("usd") or 0) for r in rows)
    shipped = sum(1 for r in rows if r.get("integrated"))
    # 1) money out, nothing shipped. Only meaningful when REAL dollars are billed (paid API).
    # In subscription mode `usd` is a phantom equivalent, so a $-spend trigger would false-fire;
    # the REPEAT-FAIL signal below catches unproductive loops in the costless case.
    subscription = os.environ.get("ORCH_USE_SUBSCRIPTION", "true").lower() == "true"
    if (not subscription) and spent >= WASTE_USD and shipped == 0:
        return (f"${spent:.2f} spent in the last {WINDOW_H:.0f}h on '{project}' with "
                f"0 merged changes - pausing to avoid a no-value spend loop.")
    # 2) a streak of pure failures (regardless of spend)
    last = rows[:STREAK]
    if len(last) >= STREAK and all(
            (not r.get("integrated")) and (not r.get("tests_passed")) for r in last):
        return (f"Last {STREAK} runs on '{project}' all failed (no tests passing, "
                f"nothing merged) - pausing before more spend.")
    return None


if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else "tomorrow"
    print(check(p) or f"{p}: no waste detected")
