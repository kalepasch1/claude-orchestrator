#!/usr/bin/env python3
"""scheduler_snapshot.py — publish the scheduler heartbeat the staleness monitor watches.

WHAT WAS ACTUALLY WRONG (measured 2026-08-24, project eatfwdzfurujcuwlhdgj):

The DB function `check_scheduler_snapshot_staleness(p_stale_secs)` reads
`max(updated_at) from scheduler_status_snapshots` and raises
runner_alerts(kind='scheduler_snapshot_stale') when it exceeds the threshold. It has
fired 2,695 times, most recently at 33.7 DAYS old against a 600-second threshold.

But `scheduler_status_snapshots` contains exactly ONE row:

    snapshot_key = 'batch:tomorrow-batches-7-9-20260719'
    updated_at   = 2026-07-22 01:43:03Z

— a one-off BATCH inventory written by an ad-hoc script in July, for an unrelated
purpose. Nothing in this repository writes to that table at all (`grep -rl
scheduler_status_snapshots` across the tree: zero hits). So the monitor is not reporting
a stalled scheduler; it is reporting that it has no data source. It was watching a table
with no producer, and the age it prints is simply "time since someone ran that script".

THIS MATTERS FOR THE DIAGNOSIS. The originating task inferred that a scheduler "operating
on a 28-day-old snapshot cannot be claiming/dispatching current work correctly" and
proposed it as a cause of the throughput collapse. That inference is wrong in a specific
and useful way: nothing READS this table either, so no scheduling decision has ever been
made from it. The alert and the throughput collapse are independent; chasing the alert as
a throughput cause would have cost a debugging cycle on a monitor with an empty input.

THE FIX is to give the monitor a real producer. publish() upserts a
`scheduler:heartbeat` row with the queue counts a human would actually want when asking
"is the scheduler alive and what is it looking at". Once it runs on the periodic tick,
the staleness function's own else-branch flips the 2,695 open alerts to resolved=true.

Conventions: fail-soft everywhere (a heartbeat must never be able to wedge the tick it
rides on), ORCH_-prefixed env vars so cadence/limits are fleet-pushable via
fleet_control.py, module-level singleton delegation.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

#: Row this module owns. Namespaced so it cannot collide with the batch:* rows an ad-hoc
#: script may still write.
SNAPSHOT_KEY = os.environ.get("ORCH_SCHEDULER_SNAPSHOT_KEY", "scheduler:heartbeat")

#: Must stay comfortably under the monitor's threshold (600s) or the heartbeat itself
#: becomes the thing that alerts. The periodic tick that calls this runs every 180s.
STALE_SECONDS = int(os.environ.get("ORCH_SCHEDULER_SNAPSHOT_STALE_SECONDS", "600") or 600)

#: States worth counting. Deliberately short: this is a heartbeat, not a report, and a
#: heartbeat that runs an expensive aggregate is a heartbeat that stops beating.
_COUNTED_STATES = ("QUEUED", "RUNNING", "BLOCKED", "QUARANTINED")


def _count(db, state):
    """Exact server-side count for one state. -1 when it could not be determined.

    count() rather than len(select(...)): PostgREST caps a response at 1,000 rows no
    matter what limit is asked for, so len() of a page silently reports 1000 for a queue
    of 2,227 — which is exactly the number this heartbeat exists to make visible.
    """
    try:
        return int(db.count("tasks", {"state": f"eq.{state}"}))
    except Exception:
        return -1


def build_payload(db, now=None):
    """The heartbeat body. Pure apart from the counts it is handed."""
    now = time.time() if now is None else now
    counts = {state: _count(db, state) for state in _COUNTED_STATES}
    return {
        "source": "scheduler_snapshot.publish",
        "host": os.environ.get("ORCH_HOST") or "",
        "pid": os.getpid(),
        "emitted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "states": counts,
        # Explicit, so a reader can tell "the scheduler saw an empty queue" apart from
        # "the count query failed", which -1 alone does not convey.
        "counts_complete": all(value >= 0 for value in counts.values()),
        "stale_threshold_seconds": STALE_SECONDS,
    }


def publish(db=None, now=None):
    """Upsert the heartbeat row. Returns True on success, False on any failure.

    Never raises: this runs inside the periodic tick alongside jobs that matter more, and
    a telemetry write must not be able to take them down with it.
    """
    if db is None:
        try:
            import db as db_module
            db = db_module
        except ImportError:
            print("scheduler_snapshot: db module unavailable; heartbeat skipped")
            return False
    payload = build_payload(db, now=now)
    row = {
        "snapshot_key": SNAPSHOT_KEY,
        "payload": payload,
        "updated_at": "now()",
    }
    try:
        db.insert("scheduler_status_snapshots", row, upsert=True)
        return True
    except TypeError:
        # Older db.insert() signatures have no upsert kwarg; fall back to update-then-insert.
        pass
    except Exception as e:
        print(f"scheduler_snapshot: upsert failed ({type(e).__name__}: {e}); fail-soft")
        return False
    try:
        db.update("scheduler_status_snapshots", {"snapshot_key": f"eq.{SNAPSHOT_KEY}"},
                  {"payload": payload, "updated_at": "now()"})
        return True
    except Exception:
        pass
    try:
        db.insert("scheduler_status_snapshots", row)
        return True
    except Exception as e:
        print(f"scheduler_snapshot: heartbeat could not be written "
              f"({type(e).__name__}: {e}); fail-soft")
        return False


def run():
    """Periodic entry point. Prints one line so the tick log shows the heartbeat."""
    ok = publish()
    print(f"scheduler_snapshot: heartbeat {'published' if ok else 'FAILED'} "
          f"(key={SNAPSHOT_KEY})", flush=True)
    return {"published": bool(ok), "snapshot_key": SNAPSHOT_KEY}


if __name__ == "__main__":
    run()
