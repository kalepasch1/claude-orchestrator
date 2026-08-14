#!/usr/bin/env python3
"""
fleet_heartbeat.py — machine + pipeline heartbeat alerts (operator directive 2026-08-02, P0).

Section 2 of the fleet immune system. Section 1 (lane_guard) stops the fleet filling with
dead workers. This half stops outages going UNNOTICED, which is the other way the
2026-08-02 incident lasted as long as it did:

  (4) Mac 2's runner had been down since ~10:28 with no alert — half a day.
  (5) sentinel's train-stale fired for days as a FALSE alarm: merge_train wrote pressure
      to the DB (controls.merge_train_pressure) while sentinel watched the FILE mtime, so
      the file went stale forever and the guard kept firing. Hotfixed in a94f4bb4; this
      module makes the whole class of file-vs-DB divergence a standing hourly check.
  (6) the release train's batch floor silently held small merges out of production
      (hotfixed 04b55df6; RELEASE_MIN_BATCH=1 recovery mode is still active).

Note on ownership: `runner_heartbeats` is already WRITTEN by db.heartbeat() every loop.
Nothing was READING it for liveness and paging the operator. This module is that reader —
deliberately additive, so no existing writer changes.

Everything here is read-only except `auto_revert_release_min_batch()`, which removes a
recovery-mode override from runner/.env once the backlog it was meant to drain is gone.

CLI:
    python3 runner/fleet_heartbeat.py              # full hourly pass
    python3 runner/fleet_heartbeat.py machines     # machine liveness only
    python3 runner/fleet_heartbeat.py selftest     # pipeline consistency only
"""
import os
import sys
import json
import time
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
RUNTIME = os.path.join(REPO, ".runtime")
ENV_FILE = os.path.join(HERE, ".env")
PRESSURE_KEY = "merge_train_pressure"
PRESSURE_FILE = os.path.join(RUNTIME, "merge_train_pressure.json")
BOOT_COMMIT_FILES = (os.path.join(REPO, ".runner_boot_commit"),
                     os.path.join(HERE, ".runner_boot_commit"))

# A machine silent this long is presumed down and pages the operator.
MACHINE_SILENT_MIN = int(os.environ.get("ORCH_MACHINE_SILENT_MIN", "30"))
# Heartbeats are written every loop; this is the cadence the monitor expects.
HEARTBEAT_INTERVAL_MIN = int(os.environ.get("ORCH_HEARTBEAT_INTERVAL_MIN", "5"))
# File-vs-DB pressure divergence beyond this is the false-train-stale bug class.
PRESSURE_SKEW_MIN = int(os.environ.get("ORCH_PRESSURE_SKEW_MIN", "60"))
# How long RELEASE_MIN_BATCH=1 recovery mode may stay on before it is flagged.
RECOVERY_MODE_WARN_H = float(os.environ.get("ORCH_RECOVERY_MODE_WARN_H", "72"))
# Auto-revert thresholds: queue below this, continuously, for this long.
AUTO_REVERT_QUEUE_FLOOR = int(os.environ.get("ORCH_AUTO_REVERT_QUEUE_FLOOR", "50"))
AUTO_REVERT_SUSTAIN_H = float(os.environ.get("ORCH_AUTO_REVERT_SUSTAIN_H", "24"))


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _parse_ts(value):
    """Parse a Postgres/ISO timestamp into an aware datetime, or None."""
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def _age_min(value):
    parsed = _parse_ts(value)
    if parsed is None:
        return None
    return (_now() - parsed).total_seconds() / 60.0


def _alert(msg, notifier=None):
    send = notifier
    if send is None:
        try:
            import notify
            send = notify.send
        except Exception:
            send = lambda m: print("[fleet-heartbeat] " + m, flush=True)
    send("[fleet-heartbeat] " + msg)


def _control_get(key):
    try:
        import db
        rows = db.select("controls", {"select": "key,value,updated_at",
                                      "key": "eq.{0}".format(key)}) or []
        return rows[0] if rows else None
    except Exception:
        return None


def _control_set(key, value):
    try:
        import db
        db.insert("controls", {"key": key, "value": json.dumps(value),
                               "updated_at": "now()"}, upsert=True)
        return True
    except Exception:
        return False


