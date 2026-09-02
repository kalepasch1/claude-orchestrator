#!/usr/bin/env python3
"""metaopt.py — Meta-optimization for fleet loop cadence.

Tunes loop timing parameters (poll interval, batch size, concurrency cap)
based on recent scoreboard metrics so the fleet self-adjusts its cadence
to match actual workload.

D2 scope: read-only analysis + recommended config writes to fleet_config.
No model spend — pure arithmetic on DB-sourced counters.
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# ── tunables (env-overridable) ──────────────────────────────────────────────
WINDOW_H = int(os.environ.get("ORCH_METAOPT_WINDOW_H", "6"))
MIN_POLL_S = int(os.environ.get("ORCH_MIN_POLL_S", "10"))
MAX_POLL_S = int(os.environ.get("ORCH_MAX_POLL_S", "120"))
MIN_PARALLEL = int(os.environ.get("ORCH_MIN_PARALLEL", "1"))
MAX_PARALLEL = int(os.environ.get("ORCH_MAX_PARALLEL", "8"))


def _state_count(state, since=None):
    """Rows in `tasks` with this state, optionally updated since `since`. 0 on error.

    db.count() asks PostgREST for an exact count without downloading the rows,
    which is what the SQL these functions used to send was for.
    """
    params = {"state": f"eq.{state}"}
    if since:
        params["updated_at"] = f"gte.{since}"
    try:
        return int(db.count("tasks", params) or 0)
    except Exception:
        return 0


def _recent_queue_stats():
    """Return (queued, running, done_last_window) from the tasks table.

    THESE NUMBERS WERE ALWAYS ZERO. The body was

        rows = db.query("SELECT state, count(*) as cnt FROM tasks GROUP BY state")

    inside a bare `except Exception: rows = []`. db has never had a `query`
    function -- it speaks PostgREST, and there has never been a raw-SQL channel
    on it -- so every call raised AttributeError and the handler swallowed it.
    recommend() therefore saw pressure 0 and throughput 0 on every invocation,
    whatever the queue actually held, and returned the idle branch every time:
    poll_interval_s = MAX_POLL_S, max_parallel = MIN_PARALLEL. A meta-optimizer
    that always recommends the slowest cadence is worse than none, because
    apply() writes it to fleet_config as though it were a measurement.
    """
    counts = {}
    for state in ("QUEUED", "RUNNING", "DEPLOYED_AND_VERIFIED"):
        counts[state] = _state_count(state)
    queued = counts.get("QUEUED", 0)
    running = counts.get("RUNNING", 0)
    # REWARD HYGIENE (2026-08-04): DONE+MERGED counted as "done", but ~96% of MERGED rows
    # were phantoms — cadence was being tuned to a fabricated throughput signal. Only
    # DEPLOYED_AND_VERIFIED counts as real delivery here.
    done = counts.get("DEPLOYED_AND_VERIFIED", 0)
    return queued, running, done


def _merged_since(cutoff):
    """MERGED task rows updated since `cutoff`, with their artifact_commit. [] on error."""
    try:
        return db.select_all("tasks", {
            "select": "id,artifact_commit",
            "state": "eq.MERGED",
            "updated_at": f"gte.{cutoff}",
        }) or []
    except Exception:
        return []


def _throughput_last_window():
    """Verified deliveries in the last WINDOW_H hours.

    REWARD HYGIENE (2026-08-04): previously counted DONE+MERGED, i.e. self-reported
    throughput. Now DEPLOYED_AND_VERIFIED counts fully, and MERGED counts 0.5 only when
    it carries a real artifact_commit (evidence of an integrated sha).

    Same defect as _recent_queue_stats: this sent raw SQL through db.query(),
    which does not exist, so it returned 0 unconditionally. The two counts are
    now two PostgREST reads. The MERGED half must still be filtered on
    "artifact_commit is a non-empty string", which PostgREST cannot express as a
    single operator, so those rows are read and filtered here -- bounded by the
    window, and MERGED-with-evidence is the small set by construction.
    """
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(hours=WINDOW_H)).isoformat()
    verified = _state_count("DEPLOYED_AND_VERIFIED", since=cutoff)
    merged = _merged_since(cutoff)
    merged_ev = sum(1 for r in merged if str(r.get("artifact_commit") or "").strip())
    return int(verified + 0.5 * merged_ev)


def recommend():
    """Compute recommended cadence params from current queue pressure.

    Returns dict with keys: poll_interval_s, max_parallel, reason.
    """
    queued, running, _done = _recent_queue_stats()
    throughput = _throughput_last_window()
    pressure = queued + running

    # High pressure → short poll, high parallelism
    if pressure > 20:
        poll_s = MIN_POLL_S
        parallel = MAX_PARALLEL
        reason = f"high pressure ({pressure} pending)"
    elif pressure > 8:
        poll_s = max(MIN_POLL_S, 30)
        parallel = min(MAX_PARALLEL, max(MIN_PARALLEL, 4))
        reason = f"moderate pressure ({pressure} pending)"
    elif pressure > 2:
        poll_s = 60
        parallel = min(MAX_PARALLEL, max(MIN_PARALLEL, 2))
        reason = f"light pressure ({pressure} pending)"
    else:
        poll_s = MAX_POLL_S
        parallel = MIN_PARALLEL
        reason = f"idle ({pressure} pending)"

    # If throughput is high, keep poll fast even if queue is draining
    if throughput > 10 and poll_s > 30:
        poll_s = 30
        reason += f", high throughput ({throughput}/{WINDOW_H}h)"

    return {
        "poll_interval_s": poll_s,
        "max_parallel": parallel,
        "reason": reason,
        "queued": queued,
        "running": running,
        "throughput_window": throughput,
        "window_h": WINDOW_H,
        "computed_at": datetime.datetime.utcnow().isoformat(),
    }


def apply(dry_run=False):
    """Compute and optionally write recommended cadence to fleet_config.

    Returns the recommendation dict (with applied=True/False).
    """
    rec = recommend()
    rec["applied"] = False

    if dry_run:
        return rec

    try:
        db.insert("fleet_config", {"key": "ORCH_POLL_INTERVAL_S", "value": str(rec["poll_interval_s"])},
                  upsert=True)
        db.insert("fleet_config", {"key": "MAX_PARALLEL", "value": str(rec["max_parallel"])},
                  upsert=True)
        db.insert("fleet_config", {"key": "ORCH_METAOPT_LAST", "value": rec["computed_at"]},
                  upsert=True)
        rec["applied"] = True
    except Exception as e:
        rec["error"] = str(e)

    return rec


def tick():
    """Called from the main loop; fail-soft."""
    try:
        rec = apply(dry_run=False)
        if rec.get("applied"):
            print(f"metaopt: poll={rec['poll_interval_s']}s parallel={rec['max_parallel']} ({rec['reason']})",
                  flush=True)
    except Exception as e:
        print(f"metaopt: tick error ({e})")


if __name__ == "__main__":
    import json
    print(json.dumps(apply(dry_run="--dry-run" in sys.argv), indent=2, default=str))
