#!/usr/bin/env python3
"""integration_liveness.py — alarm when work is being built but nothing is landing.

CORE INTEGRITY AUDIT §2(d), operator directive 2026-07-29.

WHAT IT WATCHES
---------------
The failure mode is silent and expensive: the fleet keeps producing `agent/*`
branches, every task reports DONE, every dashboard looks busy — and the merge
train has stopped. Nothing merges. Prod serves the same commit for hours while
the branch count climbs. Every other monitor here watches process health, so a
merge train that is up and merging nothing looks identical to one with no work.

This watches the conjunction that only occurs when integration is stuck:

    merged == 0 for longer than the window   AND   agent/* branches are growing

Either alone is normal. A quiet hour merges nothing because nothing was ready. A
growing branch count during a burst is throughput. Together, for two hours, they
mean the built work is not reaching anybody.

RELATIONSHIP TO release_currency_check
--------------------------------------
`blocked_triage.release_currency_check()` catches the same class weeks late — 25+
branches AND a base older than 48h, scanned every 6h. That is the archaeology
alarm; this is the smoke alarm. Two hours is short enough to catch a merge train
that died at 03:00 before the morning's work piles up behind it.

DESIGN
------
Read-only and fail-soft: every DB and git read is guarded, and any failure means
"no verdict this cycle", never an exception into the triage loop. The check is
meant to be cheap enough to run on the 10-minute cycle, so it counts rather than
scanning (a truncated page counted with len() is how four outage-class bugs got
in here already — see the note above db.PAGE_SIZE).

State lives in `coordination_tasks` rather than a file, because the alarm must
survive a runner restart: a crash-loop that resets the "branches last seen"
baseline every 90 seconds would never observe growth and would never fire.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402

try:
    import notify
except Exception:  # pragma: no cover - notify is optional at import time
    notify = None

#: How long integration may produce nothing before it counts as stalled.
STALL_WINDOW_H = float(os.environ.get("ORCH_INTEGRATION_STALL_WINDOW_H", "2"))

#: Growth below this is noise — one branch appearing in two hours is not a fleet
#: outrunning its merge train, and alerting on it would train the reader to
#: ignore the alarm.
MIN_BRANCH_GROWTH = int(os.environ.get("ORCH_INTEGRATION_MIN_BRANCH_GROWTH", "3"))

#: Don't re-notify more often than this while a stall persists. The condition is
#: sticky by nature, and an alarm that fires every ten minutes gets muted.
RENOTIFY_H = float(os.environ.get("ORCH_INTEGRATION_RENOTIFY_H", "2"))

SNAPSHOT_TYPE = "integration_liveness_snapshot"
ALERT_TYPE = "integration_liveness_alert"

#: Terminal states that mean work actually landed. DONE is excluded on purpose:
#: a task is DONE when its branch is pushed, which is precisely the state that
#: piles up when integration is stuck.
LANDED_STATES = ("MERGED", "DEPLOYED_AND_VERIFIED")


def _now() -> float:
    return time.time()


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def _parse_iso(value) -> float | None:
    """Epoch seconds from a PostgREST timestamp, or None."""
    try:
        import datetime
        return datetime.datetime.fromisoformat(
            str(value).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def count_agent_branches(repo: str) -> int:
    """Open `agent/*` heads on origin. -1 when git cannot be read.

    -1 rather than 0: "I could not look" and "there are none" must not compare
    equal, or an unreadable repo would read as a branch count that dropped to
    zero and mask a stall.
    """
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", "origin"],
            cwd=repo, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return -1
        return sum(1 for line in (result.stdout or "").splitlines()
                   if "refs/heads/agent/" in line)
    except Exception:
        return -1


def count_landed_since(epoch: float, project_id=None) -> int:
    """Tasks that reached a landed state since `epoch`. -1 on any DB error.

    Counted server-side. Paging a thousand rows back to count them is the bug
    class this repo has paid for four times.
    """
    try:
        params = {
            "select": "id",
            "state": f"in.({','.join(LANDED_STATES)})",
            "updated_at": f"gte.{_iso(epoch)}",
        }
        if project_id:
            params["project_id"] = f"eq.{project_id}"
        return int(db.count("tasks", params))
    except Exception:
        return -1


def _last_row(task_type: str) -> dict | None:
    try:
        rows = db.select("coordination_tasks", {
            "select": "created_at,payload",
            "task_type": f"eq.{task_type}",
            "order": "created_at.desc",
            "limit": "1"}) or []
        return rows[0] if rows else None
    except Exception:
        return None


def _payload_of(row) -> dict:
    try:
        payload = row.get("payload")
        return json.loads(payload) if isinstance(payload, str) else (payload or {})
    except Exception:
        return {}


def evaluate(landed: int, branches: int, previous_branches: int,
             stalled_for_h: float) -> tuple[bool, str]:
    """The verdict, as a pure function. `(should_alert, reason)`.

    Separated from all I/O so the decision can be tested exhaustively without a
    database, a repo, or the clock.
    """
    if landed < 0 or branches < 0:
        return False, "could not read integration state this cycle"
    if previous_branches < 0:
        return False, "no prior branch snapshot to compare against"
    if landed > 0:
        return False, f"{landed} task(s) landed inside the window"
    if stalled_for_h < STALL_WINDOW_H:
        return False, (f"nothing landed, but only {stalled_for_h:.1f}h of the "
                       f"{STALL_WINDOW_H:.0f}h window has elapsed")

    growth = branches - previous_branches
    if growth < MIN_BRANCH_GROWTH:
        # Nothing landing and nothing being produced is a quiet fleet, not a
        # stuck one. That is a different alarm and not this one's business.
        return False, (f"nothing landed for {stalled_for_h:.1f}h, but agent branches "
                       f"grew by only {growth} — quiet fleet, not a blocked one")

    return True, (f"nothing landed for {stalled_for_h:.1f}h while agent branches grew "
                  f"by {growth} (now {branches}) — built work is not reaching anyone")


def check(repo: str | None = None, project_id=None) -> dict:
    """Run one liveness check. Returns the verdict; never raises.

    The returned dict always has `alert` (bool) and `reason` (str), so a caller
    can log it unconditionally.
    """
    repo = repo or os.environ.get("ORCH_REPO_PATH") or os.getcwd()
    now = _now()

    branches = count_agent_branches(repo)

    previous = _last_row(SNAPSHOT_TYPE)
    previous_payload = _payload_of(previous) if previous else {}
    try:
        previous_branches = int(previous_payload.get("branches", -1))
    except Exception:
        previous_branches = -1

    since = _parse_iso(previous.get("created_at")) if previous else None
    stalled_for_h = ((now - since) / 3600) if since else 0.0

    window_start = now - STALL_WINDOW_H * 3600
    landed = count_landed_since(min(window_start, since or window_start), project_id)

    should_alert, reason = evaluate(landed, branches, previous_branches, stalled_for_h)

    verdict = {
        "at": _iso(now),
        "alert": should_alert,
        "reason": reason,
        "branches": branches,
        "previous_branches": previous_branches,
        "landed": landed,
        "stalled_for_h": round(stalled_for_h, 2),
    }

    # Snapshot first, so a failure in the alerting path below cannot cost the
    # baseline the NEXT cycle needs to observe growth.
    _record(SNAPSHOT_TYPE, verdict)

    if should_alert and _renotify_due(now):
        _record(ALERT_TYPE, dict(verdict, action=(
            "inspect the merge train (runner/merge_train.py) and "
            "runner/catchup_drive.sh — tasks are completing but not integrating")))
        _notify(f"[integration-liveness] CRITICAL: {reason}")

    return verdict


def _renotify_due(now: float) -> bool:
    row = _last_row(ALERT_TYPE)
    if not row:
        return True
    last = _parse_iso(row.get("created_at"))
    if last is None:
        # An unreadable timestamp must not silence the alarm.
        return True
    return (now - last) >= RENOTIFY_H * 3600


def _record(task_type: str, payload: dict) -> None:
    try:
        db.insert("coordination_tasks", {
            "task_type": task_type,
            "payload": json.dumps(payload)[:8000]}, upsert=False)
    except Exception:
        pass


def _notify(message: str) -> None:
    print(message, flush=True)
    try:
        if notify is not None:
            notify.send(message)
    except Exception:
        pass


def main() -> int:
    verdict = check()
    print(json.dumps(verdict, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
