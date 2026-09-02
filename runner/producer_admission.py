#!/usr/bin/env python3
"""A producer that files work nobody merges loses its quota. Any producer, any vendor.

THE PROBLEM
-----------
Over 30 days this fleet created 5,224 tasks and never attempted 3,980 of them (76%).
The reasons those 3,980 never ran:

    other                                    1,217
    work already existed                       934
    branch lost                                657
    sliced / collapsed into another task        621
    deduped as a duplicate                     320
    (no note at all)                           199
    project retired or paused                   31
    parked as near-zero value                    1

A third of them -- 1,254 -- were filed for work that already existed or duplicated
another task. The clearest single offender was an external intake labelled "ChatGPT
local-build audit (operator-directed)":

    tasks filed                    1,920      (249 in the last 24h alone)
    reached MERGED                   138      (7.2%)
    reached DEPLOYED_AND_VERIFIED      0
    QUARANTINED                      583
    SUPERSEDED (duplicates)          509

but it was never only that one: 47 distinct self-asserted producer labels were filing
into this queue.

WHY A RATE LIMIT IS THE WRONG SHAPE
-----------------------------------
A cap of N/day punishes a good producer as hard as a bad one and needs re-tuning per
vendor forever. The gate is outcome-based instead, and self-correcting: a producer's
quota returns as soon as its own numbers do. Nothing here names a vendor.

WHY THE SIGNAL IS REDUNDANCY AND NOT MERGE RATE
-----------------------------------------------
Merge rate was the obvious choice and it is the wrong one. Measured over the same 14
days, the WHOLE fleet merged 9 of 1,546 filed tasks (0.6%) -- because nine projects were
paused, the machine was swap-thrashing, and several gates were blaming candidates for
their base branch's state. Against a 10% merge floor that would have throttled almost
every producer, including the good ones, for a fault that was the fleet's and not theirs.
That is the same mistake as recording an out-of-memory build as a failed test.

Redundancy does not have that defect. It measures whether a producer files work the fleet
ALREADY HAS -- superseded, deduped, "already integrated", "already delivered" -- and that
is true regardless of whether anything is merging this week:

    producer                                    filed  merged  redundant
    ChatGPT local-build audit (operator...)       588       3      59.0%
    slug:recover-missing                          154       1      64.3%
    slug:log-p1                                   284       1      39.8%
    slug:chatgpt-local                            182       1      12.6%
    slug:backlog-batch                             41       0       2.4%

backlog-batch merged nothing either, but only 2.4% of what it filed was redundant -- it
is a well-behaved producer in a broken fleet, and a merge-rate gate would have condemned
it. The three offenders are filing work the fleet already had between 40% and 64% of the
time. That is the distinction worth acting on.

The exact-slug dedupe already in db.insert does not catch this: these producers mint a
fresh hash per task, so 509 substantive duplicates arrived under 509 distinct slugs.

DELIBERATE LIMITS
-----------------
* Verdicts are cached in-process for ORCH_PRODUCER_STATS_TTL_S so the insert path stays
  cheap; the DB is read at most once per producer per TTL.
* FAILS OPEN on every error. A gate that cannot read its evidence must not become a
  silent queue outage -- the whole point of this session was removing machinery that
  turned its own faults into verdicts about other people's work.
* Operator-origin rows never reach here (db.insert checks that first), and that check now
  requires evidence rather than a self-written label.
"""
import os
import time

#: producer key -> (verdict dict, expiry timestamp)
_CACHE = {}

