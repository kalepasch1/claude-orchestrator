#!/usr/bin/env python3
"""pipeline_selftest.py — machine + pipeline heartbeat alerts (§2, operator 2026-08-02).

Three failures on 2026-08-02 shared one shape: **the fleet was broken and nothing said so.**

  * Mac 2's runner died at ~10:28 and stayed dead half a day. `runner_heartbeats` already
    existed; nobody was reading it, so silence was indistinguishable from health.
  * `sentinel.train_guard()` alerted on a FILE's mtime while `merge_train._record_pressure()`
    had moved to writing a DB row. The file went stale and stayed stale; train-stale fired as
    a false alarm for days and was eventually ignored — the worst possible outcome for a check.
  * `RELEASE_MIN_BATCH=1` recovery mode was set to unstick production and then simply left on,
    with nothing tracking that it was a temporary measure.

So this module is the pipeline's own smoke test. It runs hourly, it is READ-ONLY except for
the one explicitly-requested auto-revert, and it is fail-soft: a self-test that crashes the
runner is worse than no self-test.

Verdicts come from `fleet_immune_contracts` — thresholds are defined once, there. See
runner/FLEET_IMMUNE_CONTRACTS.md.
"""
import datetime
import json
import os
import socket
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
REPO = os.path.dirname(HERE)
RUNTIME = os.path.join(REPO, ".runtime")

import fleet_immune_contracts as fic

HOST = socket.gethostname()
HEARTBEAT_SILENT_S = int(os.environ.get("ORCH_HEARTBEAT_SILENT_S", "1800"))       # 30 min
PRESSURE_STALE_S = int(os.environ.get("ORCH_PRESSURE_STALE_S", "3600"))           # 1 h
RECOVERY_MODE_MAX_S = int(os.environ.get("ORCH_RECOVERY_MODE_MAX_S", str(72 * 3600)))
AUTO_REVERT_QUEUE_FLOOR = int(os.environ.get("ORCH_AUTO_REVERT_QUEUE_FLOOR", "50"))
AUTO_REVERT_SUSTAIN_S = int(os.environ.get("ORCH_AUTO_REVERT_SUSTAIN_S", str(24 * 3600)))
STATE_PATH = os.path.join(RUNTIME, "pipeline_selftest_state.json")


# ── small fail-soft helpers ───────────────────────────────────────────────────────────────

def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _age_s(ts, now=None):
    """Seconds since an ISO timestamp. None when absent or unparseable."""
    if not ts:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return ((now or _now()) - parsed).total_seconds()


def load_state(path=None):
    try:
        with open(path or STATE_PATH) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_state(state, path=None):
    try:
        os.makedirs(RUNTIME, exist_ok=True)
        with open(path or STATE_PATH, "w") as f:
            json.dump(state, f, indent=1)
        return True
    except Exception:
        return False


# ── check 1: machine silence ──────────────────────────────────────────────────────────────

def check_machine_heartbeats(rows=None, control_rows=None, silent_s=None, now=None):
    """Alert on any machine silent longer than `silent_s`.

    `rows` are runner_heartbeats records ({hostname|runner_id, last_seen}); `control_rows` are
    fleet_control records, used to report how long ago each host last ACKed a control row — a
    host can publish heartbeats while having stopped honouring control, and the operator needs
    to see both. Returns a list of Verdicts. Never raises.
    """
    silent_s = HEARTBEAT_SILENT_S if silent_s is None else silent_s
    out = []
    try:
        if rows is None:
            import db
            rows = db.select("runner_heartbeats",
                             {"select": "runner_id,hostname,last_seen",
                              "order": "last_seen.desc", "limit": "50"}) or []
        latest = {}
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            host = row.get("hostname") or row.get("runner_id") or "?"
            age = _age_s(row.get("last_seen"), now=now)
            if host not in latest or (age is not None and (latest[host] is None or age < latest[host])):
                latest[host] = age

        control_age = _last_control_ack_age(control_rows, now=now)

        for host, age in sorted(latest.items()):
            verdict = fic.classify_host(
                fic.HostLiveness(host=host, last_heartbeat_age_s=age),
                down_after_s=silent_s)
            if host in control_age and control_age[host] is not None:
                verdict.detail["last_control_ack_age_s"] = round(control_age[host])
            if verdict.actionable:
                out.append(verdict)
        if not latest:
            out.append(fic.Verdict(fic.DOWN,
                                   "no runner heartbeats on record at all — the publisher itself "
                                   "may be failing silently",
                                   "alert", "host:*", {}))
    except Exception:
        pass
    return out


