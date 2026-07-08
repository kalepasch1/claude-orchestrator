#!/usr/bin/env python3
"""
kill_switch.py - stop all (or one project's) usage/cost with one flag. The dashboard's STOP
button writes controls.paused=true; the runner checks is_paused() before claiming a task and
before any external API call, so spend halts immediately. resume() lifts it.
"""
import os, sys, socket, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

REMOTE_QUARANTINE_BY = "remote-quarantine"
HOST = socket.gethostname()


def _is_remote_quarantine(row):
    return (row.get("updated_by") or "") == REMOTE_QUARANTINE_BY


def _host_aliases():
    # a host pause may be written as "Mac-2" or "Mac-2.local"; match either form.
    aliases = {HOST}
    aliases.add(HOST[:-6] if HOST.endswith(".local") else HOST + ".local")
    return aliases


def _match(scope, project):
    if project:
        return {"scope": scope, "project": project}
    return {"scope": scope}


def _write_control(row):
    """Write pause/resume intent against both historical controls-table shapes.

    The live table often has one row per scope instead of append-only decisions. In that shape a
    POST/upsert can silently fail to become the latest decision, so update matching rows first and
    insert only if no representation comes back.
    """
    match = _match(row["scope"], row.get("project"))
    patch = {k: v for k, v in row.items() if k not in match}
    try:
        updated = db.update("controls", match, patch)
        if updated:
            return updated
    except Exception:
        pass
    try:
        return db.insert("controls", row, upsert=True)
    except Exception as e:
        try:
            return db.update("controls", match, patch)
        except Exception as e2:
            print(f"kill_switch write skipped ({e}; fallback {e2})")
            return None


def is_paused(project=None):
    # LATEST decision wins per scope (rows can duplicate; old paused rows must not win).
    rows = db.select("controls", {"select": "scope,project,paused,updated_at,updated_by",
                                  "order": "updated_at.desc"}) or []
    for r in rows:                       # first global row = most recent global decision
        if _is_remote_quarantine(r):
            continue
        if r["scope"] == "global":
            if r.get("paused"):
                return True
            break
    # host-scoped pause: lets the fleet pause THIS machine (via fleet_control) without a
    # global pause that would halt every Mac. Latest 'host' decision for this host wins.
    aliases = _host_aliases()
    for r in rows:
        if _is_remote_quarantine(r):
            continue
        if r["scope"] == "host" and (r.get("project") or "") in aliases:
            if r.get("paused"):
                return True
            break
    if project:
        for r in rows:
            if _is_remote_quarantine(r):
                continue
            if r["scope"] == "project" and r.get("project") == project:
                return bool(r.get("paused"))
    return False


def pause(scope="global", project=None, reason="manual stop", by="dashboard"):
    row = {"scope": scope, "project": project, "paused": True,
           "reason": reason, "updated_by": by,
           "updated_at": datetime.datetime.utcnow().isoformat()}
    _write_control(row)
    return f"PAUSED {scope}{'/' + project if project else ''}"


def resume(scope="global", project=None, by="dashboard"):
    row = {"scope": scope, "project": project, "paused": False,
           "reason": f"resumed by {by}",
           "updated_by": by, "updated_at": datetime.datetime.utcnow().isoformat()}
    _write_control(row)
    return f"RESUMED {scope}{'/' + project if project else ''}"


if __name__ == "__main__":
    import sys
    a = sys.argv[1] if len(sys.argv) > 1 else "status"
    if a == "stop":
        print(pause())
    elif a == "resume":
        print(resume())
    else:
        print("global paused:", is_paused())
