#!/usr/bin/env python3
"""
cx_persona_lifecycle.py - identify chronically-wrong and consistently-right expert archetypes
from committee_scoreboard + seat_calibration, and PROPOSE retiring or promoting them into the
triage default pool as an owner-ratifiable approval card. Never auto-changes the roster.
Advisory only; no schema change; does not edit committees.py.
"""
import os, sys, json, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

MIN_CALLS = int(os.environ.get("PERSONA_MIN_CALLS", "5"))
LOW_ACC_THRESHOLD = float(os.environ.get("PERSONA_LOW_ACC", "0.35"))
HIGH_ACC_THRESHOLD = float(os.environ.get("PERSONA_HIGH_ACC", "0.75"))


def _seat_stats():
    """Merge scoreboard + calibration into per-seat stats."""
    sb = db.select("committee_scoreboard", {
        "select": "committee,seat,accuracy,calls,brier",
        "entity_type": "eq.seat",
    }) or []
    cal = db.select("seat_calibration", {
        "select": "committee,seat,weight,n",
    }) or []
    cal_map = {}
    for c in cal:
        key = (c.get("committee", ""), c.get("seat", ""))
        cal_map[key] = {"weight": c.get("weight", 1.0), "n": c.get("n", 0)}

    seats = []
    for s in sb:
        key = (s.get("committee", ""), s.get("seat", ""))
        calls = s.get("calls") or 0
        if calls < MIN_CALLS:
            continue
        accuracy = s.get("accuracy") or 0.0
        brier = s.get("brier") or 0.0
        cdata = cal_map.get(key, {})
        seats.append({
            "committee": s.get("committee", ""),
            "seat": s.get("seat", ""),
            "accuracy": accuracy,
            "brier": brier,
            "calls": calls,
            "weight": cdata.get("weight", 1.0),
            "cal_n": cdata.get("n", 0),
        })
    return seats


def _classify(seats):
    """Split seats into retire-candidates and promote-candidates."""
    retire, promote = [], []
    for s in seats:
        if s["accuracy"] < LOW_ACC_THRESHOLD and s["brier"] > 0.3:
            retire.append(s)
        elif s["accuracy"] > HIGH_ACC_THRESHOLD and s["brier"] < 0.2:
            promote.append(s)
    retire.sort(key=lambda x: x["accuracy"])
    promote.sort(key=lambda x: x["accuracy"], reverse=True)
    return retire, promote


def _format_entry(s):
    return (f"{s['committee']}/{s['seat']}: "
            f"acc={s['accuracy']:.2f} brier={s['brier']:.2f} "
            f"calls={s['calls']} weight={s['weight']:.2f}")


def run():
    seats = _seat_stats()
    if not seats:
        return {"status": "no_data", "detail": "no seat scoreboard entries with enough calls"}

    retire, promote = _classify(seats)
    if not retire and not promote:
        return {"status": "ok", "detail": "no archetypes currently flagged for retirement or promotion"}

    lines = []
    if retire:
        lines.append("## Retire candidates (low accuracy, high Brier)")
        for s in retire[:10]:
            lines.append(f"- {_format_entry(s)}")
    if promote:
        lines.append("## Promote candidates (high accuracy, low Brier)")
        for s in promote[:10]:
            lines.append(f"- {_format_entry(s)}")

    body = "\n".join(lines)

    db.insert("approvals", {
        "kind": "material",
        "status": "pending",
        "title": "Expert persona lifecycle review",
        "why": body[:3000],
        "project": "beethoven",
        "created_at": datetime.datetime.utcnow().isoformat() + "Z",
    })

    return {
        "status": "proposed",
        "retire_count": len(retire),
        "promote_count": len(promote),
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
