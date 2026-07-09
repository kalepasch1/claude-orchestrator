#!/usr/bin/env python3
"""
merge_stall_monitor.py — detect when the fleet stops landing merges despite active,
completed work, and alert immediately instead of silently running for hours.

Direct response to the 2026-07-08 incident: 0 merges for 32+ hours while tasks kept
completing (DONE) and quarantine/rework kept growing (QUARANTINED 812 -> 973), with
no automated signal anywhere that merges had stopped landing. Root cause was a
concurrency race in merge_train (fixed in repo_lock.py / merge_train.py / runner.py
on 2026-07-08); this monitor is the structural safeguard so ANY future cause of the
same symptom -- this race recurring, a new bug, a bad config push, Supabase being
down, whatever -- gets caught within one check interval instead of a day and a half.

Alert condition: no task has reached MERGED in ORCH_MERGE_STALL_ALERT_HOURS hours
AND there is a real backlog waiting to merge (approved merge-kind cards, or DONE
tasks) -- i.e. the fleet is clearly trying to ship work and failing, not just quiet
because there is nothing to do. A quiet fleet with an empty backlog is healthy and
must never trigger this.

Fail-soft: any error here is swallowed after logging; a broken monitor must never
be able to wedge the runner. Dedup: re-alerting is throttled by RENOTIFY_HOURS so a
persistent stall pages once per window instead of every cycle.
"""
import datetime, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

ALERT_HOURS = float(os.environ.get("ORCH_MERGE_STALL_ALERT_HOURS", "3"))
RENOTIFY_HOURS = float(os.environ.get("ORCH_MERGE_STALL_RENOTIFY_HOURS", "6"))
MIN_BACKLOG = int(os.environ.get("ORCH_MERGE_STALL_MIN_BACKLOG", "3"))


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _parse(ts):
    if not ts:
        return None
    try:
        return datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def _hours_since(ts):
    t = _parse(ts)
    if not t:
        return None
    return (_now() - t).total_seconds() / 3600.0


def _last_merge_age_hours():
    rows = db.select("tasks", {"select": "updated_at", "state": "eq.MERGED",
                                "order": "updated_at.desc", "limit": "1"}) or []
    if not rows:
        return None  # no merge has EVER landed -- a cold start, not a stall
    return _hours_since(rows[0].get("updated_at"))


def _backlog_size():
    """Work that is ready or trying to merge right now: approved merge-kind cards not yet
    handled by any integration path, plus DONE tasks (tests passed, waiting to integrate)."""
    cards = db.select("approvals", {"select": "id", "status": "eq.approved",
                                    "kind": "in.(verify,material,integrate)",
                                    "limit": "500"}) or []
    done = db.select("tasks", {"select": "id", "state": "eq.DONE", "limit": "500"}) or []
    return len(cards) + len(done)


def _existing_open_alert():
    rows = db.select("approvals", {"select": "id,created_at", "kind": "eq.merge_stall",
                                    "status": "in.(pending,approved)", "order": "created_at.desc",
                                    "limit": "1"}) or []
    return rows[0] if rows else None


def check():
    try:
        backlog = _backlog_size()
        if backlog < MIN_BACKLOG:
            return {"status": "ok", "reason": "no meaningful backlog waiting to merge", "backlog": backlog}
        age_h = _last_merge_age_hours()
        if age_h is None:
            return {"status": "ok", "reason": "no merge history yet -- not a stall signal"}
        if age_h < ALERT_HOURS:
            return {"status": "ok", "age_hours": round(age_h, 2), "backlog": backlog}

        existing = _existing_open_alert()
        if existing:
            reage = _hours_since(existing.get("created_at"))
            if reage is not None and reage < RENOTIFY_HOURS:
                return {"status": "already-alerted", "age_hours": round(age_h, 2)}

        detail = (f"No task has reached MERGED in {age_h:.1f}h, but {backlog} task(s)/card(s) "
                  f"are approved or done and waiting to integrate. The fleet is producing work "
                  f"it cannot ship -- check merge_train.py logs and repo_lock contention first "
                  f"(the 2026-07-08 incident's root cause), then transient_retries exhaustion "
                  f"on repeatedly-repaired tasks.")
        try:
            db.insert("approvals", {"project": "beethoven", "kind": "merge_stall",
                                     "title": f"Merge stall: 0 merges in {age_h:.1f}h with {backlog} waiting",
                                     "status": "pending", "detail": detail,
                                     "risk": "shipped work is piling up unmerged; investigate merge_train/repo_lock",
                                     "value": "catches recurrences of the 2026-07-08 merge-stall incident"})
        except Exception as e:
            print(f"[merge_stall_monitor] approval insert failed: {e}")
        try:
            import notify
            notify.send(f"claude-orchestrator: MERGE STALL -- 0 merges in {age_h:.1f}h, "
                        f"{backlog} task(s) waiting to integrate. Check merge_train.py / repo_lock.py.")
        except Exception as e:
            print(f"[merge_stall_monitor] notify failed: {e}")
        try:
            db.insert("resource_events", {"kind": "merge_stall_alert",
                       "detail": f"age_hours={age_h:.2f} backlog={backlog}",
                       "action": "approval+notify"})
        except Exception:
            pass
        return {"status": "alerted", "age_hours": round(age_h, 2), "backlog": backlog}
    except Exception as e:
        print(f"[merge_stall_monitor] check failed (fail-soft): {e}")
        return {"status": "error", "error": str(e)}


if __name__ == "__main__":
    import json
    print(json.dumps(check(), indent=2, default=str))
