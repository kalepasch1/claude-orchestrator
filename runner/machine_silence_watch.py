#!/usr/bin/env python3
"""machine_silence_watch.py — alert when a fleet machine stops heartbeating.

THE INCIDENT THIS FIXES (2026-08-02, operator directive):
  "Mac 2's runner has been down since ~10:28 with no alert to the operator."

fleet_doctor already checks heartbeats, but only ever asserts that *this* host is
fresh:

    _check(results, "this host heartbeat fresh", any(_fresh(...) for r in host_rows))

That check can never fire for the machine that actually died — a dead host runs no
diagnostics. Its row in `runner_heartbeats` simply stops advancing and nothing
reads it. The fleet was blind to exactly the failure it most needed to see.

WHAT THIS DOES: any live host evaluates the heartbeats of every OTHER host. A host
that was recently active and has since gone quiet past the threshold raises an
operator alert through error_alerter (in-app + email + webhook, with its own
cooldown so a machine that stays down does not alert every tick).

DESIGN NOTES
  * Silence is judged against a machine's own last_seen, not against a schedule, so
    a host that is intentionally offline for a long time alerts once and then stays
    quiet under the alerter's cooldown.
  * A host is only considered "expected up" if it heartbeat within
    ORCH_MACHINE_KNOWN_WINDOW_H (default 24h). Otherwise a machine retired weeks
    ago would alert forever.
  * Never raises. This runs on the periodic path; a monitoring bug must not take a
    runner down — that would be the monitor causing the outage it watches for.
"""
from __future__ import annotations

import json
import os
import socket
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db

try:
    import error_alerter
except Exception:  # pragma: no cover - alerting is optional, detection is not
    error_alerter = None

HOST = socket.gethostname()

# A machine is SILENT once its last heartbeat is older than this.
SILENCE_MINUTES = int(os.environ.get("ORCH_MACHINE_SILENCE_MIN", "30"))
# Only machines seen within this window are "expected up"; older ones are retired.
KNOWN_WINDOW_HOURS = int(os.environ.get("ORCH_MACHINE_KNOWN_WINDOW_H", "24"))


def _parse_ts(value):
    """Parse a Postgres timestamptz string into an aware datetime, or None."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip().replace(" ", "T")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    # Postgres emits microseconds at variable width; fromisoformat wants 3 or 6.
    if "." in text:
        head, _, tail = text.partition(".")
        digits = ""
        rest = ""
        for i, ch in enumerate(tail):
            if ch.isdigit():
                digits += ch
            else:
                rest = tail[i:]
                break
        text = f"{head}.{digits[:6].ljust(6, '0')}{rest}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _latest_per_machine(rows):
    """Collapse heartbeat rows to the newest row per hostname."""
    newest = {}
    for row in rows or []:
        host = (row.get("hostname") or "").strip()
        seen = _parse_ts(row.get("last_seen"))
        if not host or seen is None:
            continue
        current = newest.get(host)
        if current is None or seen > current["last_seen"]:
            newest[host] = {
                "hostname": host,
                "last_seen": seen,
                "runner_id": row.get("runner_id") or "",
                "active_tasks": row.get("active_tasks") or 0,
            }
    return newest


def evaluate(rows, now=None, self_host=None,
             silence_minutes=None, known_window_hours=None):
    """Pure classifier: which machines are silent right now.

    Split out from the IO so the proof ("silence a machine heartbeat: operator
    alert fires") is testable without a database or a second Mac.

    Every default resolves at CALL time, not import time. Binding `self_host=HOST`
    in the signature would freeze this host's name into the default the moment the
    module loads, so neither a test nor a caller could override it — and a
    monitoring module that cannot be exercised is how the original blind spot
    survived in the first place.
    """
    now = now or datetime.now(timezone.utc)
    self_host = HOST if self_host is None else self_host
    silence_minutes = SILENCE_MINUTES if silence_minutes is None else silence_minutes
    known_window_hours = (
        KNOWN_WINDOW_HOURS if known_window_hours is None else known_window_hours
    )
    silence_cutoff = now - timedelta(minutes=silence_minutes)
    known_cutoff = now - timedelta(hours=known_window_hours)

    silent, live, retired = [], [], []
    aliases = {self_host, self_host.replace(".local", "")}

    for host, info in sorted(_latest_per_machine(rows).items()):
        if host in aliases or host.replace(".local", "") in aliases:
            continue  # this host is demonstrably alive: it is running this code
        age_min = int((now - info["last_seen"]).total_seconds() // 60)
        entry = dict(info, age_minutes=age_min)
        if info["last_seen"] < known_cutoff:
            retired.append(entry)
        elif info["last_seen"] < silence_cutoff:
            silent.append(entry)
        else:
            live.append(entry)
    return {"silent": silent, "live": live, "retired": retired}


def check(emit_alert=True, now=None):
    """Read heartbeats, classify, and alert the operator on any silent machine."""
    try:
        rows = db.select("runner_heartbeats", {
            "select": "hostname,last_seen,active_tasks,runner_id",
            "order": "last_seen.desc",
            "limit": "200",
        }) or []
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {str(exc)[:200]}",
                "silent": [], "live": [], "retired": [], "alerted": []}

    verdict = evaluate(rows, now=now)
    alerted = []
    if emit_alert and error_alerter is not None:
        for machine in verdict["silent"]:
            detail = (
                f"{machine['hostname']} last heartbeat {machine['age_minutes']}m ago "
                f"(runner_id={machine['runner_id'] or 'unknown'}, "
                f"active_tasks={machine['active_tasks']}). "
                f"Threshold {SILENCE_MINUTES}m. Observed from {HOST}."
            )
            try:
                if error_alerter.alert("MACHINE_SILENT", machine["hostname"],
                                       detail, severity="critical"):
                    alerted.append(machine["hostname"])
            except Exception:
                pass  # detection still reported below even if delivery fails
    verdict["alerted"] = alerted
    return verdict


if __name__ == "__main__":
    print(json.dumps(check(), indent=2, default=str))