#: Tasks a producer must have filed before its record means anything. Below this, one
#: unlucky week would throttle a new intake before it had a chance to behave.
DEFAULT_MIN_SAMPLE = 50
#: Share of output that may be work the fleet already had. The measured offenders sit at
#: 52-64%; the well-behaved producer measured 2.4%.
DEFAULT_REDUNDANT_CEILING = 0.35
#: What a throttled producer may still file per day. Rationed, not silenced.
DEFAULT_THROTTLED_DAILY_CAP = 25
#: How much history the verdict considers.
DEFAULT_WINDOW_DAYS = 14
#: How long a verdict is cached, to keep the insert path off the database.
DEFAULT_STATS_TTL_S = 600.0
#: Floor on the cache TTL, so a misconfiguration cannot put a query on every insert.
MIN_STATS_TTL_S = 30.0
#: PostgREST page size for the two reads in this module.
PAGE_SIZE = 1000
#: Upper bound on rows a single verdict will weigh.
VERDICT_ROW_LIMIT = 2000
SECONDS_PER_DAY = 86400
#: Producer keys are truncated so one absurd label cannot bloat the cache.
LABEL_KEY_CHARS = 120
#: Slug segments used to group an unlabelled producer into one family.
SLUG_KEY_SEGMENTS = 2


def _f(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def _i(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return int(default)


def enabled():
    return os.environ.get("ORCH_PRODUCER_ADMISSION", "true").strip().lower() \
        not in ("0", "false", "no", "off")


def min_sample():
    """Tasks a producer must have filed before its merge rate means anything."""
    return max(1, _i("ORCH_PRODUCER_MIN_SAMPLE", DEFAULT_MIN_SAMPLE))


def redundant_ceiling():
    """Share of a producer's output that may be work the fleet already had."""
    return max(0.0, _f("ORCH_PRODUCER_REDUNDANT_CEILING", DEFAULT_REDUNDANT_CEILING))


def daily_cap():
    """How many tasks a throttled producer may still file per day."""
    return max(0, _i("ORCH_PRODUCER_THROTTLED_DAILY_CAP", DEFAULT_THROTTLED_DAILY_CAP))


def window_days():
    return max(1, _i("ORCH_PRODUCER_WINDOW_DAYS", DEFAULT_WINDOW_DAYS))


def ttl_s():
    return max(MIN_STATS_TTL_S, _f("ORCH_PRODUCER_STATS_TTL_S", DEFAULT_STATS_TTL_S))


def producer_key(row):
    """Who filed this. Falls back to the slug's family so unlabelled producers still group.

    Returns "" when nothing identifies the caller, which means "not attributable" and is
    always admitted -- guessing an identity would throttle the wrong thing.
    """
    if not isinstance(row, dict):
        return ""
    label = str(row.get("submitted_by_label") or "").strip()
    if label:
        return "label:" + label[:LABEL_KEY_CHARS]
    slug = str(row.get("slug") or "").strip()
    if not slug:
        return ""
    # "chatgpt-local-reconcile-tomorrow-3ac28eed" -> "chatgpt-local-reconcile".
    # Two segments is enough to separate intakes without splitting one into many.
    parts = [p for p in slug.split("-") if p]
    if len(parts) < SLUG_KEY_SEGMENTS:
        return ""
    return "slug:" + "-".join(parts[:SLUG_KEY_SEGMENTS])


#: Notes and states that mean "the fleet already had this". Deliberately broad: a false
#: positive costs one task's worth of quota, a false negative is the flood this prevents.
_REDUNDANT_STATES = ("SUPERSEDED",)
_REDUNDANT_MARKERS = (
    "duplicate", "dedupe", "already exist", "already integrated", "already delivered",
    "already completed", "already present", "collapsed into", "semantic-dedupe",
)


def _is_redundant(row):
    """True when this task turned out to be work the fleet already had."""
    if str((row or {}).get("state") or "") in _REDUNDANT_STATES:
        return True
    note = str((row or {}).get("note") or "").lower()
    return any(marker in note for marker in _REDUNDANT_MARKERS)


def _measure(key, db):
    """Read this producer's recent record. Returns None when it cannot be measured."""
    field, value = key.split(":", 1)
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                          time.gmtime(time.time() - window_days() * SECONDS_PER_DAY))
    query = {"select": "state,note,created_at", "created_at": f"gte.{since}",
             "limit": str(VERDICT_ROW_LIMIT)}
    if field == "label":
        query["submitted_by_label"] = f"eq.{value}"
    else:
        query["slug"] = f"like.{value}*"
    rows = db.select("tasks", query) or []
    if not rows:
        return None
    filed = len(rows)
    merged = sum(1 for r in rows
                 if str(r.get("state") or "") in ("MERGED", "DEPLOYED_AND_VERIFIED"))
    redundant = sum(1 for r in rows if _is_redundant(r))
    day_ago = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - SECONDS_PER_DAY))
    last_24h = sum(1 for r in rows if str(r.get("created_at") or "") >= day_ago)
    return {"filed": filed, "merged": merged, "redundant": redundant,
            "last_24h": last_24h,
            "rate": (merged / float(filed)) if filed else 0.0,
            "redundant_rate": (redundant / float(filed)) if filed else 0.0}


