#!/usr/bin/env python3
"""Novelty and downstream-capacity controls for self-improvement drafting."""
import os
import re

REVIEW_CAP = int(os.environ.get("IMPROVE_REVIEW_BACKLOG_CAP", "25"))
BUILD_CAP = int(os.environ.get("IMPROVE_BUILD_BACKLOG_CAP", "12"))
NOVELTY_THRESHOLD = float(os.environ.get("IMPROVE_NOVELTY_THRESHOLD", "0.58"))


def _tokens(value):
    stop = {"the", "and", "for", "with", "that", "from", "into", "using", "improve", "improvement"}
    aliases = {"dollar": "cost", "dollars": "cost", "deployment": "deploy",
               "deployed": "deploy", "deployments": "deploy", "routing": "route",
               "routes": "route", "rank": "select", "optimize": "select"}
    out = set()
    for token in re.findall(r"[a-z0-9]+", str(value or "").lower()):
        token = aliases.get(token, token)
        if token.endswith("ies") and len(token) > 5:
            token = token[:-3] + "y"
        elif token.endswith("s") and not token.endswith("ss") and len(token) > 4:
            token = token[:-1]
        token = aliases.get(token, token)
        if len(token) >= 3 and token not in stop:
            out.add(token)
    return out


def similarity(left, right):
    a, b = _tokens(left), _tokens(right)
    return len(a & b) / len(a | b) if a and b else 0.0


def idea_text(idea):
    return " ".join(str(idea.get(k) or "") for k in ("title", "current_state", "proposal", "rationale"))


def novel(idea, existing, threshold=NOVELTY_THRESHOLD):
    text = idea_text(idea)
    best = (None, 0.0)
    for item in existing or []:
        score = similarity(text, idea_text(item))
        if score > best[1]:
            best = (item.get("id") or item.get("title"), score)
    return {"novel": best[1] < threshold, "nearest": best[0], "similarity": round(best[1], 4)}


LOW_WATER_PCT = float(os.environ.get("IMPROVE_BACKLOG_LOW_WATER_PCT", "0.8"))
_LATCH_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", ".runtime", "improve_capacity_latch.json")


def _backlog(database, table, params, cap):
    """Exact backlog depth. Falls back to a capped probe if count() is unavailable.

    The old implementation only ever issued select(..., limit=cap+1), so the
    backlog could never be reported as deeper than cap+1 no matter how far
    behind the pipeline actually was. That made a 393-deep build queue look
    like "13 / cap 12" -- indistinguishable from being over by one, and it hid
    the real magnitude of the stall from every operator who looked at it.
    """
    try:
        return int(database.count(table, dict(params)))
    except Exception:
        try:
            probe = dict(params)
            probe["select"] = "id"
            probe["limit"] = str(cap + 1)
            return len(database.select(table, probe) or [])
        except Exception:
            return 0


def _read_latch():
    try:
        import json
        with open(_LATCH_PATH) as fh:
            return bool(json.load(fh).get("limited"))
    except Exception:
        return False


def _write_latch(limited):
    try:
        import json
        os.makedirs(os.path.dirname(_LATCH_PATH), exist_ok=True)
        with open(_LATCH_PATH, "w") as fh:
            json.dump({"limited": bool(limited)}, fh)
    except Exception:
        pass


def capacity(database):
    """Downstream capacity for drafting new improvement proposals.

    Hysteresis: once the backlog trips a cap the gate latches shut and only
    reopens when the backlog has fallen to LOW_WATER_PCT of cap. Without that
    band the gate reopens the instant one item drains, the miner immediately
    drafts a replacement, and the backlog snaps straight back to cap -- an
    edge-triggered flap that keeps the pipeline pinned at its ceiling forever
    instead of letting it actually drain.
    """
    review_backlog = _backlog(database, "improvement_proposals",
                              {"status": "eq.for_review"}, REVIEW_CAP)
    build_backlog = _backlog(database, "tasks",
                             {"slug": "like.improve-%",
                              "state": "in.(QUEUED,RUNNING,RETRY,DECOMPOSED)"}, BUILD_CAP)

    review_slots = max(0, REVIEW_CAP - review_backlog)
    build_slots = max(0, BUILD_CAP - build_backlog)
    slots = min(review_slots, build_slots)

    was_limited = _read_latch()
    if was_limited:
        # Stay shut until the backlog drains to the low-water mark.
        reopen = (review_backlog <= REVIEW_CAP * LOW_WATER_PCT
                  and build_backlog <= BUILD_CAP * LOW_WATER_PCT)
        limited = not reopen
    else:
        limited = slots <= 0
    if limited != was_limited:
        _write_latch(limited)
    if limited:
        slots = 0

    return {"slots": slots, "review_backlog": review_backlog, "build_backlog": build_backlog,
            "review_cap": REVIEW_CAP, "build_cap": BUILD_CAP,
            "review_low_water": round(REVIEW_CAP * LOW_WATER_PCT, 2),
            "build_low_water": round(BUILD_CAP * LOW_WATER_PCT, 2),
            "limited": limited}
