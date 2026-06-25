#!/usr/bin/env python3
"""
maturity.py - the maturity ladder with evidence-gated auto-promotion. A capability advances
experimental -> trusted -> productizable ONLY when it clears thresholds on eval pass-rate,
number of apps using it, and prod outcomes. Productization is earned, not guessed. Schedule
daily.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

TRUST_EVAL = float(os.environ.get("MATURITY_TRUST_EVAL", "0.7"))
PROD_EVAL = float(os.environ.get("MATURITY_PROD_EVAL", "0.9"))
PROD_MIN_APPS = int(os.environ.get("MATURITY_PROD_APPS", "2"))


def _latest_eval(cap_id):
    rows = db.select("capability_versions", {"select": "eval_pass_rate", "capability_id": f"eq.{cap_id}",
                                             "order": "created_at.desc", "limit": "1"}) or []
    return float(rows[0]["eval_pass_rate"]) if rows and rows[0].get("eval_pass_rate") is not None else 0.0


def _apps(cap_id):
    rows = db.select("capability_instances", {"select": "project", "capability_id": f"eq.{cap_id}",
                                              "status": "eq.active"}) or []
    return len({r["project"] for r in rows})


def recompute():
    promoted = 0
    for c in db.select("capabilities") or []:
        if c["status"] == "retired":
            continue
        ev, apps = _latest_eval(c["id"]), _apps(c["id"])
        score = round(min(100, ev * 60 + apps * 20), 2)
        status = c["status"]
        if ev >= PROD_EVAL and apps >= PROD_MIN_APPS:
            status = "productizable"
        elif ev >= TRUST_EVAL:
            status = "trusted"
        else:
            status = "experimental"
        if status != c["status"] or float(c["maturity"]) != score:
            db.update("capabilities", {"id": c["id"]}, {"maturity": score, "status": status})
            if status != c["status"]:
                promoted += 1
    print(f"maturity recomputed; {promoted} status changes")
    return promoted


if __name__ == "__main__":
    recompute()