def _last_control_ack_age(control_rows=None, now=None):
    """{host: seconds since it last handled a fleet_control row}. Fail-soft -> {}."""
    ages = {}
    try:
        if control_rows is None:
            import db
            control_rows = db.select("fleet_control",
                                     {"select": "handled_by,handled_at,created_at",
                                      "order": "created_at.desc", "limit": "50"}) or []
        for row in control_rows or []:
            if not isinstance(row, dict):
                continue
            host = row.get("handled_by")
            if not host:
                continue
            age = _age_s(row.get("handled_at") or row.get("created_at"), now=now)
            if host not in ages or (age is not None and (ages[host] is None or age < ages[host])):
                ages[host] = age
    except Exception:
        return {}
    return ages


# ── check 2: pressure signal consistency (the false train-stale bug class) ────────────────

def check_pressure_consistency(file_age_s=None, db_age_s=None, stale_s=None):
    """Compare the pressure FILE's age against the pressure DB ROW's age.

    Diagnosis (5) in code form. Three distinguishable outcomes, and the middle one is the one
    that cost days:
      * both fresh                       -> healthy
      * DB fresh, file stale/absent      -> the FILE consumer is lying; fix the consumer, and
                                            never let it alert as though the train were stale
      * both stale                       -> the train really is stale
    Never raises.
    """
    stale_s = PRESSURE_STALE_S if stale_s is None else stale_s
    try:
        if file_age_s is None:
            marker = os.path.join(RUNTIME, "merge_train_pressure.json")
            try:
                file_age_s = time.time() - os.path.getmtime(marker)
            except OSError:
                file_age_s = None
        if db_age_s is None:
            db_age_s = _pressure_row_age()

        file_stale = file_age_s is None or file_age_s > stale_s
        db_stale = db_age_s is None or db_age_s > stale_s

        detail = {"file_age_s": None if file_age_s is None else round(file_age_s),
                  "db_age_s": None if db_age_s is None else round(db_age_s),
                  "stale_s": stale_s,
                  "authoritative": fic.AUTHORITATIVE_SOURCE}

        if not db_stale and file_stale:
            return fic.Verdict(
                fic.DEGRADED,
                "merge-train pressure is FRESH in the DB but stale/missing as a file — any check "
                "reading only the file will report a false train-stale (the 2026-08-02 bug class). "
                "Point the consumer at the DB, which is authoritative.",
                "fix_consumer", "pressure", detail)
        if db_stale and file_stale:
            return fic.Verdict(fic.STUCK,
                               "merge-train pressure is stale in BOTH the DB and the file — the "
                               "train genuinely is not running",
                               "fire_train", "pressure", detail)
        if db_stale and not file_stale:
            return fic.Verdict(fic.DEGRADED,
                               "merge-train pressure file is fresh but the DB row is stale — the "
                               "DB writer is failing while the file writer is not",
                               "investigate", "pressure", detail)
        return fic.Verdict(fic.HEALTHY, "", "", "pressure", detail)
    except Exception:
        return fic.Verdict(fic.HEALTHY, "", "", "pressure", {})


def _pressure_row_age():
    try:
        import db
        import merge_train
        key = getattr(merge_train, "PRESSURE_KEY", "merge_train_pressure")
        rows = db.select("controls", {"select": "updated_at", "key": f"eq.{key}", "limit": "1"}) or []
        return _age_s((rows[0] if rows else {}).get("updated_at"))
    except Exception:
        return None


