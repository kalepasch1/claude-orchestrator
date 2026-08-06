#!/usr/bin/env python3
"""
paused_host_guard.py — a pause must stop every fleet actor, not just task claims.

THE GAP
-------
trg_stale_host_claim_guard (2026-08-06) fires on `tasks.account` changing — a task
CLAIM. Release-train and merge-train work is not a task claim, so a paused host went
on running QA gates, build gates and release attempts against its own stale checkout
and broken toolchain.

Evidence, 2026-08-06 21:10. A beethoven release failed with:

    [gate:build] staging BUILD red — self-heal queued:
    npm error A complete log of this run can be found in: /Users/mandypa...

`/Users/mandypa...` is Mandys-MacBook-Pro: PAUSED in controls since 19:02, 40+ commits
stale on code_sha 10d9e408, 0 of 46 tasks completed in 48h. Its failures write
`releases` rows with deploy_status='failed', which flips the project RED, which trips
ORCH_RELEASE_BACKPRESSURE and rejects new work FLEET-WIDE. A paused, broken host is
not merely useless — it poisons the release state of projects it must not touch.

Note the diagnosis had to come from a log PATH. `releases` records no host, so nothing
in the row said who produced it. The migration alongside this module adds `releases.host`
for exactly that reason.

THE ONE RULE THAT MAKES THIS SAFE
---------------------------------
Block STARTING, never block FINISHING. The claim guard permits a paused host to complete
and record work it already holds, because stranding in-flight work is worse than the
failure being fixed. Same contract here: `may_start()` is called at the top of a pass,
and nothing in this module is consulted once a pass is under way.

FAIL-OPEN, DELIBERATELY
-----------------------
If the pause lookup itself errors, `may_start()` returns True. A guard that halts every
train in the fleet when `controls` is briefly unreachable is a worse outage than the one
it prevents — and the DB trigger is the backstop that a broken client cannot evade. That
is the same belt-and-braces split the claim guard uses.
"""
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HOST = socket.gethostname()

# Recorded into runner_alerts so a refusal is visible. Silence is how this went unseen.
ALERT_KIND = "release_from_paused_host"


def host_is_paused():
    """(paused, reason). Fail-open: (False, "") if the lookup itself fails."""
    try:
        import kill_switch
        if kill_switch.is_paused():
            return True, _pause_reason()
    except Exception as exc:
        print(f"[paused-host-guard] pause lookup failed ({exc}); proceeding", flush=True)
    return False, ""


def may_start(actor, project=None):
    """May `actor` begin a new pass on this host? Returns (ok, reason).

    `actor` is a short name used in the log line and the recorded alert:
    "release_train", "merge_train", "gate:build", and so on.
    """
    paused, reason = host_is_paused()
    if not paused:
        return True, ""
    detail = (f"{actor} refused on {HOST}: host is paused"
              + (f" ({reason})" if reason else "")
              + (f"; project={project}" if project else ""))
    print(f"[paused-host-guard] {detail}", flush=True)
    return False, detail


def record_rejection(actor, detail, project=None):
    """Record a refusal in runner_alerts. Never raises.

    The task that prompted this module was explicit: "When a release row is rejected
    because its host is paused, record it rather than swallowing. Silence is how this
    went unseen."
    """
    try:
        import db
        db.insert("runner_alerts", {
            "kind": ALERT_KIND,
            "detail": (f"host={HOST} actor={actor}"
                       + (f" project={project}" if project else "")
                       + f" — {detail}")[:2000],
            "resolved": False,
        })
    except Exception as exc:
        print(f"[paused-host-guard] could not record rejection ({exc}): {detail}", flush=True)


def refuse(actor, project=None):
    """may_start() + record_rejection() in one call. Returns (ok, reason)."""
    ok, reason = may_start(actor, project=project)
    if not ok:
        record_rejection(actor, reason, project=project)
    return ok, reason


def _pause_reason():
    """Best-effort reason string from the latest host-scoped controls row."""
    try:
        import db
        import kill_switch
        aliases = kill_switch._host_aliases()
        rows = db.select("controls", {"select": "scope,project,paused,reason,updated_at",
                                      "order": "updated_at.desc"}) or []
        for row in rows:
            if row.get("scope") == "host" and (row.get("project") or "") in aliases:
                return (row.get("reason") or "").strip()
    except Exception:
        pass
    return ""