# ── 1. Machine liveness ──────────────────────────────────────────────────────
def machines(rows=None):
    """Latest heartbeat per HOSTNAME, with age and last-handled fleet_control row age.

    runner_id is PID-based, so one machine produces many rows across restarts. Liveness
    is a property of the MACHINE, so collapse to the freshest row per hostname —
    otherwise a restarted runner looks like a second, permanently-dead machine.
    """
    if rows is None:
        try:
            import db
            rows = db.select("runner_heartbeats", {
                "select": "runner_id,hostname,active_tasks,last_seen,code_sha",
                "order": "last_seen.desc", "limit": "200"}) or []
        except Exception as exc:
            return {"error": str(exc), "machines": []}

    freshest = {}
    for row in rows:
        host = row.get("hostname")
        if not host:
            continue
        seen = _parse_ts(row.get("last_seen"))
        if seen is None:
            continue
        current = freshest.get(host)
        if current is None or seen > current["_seen"]:
            freshest[host] = {"hostname": host, "runner_id": row.get("runner_id"),
                              "active_tasks": int(row.get("active_tasks") or 0),
                              "code_sha": row.get("code_sha"),
                              "last_seen": row.get("last_seen"), "_seen": seen}

    control_ages = _fleet_control_ages()
    out = []
    for host, info in freshest.items():
        age = (_now() - info.pop("_seen")).total_seconds() / 60.0
        info["silent_min"] = round(age, 1)
        info["down"] = age > MACHINE_SILENT_MIN
        info["last_fleet_control_min"] = control_ages.get(host)
        out.append(info)
    out.sort(key=lambda m: -m["silent_min"])
    return {"machines": out, "silent_threshold_min": MACHINE_SILENT_MIN}


def _fleet_control_ages():
    """Age in minutes of the newest fleet_control row each host acknowledged.

    A machine can keep heartbeating while having stopped ACTING on fleet_control (the
    ack path is what actually proves the coordination gateway is alive on that host), so
    the directive asks for this alongside plain liveness.
    """
    ages = {}
    try:
        import db
        rows = db.select("fleet_control", {"select": "handled_by,created_at,updated_at",
                                           "order": "created_at.desc", "limit": "100"}) or []
    except Exception:
        return ages
    for row in rows:
        handled = row.get("handled_by")
        if not handled:
            continue
        hosts = handled if isinstance(handled, list) else [handled]
        stamp = row.get("updated_at") or row.get("created_at")
        age = _age_min(stamp)
        if age is None:
            continue
        for host in hosts:
            host = str(host).strip()
            if host and (host not in ages or age < ages[host]):
                ages[host] = round(age, 1)
    return ages


def check_machines(snapshot=None, notifier=None):
    """Page the operator for any machine silent longer than the threshold.

    This is the check that did not exist: Mac 2 was down from ~10:28 and nothing said so.
    """
    snap = snapshot if snapshot is not None else machines()
    alerts = []
    if snap.get("error"):
        return alerts
    for m in snap.get("machines", []):
        if not m.get("down"):
            continue
        detail = "machine {0} silent {1}m (threshold {2}m; heartbeat cadence {3}m)".format(
            m["hostname"], int(m["silent_min"]), MACHINE_SILENT_MIN, HEARTBEAT_INTERVAL_MIN)
        fc = m.get("last_fleet_control_min")
        if fc is not None:
            detail += "; last fleet_control ack {0}m ago".format(int(fc))
        alerts.append(detail)
    for msg in alerts:
        _alert(msg, notifier)
    return alerts


# ── 2. Pipeline consistency self-tests ───────────────────────────────────────
def selftest_pressure_consistency():
    """merge_train pressure: DB row vs file mtime.

    THE bug class behind the false train-stale alarm. merge_train upserts
    controls.merge_train_pressure and, only in the DB-failure branch, wrote the file.
    sentinel.train_guard() reads the FILE's mtime. So on a healthy DB the file never
    updated, its age grew without bound, and train_guard fired forever on a train that
    was running fine. Two sources of truth for one fact, and nothing compared them.
    """
    result = {"name": "pressure_file_vs_db", "ok": True, "detail": ""}
    row = _control_get(PRESSURE_KEY)
    db_age = _age_min(row.get("updated_at")) if row else None
    try:
        file_age = (time.time() - os.path.getmtime(PRESSURE_FILE)) / 60.0
    except OSError:
        file_age = None

    result["db_age_min"] = None if db_age is None else round(db_age, 1)
    result["file_age_min"] = None if file_age is None else round(file_age, 1)

    if db_age is None and file_age is None:
        result["ok"] = None
        result["detail"] = "no pressure signal in either the DB or the file"
        return result
    if file_age is None:
        result["ok"] = False
        result["detail"] = ("DB pressure is {0}m old but {1} does not exist — sentinel "
                            "watches the file and will fire train-stale forever".format(
                                int(db_age or 0), PRESSURE_FILE))
        return result
    if db_age is None:
        result["ok"] = False
        result["detail"] = "pressure file exists but controls.{0} is missing".format(PRESSURE_KEY)
        return result
    skew = abs(file_age - db_age)
    result["skew_min"] = round(skew, 1)
    if skew > PRESSURE_SKEW_MIN:
        result["ok"] = False
        result["detail"] = ("pressure file/DB skew {0}m > {1}m (file {2}m, DB {3}m) — the "
                            "two writers have diverged again".format(
                                int(skew), PRESSURE_SKEW_MIN, int(file_age), int(db_age)))
    else:
        result["detail"] = "file and DB agree within {0}m".format(int(skew))
    return result