# ── check 3: boot-commit marker ───────────────────────────────────────────────────────────

def check_boot_commit(paths=None):
    """The `.runner_boot_commit` marker must exist, or the stale-code check silently no-ops."""
    try:
        candidates = paths if paths is not None else [
            os.path.join(REPO, ".runner_boot_commit"),
            os.path.join(HERE, ".runner_boot_commit"),
        ]
        for path in candidates:
            try:
                if os.path.isfile(path) and open(path).read().strip():
                    return fic.Verdict(fic.HEALTHY, "", "", "boot_commit", {"path": path})
            except OSError:
                continue
        return fic.Verdict(
            fic.DEGRADED,
            "no .runner_boot_commit marker — sentinel cannot tell whether the runner is on "
            "current code, so its stale-code remediation does nothing, forever",
            "write_boot_commit", "boot_commit", {"looked_in": list(candidates)})
    except Exception:
        return fic.Verdict(fic.HEALTHY, "", "", "boot_commit", {})


def write_boot_commit(sha, path=None):
    """Write the boot-commit marker. Returns True on success. Never raises."""
    try:
        if not sha:
            return False
        target = path or os.path.join(REPO, ".runner_boot_commit")
        with open(target, "w") as f:
            f.write(str(sha).strip() + "\n")
        return True
    except Exception:
        return False


# ── check 4: release-train recovery-mode sanity ───────────────────────────────────────────

def check_release_recovery_mode(min_batch=None, since_ts=None, max_s=None, now=None):
    """Warn while RELEASE_MIN_BATCH=1 recovery mode has been active longer than `max_s`.

    Recovery mode is correct during an incident and wrong as a permanent state: a floor of 1
    releases every merge individually, which is exactly what the batch train exists to avoid.
    """
    max_s = RECOVERY_MODE_MAX_S if max_s is None else max_s
    try:
        if min_batch is None:
            min_batch = int(os.environ.get("RELEASE_MIN_BATCH", "1") or 1)
        if int(min_batch) > 1:
            return fic.Verdict(fic.HEALTHY, "", "", "release_mode", {"min_batch": int(min_batch)})
        age = _age_s(since_ts, now=now)
        detail = {"min_batch": int(min_batch), "age_s": None if age is None else round(age),
                  "max_s": max_s}
        if age is not None and age > max_s:
            return fic.Verdict(
                fic.DEGRADED,
                f"RELEASE_MIN_BATCH=1 recovery mode has been active {int(age / 3600)}h "
                f"(limit {int(max_s / 3600)}h) — confirm it is still needed or revert to batching",
                "review_release_mode", "release_mode", detail)
        return fic.Verdict(fic.HEALTHY, "", "", "release_mode", detail)
    except Exception:
        return fic.Verdict(fic.HEALTHY, "", "", "release_mode", {})


# ── the one WRITE: auto-revert of recovery mode ───────────────────────────────────────────

def evaluate_auto_revert(queued_count, state=None, now_t=None,
                         floor=None, sustain_s=None, min_batch=None):
    """Decide whether recovery-mode batching should be restored.

    Requires the queue to sit below `floor` CONTINUOUSLY for `sustain_s`; a single low reading
    is noise, and reverting on noise would re-strand small merges. Returns
    (should_revert: bool, new_state: dict, reason: str). Pure — no I/O. Never raises.
    """
    floor = AUTO_REVERT_QUEUE_FLOOR if floor is None else floor
    sustain_s = AUTO_REVERT_SUSTAIN_S if sustain_s is None else sustain_s
    state = dict(state or {})
    now_t = time.time() if now_t is None else now_t
    try:
        if min_batch is None:
            min_batch = int(os.environ.get("RELEASE_MIN_BATCH", "1") or 1)
        if int(min_batch) > 1:
            state.pop("below_floor_since", None)
            return False, state, "not in recovery mode"

        queued_count = int(queued_count)
        if queued_count >= floor:
            state.pop("below_floor_since", None)
            return False, state, f"queue at {queued_count} (floor {floor})"

        # `is None`, not falsiness: a timestamp of 0.0 is a real value, and treating it as
        # "unset" restarts the sustain window forever — the revert would never fire.
        since = state.get("below_floor_since")
        if since is None:
            state["below_floor_since"] = now_t
            return False, state, f"queue below {floor}; starting sustain window"

        elapsed = now_t - float(since)
        if elapsed < sustain_s:
            return False, state, (f"queue below {floor} for {int(elapsed / 3600)}h of "
                                  f"{int(sustain_s / 3600)}h required")
        state.pop("below_floor_since", None)
        return True, state, (f"queue below {floor} continuously for {int(elapsed / 3600)}h — "
                             f"restoring default release batching")
    except Exception:
        return False, state, "auto-revert evaluation failed"


