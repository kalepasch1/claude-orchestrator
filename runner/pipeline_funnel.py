#!/usr/bin/env python3
"""
pipeline_funnel.py — one metric that answers "is work actually flowing?"

WHY (2026-08-06)
----------------
Every failure in the 2026-08-06 session was invisible for hours-to-months, and each was
invisible for the SAME reason: the fleet measured activity, not flow. Counters went up
the whole time work was stranded.

  * The merge train idled with ZERO undecided cards while 191 tasks sat at DONE — for
    months. Nothing compared the two numbers.
  * `tomorrow` production failed to build for ~8 hours, 20+ consecutive red deploys.
  * Completed recovery work waited 13 days because a guard skipped it before carding.
  * DB transport was blocked for 5 hours and the fleet looked "idle" rather than broken.

A funnel with AGE-OF-OLDEST per stage surfaces all four in minutes, because a stalled
stage shows a growing oldest-item age even when throughput looks normal elsewhere. Counts
alone cannot do this: a stage can process 300 items/hour and still have one item stuck for
two weeks.

STAGES
  ingest  QUEUED            work accepted, not started
  draft   RUNNING           an agent is working
  card    DONE              finished, waiting for an integration card  <-- the silent killer
  merge   undecided cards   carded, waiting for the train
  deploy  MERGED            landed; deploy health is checked separately

Usage:
    python3 pipeline_funnel.py            # human table
    python3 pipeline_funnel.py --json     # machine readable
    python3 pipeline_funnel.py --check    # exit 1 if any stage breaches its threshold
"""
import datetime
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# A stage is UNHEALTHY when its oldest item is older than this. Deliberately generous:
# these are "something is structurally wrong", not "we are busy".
# Sentinel: the probe FAILED (not "stage is empty"). Rendered distinctly and always unhealthy,
# so a monitor that has gone blind can never masquerade as a healthy one.
UNMEASURABLE = "unmeasurable"

THRESHOLD_H = {
    "ingest": float(os.environ.get("ORCH_FUNNEL_INGEST_H", "72")),
    "draft":  float(os.environ.get("ORCH_FUNNEL_DRAFT_H", "6")),
    "card":   float(os.environ.get("ORCH_FUNNEL_CARD_H", "4")),
    "merge":  float(os.environ.get("ORCH_FUNNEL_MERGE_H", "4")),
}


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _age_h(ts):
    """Hours since `ts`. Returns UNMEASURABLE if it cannot be parsed — never a silent None.

    Python 3.9's datetime.fromisoformat only accepts exactly 3 or 6 fractional-second digits.
    Postgres emits however many it has, so a timestamp like
    '2026-08-04T01:59:47.94499+00:00' (FIVE digits) raised ValueError, was swallowed, and the
    stage rendered as an empty '-' that read as healthy. That is how a stage holding 132 items
    for four days displayed as 'ok'. Normalise the fraction to 6 digits before parsing.
    """
    if not ts:
        return None
    raw = str(ts).replace("Z", "+00:00")
    m = re.match(r"^(.*?)\.(\d+)(.*)$", raw)
    if m:
        frac = (m.group(2) + "000000")[:6]
        raw = f"{m.group(1)}.{frac}{m.group(3)}"
    try:
        t = datetime.datetime.fromisoformat(raw)
        if t.tzinfo is None:
            t = t.replace(tzinfo=datetime.timezone.utc)
        return round((_now() - t).total_seconds() / 3600.0, 1)
    except Exception:
        return UNMEASURABLE


def _count(table, params):
    """Exact row count without pulling rows (PostgREST count=exact via db.count when present)."""
    try:
        if hasattr(db, "count"):
            return db.count(table, params)
    except Exception:
        pass
    try:                       # fall back to a bounded select
        rows = db.select(table, {**params, "select": "id", "limit": "1000"}) or []
        return len(rows)
    except Exception:
        return -1


def _oldest(table, params, ts_col):
    """Age in hours of the oldest item, None if the stage is genuinely empty.

    Raises nothing, but MUST distinguish "no rows" from "could not measure". Returning None
    for both let a transient DB error render as a healthy dash — the funnel would report `ok`
    precisely when it had lost the ability to see anything, which is the silent-failure mode
    this module exists to catch. A failed probe now returns the sentinel below and is treated
    as unhealthy.
    """
    for attempt in range(3):                 # the shared relay rate-limits under fleet load
        try:
            rows = db.select(table, {**params, "select": ts_col, "order": f"{ts_col}.asc",
                                     "limit": "1"}) or []
            return _age_h(rows[0].get(ts_col)) if rows else None
        except Exception:
            if attempt == 2:
                return UNMEASURABLE
            time.sleep(1.5 * (attempt + 1))
    return UNMEASURABLE