def selftest_boot_commit():
    """`.runner_boot_commit` must exist and hold a sha.

    Without it self_deploy can never detect stale code, so merged work never takes
    effect until a human restarts the fleet — the standing 'no .runner_boot_commit'
    warning. keepalive.sh writes it at runner start; this proves it actually happened.
    """
    result = {"name": "boot_commit_file", "ok": False, "detail": ""}
    for path in BOOT_COMMIT_FILES:
        try:
            with open(path) as fh:
                sha = fh.read().strip()
        except IOError:
            continue
        if sha:
            result["ok"] = True
            result["path"] = path
            result["sha"] = sha[:12]
            result["detail"] = "boot commit {0} recorded at {1}".format(sha[:12], path)
            return result
        result["detail"] = "{0} exists but is empty".format(path)
        return result
    result["detail"] = ("no .runner_boot_commit in {0} — self_deploy cannot detect stale "
                        "code, so merged work will not take effect".format(
                            " or ".join(BOOT_COMMIT_FILES)))
    return result


def _env_override(key):
    """Read a key's override from runner/.env (the machine-local file), or None."""
    try:
        with open(ENV_FILE) as fh:
            lines = fh.readlines()
    except IOError:
        return None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        if name.strip() == key:
            return value.strip().strip('"').strip("'")
    return None


def selftest_release_env():
    """Warn while RELEASE_MIN_BATCH=1 recovery mode has been active longer than the window.

    The floor of 10 silently held small merges out of production. Recovery mode (=1) was
    the right emergency fix, but it is a temporary state: leaving it on indefinitely
    means every single merge ships alone, which is its own kind of broken.
    """
    result = {"name": "release_min_batch_recovery", "ok": True, "detail": ""}
    value = _env_override("RELEASE_MIN_BATCH") or os.environ.get("RELEASE_MIN_BATCH")
    result["value"] = value
    if str(value) != "1":
        result["detail"] = "RELEASE_MIN_BATCH={0} — not in recovery mode".format(value)
        return result

    row = _control_get("release_min_batch_recovery_since")
    since = None
    if row:
        try:
            since = _parse_ts(json.loads(row.get("value") or "null"))
        except Exception:
            since = None
    if since is None:
        _control_set("release_min_batch_recovery_since", _now().isoformat())
        result["detail"] = "recovery mode observed; started tracking now"
        return result

    hours = (_now() - since).total_seconds() / 3600.0
    result["active_hours"] = round(hours, 1)
    if hours > RECOVERY_MODE_WARN_H:
        result["ok"] = False
        result["detail"] = ("RELEASE_MIN_BATCH=1 recovery mode active {0}h > {1}h — every "
                            "merge is shipping alone; revert once the backlog is drained"
                            .format(int(hours), int(RECOVERY_MODE_WARN_H)))
    else:
        result["detail"] = "recovery mode active {0}h (warn at {1}h)".format(
            int(hours), int(RECOVERY_MODE_WARN_H))
    return result


def consistency_selftests(notifier=None):
    """Hourly pipeline self-tests. Returns every result; alerts only on hard failures."""
    checks = [selftest_pressure_consistency(), selftest_boot_commit(), selftest_release_env()]
    for check in checks:
        if check["ok"] is False:
            _alert("{0}: {1}".format(check["name"], check["detail"]), notifier)
    return checks


# ── 3. Auto-revert release-train recovery mode ───────────────────────────────
def _queued_counts():
    """QUEUED task count per project name."""
    try:
        import db
        rows = db.select("tasks", {"select": "project_id", "state": "eq.QUEUED",
                                   "limit": "20000"}) or []
    except Exception:
        return None
    counts = {}
    for row in rows:
        key = row.get("project_id")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _remove_env_override(key):
    """Drop `key` from runner/.env, preserving everything else. Returns True if removed."""
    try:
        with open(ENV_FILE) as fh:
            lines = fh.readlines()
    except IOError:
        return False
    kept, removed = [], False
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            if stripped.partition("=")[0].strip() == key:
                removed = True
                continue
        kept.append(line)
    if not removed:
        return False
    tmp = ENV_FILE + ".tmp"
    with open(tmp, "w") as fh:
        fh.writelines(kept)
    os.replace(tmp, ENV_FILE)
    return True