def remove_env_override(key="RELEASE_MIN_BATCH", env_path=None):
    """Comment out `key=` in runner/.env so the default takes effect on the next load.

    Commented, not deleted: the incident record stays readable in the file. Returns True when
    the file changed. Never raises.
    """
    try:
        path = env_path or os.path.join(HERE, ".env")
        if not os.path.isfile(path):
            return False
        with open(path) as f:
            lines = f.readlines()
        changed = False
        stamp = datetime.date.today().isoformat()
        out = []
        for line in lines:
            if line.strip().startswith(f"{key}=") and not line.strip().startswith("#"):
                out.append(f"# auto-reverted {stamp} by pipeline_selftest (queue drained): {line.rstrip()}\n")
                changed = True
            else:
                out.append(line)
        if changed:
            with open(path, "w") as f:
                f.writelines(out)
        return changed
    except Exception:
        return False


# ── orchestration ─────────────────────────────────────────────────────────────────────────

def run(rows=None, control_rows=None, queued_count=None, state=None, apply_revert=True):
    """Run every self-test. Returns {"verdicts": [...], "reverted": bool, "state": {...}}."""
    result = {"verdicts": [], "reverted": False, "state": dict(state or load_state())}
    try:
        result["verdicts"].extend(check_machine_heartbeats(rows=rows, control_rows=control_rows))
        for verdict in (check_pressure_consistency(), check_boot_commit(),
                        check_release_recovery_mode(
                            since_ts=result["state"].get("recovery_mode_since"))):
            if verdict.actionable:
                result["verdicts"].append(verdict)

        if queued_count is None:
            queued_count = _queued_count()
        if queued_count is not None:
            should, new_state, reason = evaluate_auto_revert(queued_count, result["state"])
            result["state"] = new_state
            if should and apply_revert:
                result["reverted"] = remove_env_override()
                result["verdicts"].append(
                    fic.Verdict(fic.RELEASE_OK, reason,
                                "reverted" if result["reverted"] else "revert_failed",
                                "release_mode", {"queued": queued_count}))
        save_state(result["state"])
    except Exception:
        pass
    return result


def _queued_count():
    try:
        import db
        return db.count("tasks", {"select": "id", "state": "eq.QUEUED"})
    except Exception:
        return None


def render(result):
    """Operator summary. Never raises."""
    try:
        verdicts = result.get("verdicts", [])
        if not verdicts:
            return "pipeline self-test: all checks clear"
        lines = ["pipeline self-test: %d finding(s)" % len(verdicts)]
        for v in verdicts:
            lines.append(f"  [{v.state}] {v.subject}: {v.reason}")
        if result.get("reverted"):
            lines.append("  RELEASE_MIN_BATCH override removed — default batching restored")
        return "\n".join(lines)
    except Exception:
        return "pipeline self-test: report unavailable"


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    result = run(apply_revert="--no-revert" not in argv)
    if "--json" in argv:
        print(json.dumps({"verdicts": [v.to_dict() for v in result["verdicts"]],
                          "reverted": result["reverted"]}, indent=2))
    else:
        print(render(result))
    return 1 if result["verdicts"] else 0


if __name__ == "__main__":
    sys.exit(main())
