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


_WINDOW = 25      # rows pulled per stage probe

_SENTINELS = {}          # stage -> how many impossible-age rows exist in that stage
_UNMEASURABLE_WHY = {}   # stage -> why the probe could not produce a real age


def _reset_probe_state():
    """Per-snapshot bookkeeping. Module dicts that are never cleared turn a monitor into a
    log: one stage's sentinel count would still be attached to a later, unrelated run."""
    _SENTINELS.clear()
    _UNMEASURABLE_WHY.clear()


def _sane_age_h():
    try:
        return float(os.environ.get("ORCH_FUNNEL_MAX_SANE_AGE_H", "17520") or 17520)  # 2 years
    except (TypeError, ValueError):
        return 17520.0


def _sane_floor_iso(sane=None):
    """The oldest created_at/updated_at a row may carry and still be believed."""
    sane = _sane_age_h() if sane is None else sane
    return (_now() - datetime.timedelta(hours=sane)).isoformat()


def _oldest(table, params, ts_col, stage=None):
    """Age in hours of the oldest REAL item, None if the stage is genuinely empty.

    Raises nothing, but MUST distinguish three things that a single None used to collapse:
    "no rows", "could not measure", and "rows exist but every one of them is a sentinel".
    Returning None for all three let a transient DB error — or a stage full of pinned rows —
    render as a healthy dash. The funnel would report `ok` precisely when it had lost the
    ability to see anything, which is the silent-failure mode this module exists to catch.

    SENTINEL TIMESTAMPS POISON THIS METRIC (2026-08-15, corrected 2026-08-17).
    ----------------------------------------------------------------------
    The ingest stage was reporting an oldest item of 58,054.7 hours — 6.6 years, predating the
    project. One row was responsible: prompt-evolution-bandit, created_at 2020-01-01T00:00:04.
    46 tasks carry a pre-2026 date like that, and they are not corrupt — it is a deliberate
    hack, because every claim scan orders by created_at ASC, so an impossible past date pins a
    task to the front of the queue forever.

    The first fix walked past sentinels INSIDE a 25-row window. That only works while fewer
    than 25 of the 46 sentinels sit in one stage. Put 25 of them in a single state and every
    visible row is a sentinel, the skip loop falls through, and the fallback reported the 25th
    sentinel's age — 6.6 years, the exact number the fix existed to suppress. Latent today
    (2 sentinels are QUEUED), and latent is not fixed.

    So push the floor SERVER-SIDE: ask for rows at or after the sane floor, and the 25 oldest
    rows returned are the 25 oldest REAL rows no matter how many sentinels the stage holds.
    Sentinels are then counted with their own exact query rather than inferred from whatever
    happened to fit in the window, so the note reports 46 when there are 46.
    """
    stage = stage or table
    sane = _sane_age_h()
    floor = _sane_floor_iso(sane)

    # Only push the floor down when nothing else already constrains this column — two
    # predicates on one column need PostgREST's and=() form, and silently overwriting the
    # caller's filter would be a worse bug than not applying the floor.
    use_floor = ts_col not in params
    query = {**params, "select": ts_col, "order": f"{ts_col}.asc", "limit": str(_WINDOW)}
    if use_floor:
        query[ts_col] = f"gte.{floor}"

    def _sentinel_count():
        """How many rows in this stage sit below the sane floor.

        Returns -1 when the probe itself FAILED. `_count` signals failure with -1, and the
        first version of this helper folded that into 0 — which made a failed count read as
        "no sentinels", so a stage that is entirely pinned rendered as a healthy empty dash.
        That is the same fail-open shape this module exists to prevent, reintroduced one
        layer down. Unknown is not zero; the caller decides.
        """
        if not use_floor:
            return 0
        n = _count(table, {**params, ts_col: f"lt.{floor}"})
        if n is None or n < 0:
            return -1
        return n

    for attempt in range(3):                 # the shared relay rate-limits under fleet load
        try:
            rows = db.select(table, query) or []
            if not rows:
                # Empty UNDER THE FLOOR is not empty. Distinguish the two, because a stage
                # holding nothing but pinned rows is holding work, and rendering it as a
                # healthy dash is the same lie in the opposite direction.
                if use_floor:
                    n_sent = _sentinel_count()
                    if n_sent < 0:
                        # Cannot tell "genuinely empty" from "entirely pinned". Refusing to
                        # guess is the whole point: guessing empty renders a healthy dash
                        # over a stage that may be holding every task it has.
                        _UNMEASURABLE_WHY[stage] = (
                            "no rows above the sane-age floor, and the sentinel count probe "
                            "failed — cannot distinguish an empty stage from a fully pinned "
                            "one, so this is NOT reported as empty")
                        return UNMEASURABLE
                    if n_sent:
                        _SENTINELS[stage] = n_sent
                        _UNMEASURABLE_WHY[stage] = (
                            f"every row in this stage ({n_sent}) carries a pinned "
                            f"pre-{floor[:10]} timestamp — real age is unmeasurable, and the "
                            f"stage is NOT empty")
                        return UNMEASURABLE
                return None
            n_sent = _sentinel_count()
            if n_sent > 0:
                _SENTINELS[stage] = n_sent
            for row in rows:
                age = _age_h(row.get(ts_col))
                if age is UNMEASURABLE or age is None:
                    continue
                if age > sane:               # belt-and-braces if the floor did not apply
                    _SENTINELS[stage] = max(_SENTINELS.get(stage, 0), 1)
                    continue
                return age
            _UNMEASURABLE_WHY[stage] = (
                f"all {len(rows)} rows in the probe window have unusable or pinned "
                f"timestamps — real age is unmeasurable, and the stage is NOT empty")
            return UNMEASURABLE
        except Exception as e:
            if attempt == 2:
                _UNMEASURABLE_WHY[stage] = (
                    f"probe failed after 3 attempts ({type(e).__name__}) — funnel is BLIND "
                    f"for this stage")
                return UNMEASURABLE
            time.sleep(1.5 * (attempt + 1))
    _UNMEASURABLE_WHY[stage] = "probe failed after 3 attempts — funnel is BLIND for this stage"
    return UNMEASURABLE


def snapshot():
    _reset_probe_state()
    stages = []

    def add(name, table, params, ts_col, note=""):
        stages.append({
            "stage": name,
            "table": table,
            "count": _count(table, params),
            "oldest_h": _oldest(table, params, ts_col, stage=name),
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
        # Keyed by STAGE, not by table. `ingest`, `draft` and `card` all read `tasks`, so a
        # table-keyed count reported ingest's sentinels again on draft and on card — three
        # stages accusing each other of the same 46 rows.
        n_sent = _SENTINELS.get(s["stage"], 0)
        if n_sent:
            s["sentinels"] = n_sent
            s["note"] = ((s.get("note") or "") +
                         f"  [{n_sent} row(s) with an impossible created_at excluded — "
                         f"pinned-to-front sentinels, not real age]").strip()
        thr, age = s.get("threshold_h"), s.get("oldest_h")
        if age == UNMEASURABLE:
            s["healthy"] = False
            # Say WHICH kind of blindness this is: a failed probe and a stage made entirely of
            # pinned rows are both unmeasurable, and they call for different action.
            s["note"] = _UNMEASURABLE_WHY.get(
                s["stage"], "probe failed after 3 attempts — funnel is BLIND for this stage")
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