def snapshot():
    stages = []

    def add(name, table, params, ts_col, note=""):
        stages.append({
            "stage": name,
            "count": _count(table, params),
            "oldest_h": _oldest(table, params, ts_col),
            "threshold_h": THRESHOLD_H.get(name),
            "note": note,
        })

    add("ingest", "tasks", {"state": "eq.QUEUED"}, "created_at")
    add("draft",  "tasks", {"state": "eq.RUNNING"}, "updated_at")
    add("card",   "tasks", {"state": "eq.DONE"}, "updated_at",
        "finished work with no integration card is the failure that hid for months")
    # THE MONITOR WAS COUNTING THE WRONG THING (fixed 2026-08-06).
    #
    # This counted approvals with decided_by IS NULL. But ensure_integration_card stamps every
    # card it creates with decided_by="canonical-train:sweeper" — an ATTRIBUTION marker naming
    # who queued it, written at CREATION time, not a verdict. So a correctly filed, completely
    # unprocessed card has a non-null decided_by and was invisible here. This stage read 0 no
    # matter how many cards existed, which made the "stranded" invariant below fire permanently
    # whenever any DONE task existed — that is, always.
    #
    # Measured today: the sweeper fix took stranded DONE-without-approvals from 43 to 8 and put
    # 189 cards in front of the train, and this monitor went on reporting "183 tasks finished
    # but 0 cards exist". A monitor that cries stall through a working pipeline trains everyone
    # to ignore it, which is the same failure as one that stays green through an outage.
    #
    # merge_train._pick_cards already carries the correct definition and the scar tissue
    # explaining it: only the train's own outcome prefixes mean a card has been examined. Use
    # the same predicate so the monitor and the thing it monitors cannot drift apart.
    _skip = ("merge-handler", "train", "auto-policy")
    try:
        import merge_train as _mt
        _skip = _mt.SKIP_PREFIXES
        _kinds = ",".join(_mt.MERGE_KINDS)
    except Exception:
        _kinds = "verify,material,integrate"
    _undecided = "or=(decided_by.is.null,and({}))".format(
        ",".join(f"decided_by.not.like.{pfx}*" for pfx in _skip))
    _k, _v = _undecided.split("=", 1)
    add("merge", "approvals",
        {"status": "eq.approved", "kind": f"in.({_kinds})", _k: _v}, "created_at")

    merged_24h = _count("tasks", {
        "state": "eq.MERGED",
        "updated_at": f"gt.{(_now() - datetime.timedelta(hours=24)).isoformat()}",
    })

    for s in stages:
        thr, age = s.get("threshold_h"), s.get("oldest_h")
        if age == UNMEASURABLE:
            s["healthy"] = False
            s["note"] = "probe failed after 3 attempts — funnel is BLIND for this stage"
        else:
            s["healthy"] = not (thr and age is not None and age > thr)

    # THE INVARIANT THAT WAS MISSING: finished work with nothing queued to integrate it.
    card_stage = next(s for s in stages if s["stage"] == "card")
    merge_stage = next(s for s in stages if s["stage"] == "merge")
    stranded = card_stage["count"] > 0 and merge_stage["count"] == 0
    if stranded:
        card_stage["healthy"] = False
        card_stage["note"] = (f"STRANDED: {card_stage['count']} tasks finished but 0 cards exist "
                              f"— the train has nothing to merge")

    return {
        "generated_at": _now().isoformat(),
        "stages": stages,
        "merged_24h": merged_24h,
        "stranded": stranded,
        "healthy": all(s["healthy"] for s in stages),
    }


def main():
    snap = snapshot()
    if "--json" in sys.argv:
        print(json.dumps(snap, indent=2))
    else:
        print(f"pipeline funnel @ {snap['generated_at'][:19]}   merged/24h={snap['merged_24h']}")
        print(f"{'stage':<8}{'count':>8}{'oldest':>10}{'limit':>8}  status")
        for s in snap["stages"]:
            age = ("-" if s["oldest_h"] is None
                   else "ERR" if s["oldest_h"] == UNMEASURABLE else f"{s['oldest_h']}h")
            thr = "-" if not s["threshold_h"] else f"{s['threshold_h']:.0f}h"
            print(f"{s['stage']:<8}{s['count']:>8}{age:>10}{thr:>8}  "
                  f"{'ok' if s['healthy'] else 'STALLED'}"
                  + (f"  {s['note']}" if s["note"] and not s["healthy"] else ""))
        if not snap["healthy"]:
            print("\nunhealthy — a stage is holding work past its limit")
    if "--check" in sys.argv and not snap["healthy"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