def auto_revert_release_min_batch(counts=None, notifier=None, apply=True):
    """Restore default batching once every project's queue has stayed below the floor.

    Recovery mode exists to drain a backlog. When the backlog is gone it should switch
    itself off — otherwise the fleet ships one-merge releases forever because nobody
    remembered to undo an emergency setting. Requires the condition to HOLD for
    AUTO_REVERT_SUSTAIN_H, so a brief dip cannot flap the release cadence.
    """
    out = {"reverted": False, "detail": "", "max_queued": None}

    value = _env_override("RELEASE_MIN_BATCH")
    if str(value) != "1":
        out["detail"] = "not in recovery mode (RELEASE_MIN_BATCH={0})".format(value)
        return out

    counts = _queued_counts() if counts is None else counts
    if counts is None:
        out["detail"] = "queue depth unavailable"
        return out
    max_queued = max(counts.values()) if counts else 0
    out["max_queued"] = max_queued

    key = "release_min_batch_below_floor_since"
    row = _control_get(key)
    since = None
    if row:
        try:
            since = _parse_ts(json.loads(row.get("value") or "null"))
        except Exception:
            since = None

    if max_queued >= AUTO_REVERT_QUEUE_FLOOR:
        if since is not None:
            _control_set(key, None)          # queue climbed again — restart the clock
        out["detail"] = "deepest queue {0} >= floor {1}; recovery mode stays on".format(
            max_queued, AUTO_REVERT_QUEUE_FLOOR)
        return out

    if since is None:
        _control_set(key, _now().isoformat())
        out["detail"] = "queue below floor; started the {0}h sustain clock".format(
            int(AUTO_REVERT_SUSTAIN_H))
        return out

    hours = (_now() - since).total_seconds() / 3600.0
    out["sustained_hours"] = round(hours, 1)
    if hours < AUTO_REVERT_SUSTAIN_H:
        out["detail"] = "queue below floor for {0}h of {1}h required".format(
            round(hours, 1), int(AUTO_REVERT_SUSTAIN_H))
        return out

    if not apply:
        out["detail"] = "would revert (sustained {0}h)".format(int(hours))
        return out

    if _remove_env_override("RELEASE_MIN_BATCH"):
        os.environ.pop("RELEASE_MIN_BATCH", None)
        _control_set(key, None)
        _control_set("release_min_batch_recovery_since", None)
        out["reverted"] = True
        out["detail"] = ("reverted RELEASE_MIN_BATCH=1 recovery mode — deepest queue {0} "
                         "< floor {1} sustained {2}h; default batching restored".format(
                             max_queued, AUTO_REVERT_QUEUE_FLOOR, int(hours)))
        _alert(out["detail"], notifier)
    else:
        out["detail"] = "RELEASE_MIN_BATCH override not present in {0}".format(ENV_FILE)
    return out


# ── entry point ──────────────────────────────────────────────────────────────
def run(notifier=None):
    """Hourly pass: machine liveness, pipeline self-tests, auto-revert."""
    snap = machines()
    report = {
        "ts": _now().isoformat(),
        "machines": snap.get("machines", []),
        "machine_alerts": check_machines(snap, notifier),
        "selftests": consistency_selftests(notifier),
        "auto_revert": auto_revert_release_min_batch(notifier=notifier),
    }
    failed = [c["name"] for c in report["selftests"] if c["ok"] is False]
    print("[fleet-heartbeat] machines={0} down={1} selftests_failed={2}".format(
        len(report["machines"]), len(report["machine_alerts"]),
        ",".join(failed) or "none"), flush=True)
    return report


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    cmd = (argv[0] if argv else "run").lower()
    if cmd == "machines":
        print(json.dumps(machines(), indent=2, default=str))
    elif cmd == "selftest":
        print(json.dumps(consistency_selftests(), indent=2, default=str))
    elif cmd in ("run", ""):
        print(json.dumps(run(), indent=2, default=str))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    # Single-instance lock: this is an interval job, and the whole point of the section is
    # that interval jobs must not stack. Falls through gracefully if lane_guard is absent.
    try:
        import lane_guard
        if not os.environ.get("ORCH_NO_SINGLE_INSTANCE"):
            _lock = lane_guard.guard_or_exit("fleet_heartbeat", interval_s=3600)
    except ImportError:
        pass
    sys.exit(main())