def verdict(row, db=None):
    """(admit: bool, reason: str). Never raises; admits on any doubt."""
    if not enabled():
        return True, ""
    key = producer_key(row)
    if not key:
        return True, ""
    now = time.time()
    cached = _CACHE.get(key)
    if cached and cached[1] > now:
        stats = cached[0]
    else:
        try:
            if db is None:
                import db as db_mod
                db = db_mod
            stats = _measure(key, db)
        except Exception:
            return True, ""      # unmeasurable is not the same as bad
        _CACHE[key] = (stats, now + ttl_s())
    if not stats:
        return True, ""
    if stats["filed"] < min_sample():
        return True, ""
    if stats["redundant_rate"] <= redundant_ceiling():
        return True, ""
    if stats["last_24h"] < daily_cap():
        return True, ""
    return False, (
        "producer %s is throttled: %d of %d tasks it filed in the last %d days were work "
        "the fleet already had (%.1f%%, ceiling %.0f%%), and it has filed %d in the last "
        "24h (cap %d). It is not blocked -- its quota returns as soon as it stops filing "
        "duplicates."
        % (key, stats["redundant"], stats["filed"], window_days(),
           100.0 * stats["redundant_rate"], 100.0 * redundant_ceiling(),
           stats["last_24h"], daily_cap()))


def reset_cache():
    _CACHE.clear()


def report(db=None):
    """Every producer's current standing. Diagnostics; not on the insert path."""
    if db is None:
        import db as db_mod
        db = db_mod
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                          time.gmtime(time.time() - window_days() * SECONDS_PER_DAY))
    rows, offset = [], 0
    while True:
        page = db.select("tasks", {"select": "slug,state,note,submitted_by_label,created_at",
                                   "created_at": f"gte.{since}",
                                   "offset": str(offset), "limit": str(PAGE_SIZE)}) or []
        if not page:
            break
        rows.extend(page)
        offset += len(page)
        if len(page) < PAGE_SIZE:
            break
    buckets = {}
    for r in rows:
        key = producer_key(r)
        if not key:
            continue
        b = buckets.setdefault(key, {"filed": 0, "merged": 0, "redundant": 0})
        b["filed"] += 1
        if str(r.get("state") or "") in ("MERGED", "DEPLOYED_AND_VERIFIED"):
            b["merged"] += 1
        if _is_redundant(r):
            b["redundant"] += 1
    out = []
    for key, b in buckets.items():
        rate = b["merged"] / float(b["filed"]) if b["filed"] else 0.0
        red = b["redundant"] / float(b["filed"]) if b["filed"] else 0.0
        out.append({"producer": key, "filed": b["filed"], "merged": b["merged"],
                    "redundant": b["redundant"], "rate": rate, "redundant_rate": red,
                    "throttled": b["filed"] >= min_sample() and red > redundant_ceiling()})
    return sorted(out, key=lambda d: -d["filed"])
