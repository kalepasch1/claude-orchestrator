#!/usr/bin/env python3
"""
queue_velocity.py — PID-style queue velocity controller.

Tracks queue depth every 15 minutes. When the queue is growing (velocity positive for 2+
windows), proportionally throttle generators. When acceleration is positive (getting worse),
aggressively compact. When cumulative surplus (integral) is large, shelve lowest-EV work.

This replaces the blunt QUEUE_GEN_CEILING threshold with a smooth, adaptive controller
that keeps the queue draining without stalling improvement/recovery work.

Runs as a scheduled periodic job (every 15 minutes).
"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
STATE_FILE = os.path.join(HOME, "queue_velocity_state.json")
WINDOW_S = 900  # 15 minutes
MAX_HISTORY = 20  # keep 5 hours of history

# Generator jobs that can be paused (never pause improve/remediate/recovery)
PAUSABLE_GENERATORS = {
    "bizradar", "demand_mining.py", "capability_radar.py", "scout", "spec",
    "promote", "roadmap", "newapp", "committees"
}
# Flag file: when present, _fire_periodic skips these generators
GENERATOR_PAUSE_FILE = os.path.join(HOME, "generator_pause.json")

def _env_int(name, default):
    try:
        return int(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default


def _env_float(name, default):
    try:
        return float(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default


# Thresholds (env-tunable)
VELOCITY_PAUSE_THRESHOLD = _env_int("ORCH_QV_PAUSE_WINDOWS", 2)        # positive velocity for N windows -> pause generators
ACCELERATION_COMPACT_THRESHOLD = 0  # if acceleration > 0 (getting worse), compact
INTEGRAL_SHELVE_THRESHOLD = _env_int("ORCH_QV_INTEGRAL_SHELVE", 5000)  # cumulative surplus tasks -> shelve lowest 20%
SHELVE_PCT = _env_float("ORCH_QV_SHELVE_PCT", 0.20)                    # fraction of queue to shelve when integral is too high
SHELVE_MIN_DEPTH = _env_int("ORCH_QV_SHELVE_MIN_DEPTH", 500)           # I-action only fires above this depth
# Anti-windup clamp: the integral can otherwise grow without bound during a long
# backlog (or a metrics glitch) and then shelve work for hours after the queue
# has recovered.
INTEGRAL_MAX = _env_int("ORCH_QV_INTEGRAL_MAX", 3 * INTEGRAL_SHELVE_THRESHOLD)
# Shelving requires the integral to stay over threshold for N consecutive samples,
# so a single low-EV/high-integral blip (e.g. one bad measurement window) never
# shelves anything on its own.
SHELVE_CONSECUTIVE_REQUIRED = _env_int("ORCH_QV_SHELVE_CONSECUTIVE", 2)
# Zero-spend recovery check before shelving a task (see _shelve_lowest_ev)
RECOVERY_ENABLED = os.environ.get("ORCH_QV_RECOVERY_ENABLED", "true").lower() in ("1", "true", "yes", "on")

# Last run's decision, exposed so tests/operators can observe why the controller
# did (or did not) act. Updated atomically at the end of run().
_last_decision = {}


def last_decision():
    """Snapshot of the most recent run()'s controller decision."""
    return dict(_last_decision)


def _load_state():
    try:
        return json.load(open(STATE_FILE))
    except Exception:
        return {"history": [], "integral": 0, "paused_at": None}


def _save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _queue_depth():
    # Exact header count is O(1), avoids PostgREST's 1,000-row body cap, and raises
    # on transport failure. An outage must never masquerade as a drained queue.
    return db.count("tasks", {"state": "eq.QUEUED"})


def _pinned_depth():
    """Queued pinned (express-lane) tasks. Fail-soft: 0 means 'assume none'.

    Used only to subtract express work from the depth the integral accumulates, so a
    measurement problem degrades to the old behaviour rather than suppressing the I-action.
    """
    try:
        return db.count("tasks", {"state": "eq.QUEUED", "pinned": "is.true"}) or 0
    except Exception as e:
        print(f"[queue-velocity] pinned depth unavailable ({e}); treating as 0")
        return 0


def _pause_generators(reason):
    """Write a pause file that _fire_periodic checks before launching generators."""
    with open(GENERATOR_PAUSE_FILE, "w") as f:
        json.dump({"paused": True, "reason": reason, "jobs": list(PAUSABLE_GENERATORS),
                    "at": time.time()}, f)
    print(f"[queue-velocity] PAUSED generators: {reason}")


def _unpause_generators():
    """Remove the pause file so generators can run again."""
    try:
        os.remove(GENERATOR_PAUSE_FILE)
        print("[queue-velocity] UNPAUSED generators (queue draining)")
    except FileNotFoundError:
        pass


def _get_project(project_id):
    """Fetch project row for repo_path/default_base. Returns dict or None."""
    if not project_id:
        return None
    try:
        rows = db.select("projects", {"select": "id,repo_path,default_base",
                                      "id": f"eq.{project_id}"})
        return (rows or [None])[0]
    except Exception:
        return None


def _recovery_action(task):
    """Zero-spend recovery check before shelving a task.

    Returns (action, detail) where action is one of:
      'recovered'   — branch exists (local/worktree) or was mechanically
                      reconstructed from cached artifacts/reflog/merged diffs;
                      the task must NOT be shelved.
      'shelve'      — nothing recoverable was found; shelving may proceed.
      'infra_error' — DB/RPC/git infrastructure failed mid-check. Fail-soft
                      (branch_lease pattern): an infra outage is not proof the
                      work is unrecoverable, so the task must NOT be shelved.
    """
    if not RECOVERY_ENABLED:
        return "shelve", "recovery disabled"
    slug = (task.get("slug") or "").strip()
    if not slug:
        return "shelve", "no slug"
    try:
        import patch_recovery
        proj = _get_project(task.get("project_id"))
        repo = (proj or {}).get("repo_path") or ""
        if not repo or not os.path.isdir(repo):
            return "shelve", "no repo on disk"
        base = (proj or {}).get("default_base") or "main"

        detection = patch_recovery.detect_branch(repo, slug)
        if detection.get("found"):
            return "recovered", f"branch present ({detection.get('location')})"

        result = patch_recovery.recover(repo, slug, base,
                                        project=task.get("project_id"))
        if result.get("ok"):
            return "recovered", f"reconstructed via {result.get('method')}"
        return "shelve", result.get("reason") or "not recoverable"
    except Exception as e:
        return "infra_error", str(e)[:200]


def _shelve_lowest_ev(count):
    """Move the lowest-EV queued tasks to SHELVED state so the queue can drain.

    Before shelving each task, run a zero-spend recovery check: a task whose
    branch still exists or can be mechanically reconstructed keeps its queue
    slot instead of being shelved. Infra errors during the check are fail-soft
    (skip shelving that task) — mirrors runner/branch_lease.py.
    """
    try:
        # Get tasks ordered by confidence (lowest first = lowest EV).
        # Pinned tasks are excluded server-side: they are the express lane, and shelving one
        # is exactly the failure this controller caused before — a pinned burst arriving during
        # a backlog drove the integral over threshold, the I-action fired, and the express work
        # itself got shelved. Pinning is an explicit operator instruction; the PID does not get
        # to override it. Low confidence is not a reason to drop pinned work.
        tasks = db.select("tasks", {"select": "id,slug,confidence,project_id,pinned",
                                     "state": "eq.QUEUED",
                                     "pinned": "not.is.true",
                                     "order": "confidence.asc.nullsfirst",
                                     "limit": str(count)}) or []
        shelved = 0
        recovered = 0
        skipped_infra = 0
        for t in tasks:
            # Defence in depth. db.py documents deployments where pinned/pin_rank predate their
            # migration, so the server-side filter can be silently dropped; never rely on it alone.
            if t.get("pinned"):
                print(f"[queue-velocity] refusing to shelve pinned task {t.get('slug')}")
                continue
            action, detail = _recovery_action(t)
            if action == "recovered":
                recovered += 1
                print(f"[queue-velocity] kept {t.get('slug')}: {detail}")
                continue
            if action == "infra_error":
                skipped_infra += 1
                print(f"[queue-velocity] recovery check infra error for "
                      f"{t.get('slug')} ({detail}); fail-soft NOT SHELVED")
                continue
            try:
                db.update("tasks", {"id": t["id"]},
                          {"state": "SHELVED",
                           "note": f"shelved by queue-velocity PID (low EV, integral too high)"})
                shelved += 1
            except Exception:
                pass
        if shelved:
            print(f"[queue-velocity] shelved {shelved} lowest-EV tasks to drain backlog")
        if recovered or skipped_infra:
            print(f"[queue-velocity] shelve pass: recovered={recovered} "
                  f"infra_skipped={skipped_infra}")
        return shelved
    except Exception as e:
        print(f"[queue-velocity] shelve error: {e}")
        return 0


def run():
    global _last_decision
    state = _load_state()
    history = state.get("history", [])
    integral = state.get("integral", 0)
    shelve_pressure = state.get("shelve_pressure", 0)

    # Sample current queue depth
    try:
        depth = _queue_depth()
    except Exception as e:
        print(f"[queue-velocity] measurement failed; preserving controller state: {e}")
        return {"ok": False, "error": str(e), "measurement_valid": False}
    now = time.time()
    # The integral tracks BACKLOG surplus, and pinned work is not backlog — it is express-lane
    # work that claims ahead of everything and drains within a window or two. Accumulating it
    # was a windup source: a burst of pinned items spiked depth, the integral crossed the shelve
    # threshold, and the I-action then shelved queued work (previously including the pinned items
    # themselves) purely because the operator had pinned a batch. Integrate on the effective
    # (non-express) depth instead. Raw depth is still what the P/D actions and logs report.
    pinned_depth = _pinned_depth()
    effective_depth = max(0, depth - pinned_depth)
    history.append({"t": now, "depth": depth, "effective_depth": effective_depth})
    history = history[-MAX_HISTORY:]  # trim

    def _eff(entry):
        # History written before this change has no effective_depth; fall back to depth.
        return entry.get("effective_depth", entry.get("depth", 0))

    # Compute velocity (dQ/dt) — change per window
    velocity = 0
    if len(history) >= 2:
        velocity = history[-1]["depth"] - history[-2]["depth"]

    # Express-excluded velocity: what the integral accumulates.
    effective_velocity = 0
    if len(history) >= 2:
        effective_velocity = _eff(history[-1]) - _eff(history[-2])

    # Compute acceleration (d²Q/dt²) — change in velocity
    acceleration = 0
    if len(history) >= 3:
        prev_velocity = history[-2]["depth"] - history[-3]["depth"]
        acceleration = velocity - prev_velocity

    # Update integral (cumulative surplus), with anti-windup clamp
    if effective_velocity > 0:
        integral += effective_velocity
    else:
        # drain integral when the non-express queue shrinks
        integral = max(0, integral + effective_velocity)
    integral_clamped = integral > INTEGRAL_MAX
    integral = min(integral, INTEGRAL_MAX)

    # Count consecutive positive-velocity windows
    consecutive_positive = 0
    for i in range(len(history) - 1, 0, -1):
        if history[i]["depth"] > history[i-1]["depth"]:
            consecutive_positive += 1
        else:
            break

    # --- PID ACTIONS ---

    # P (proportional): pause generators when velocity positive for 2+ windows
    if consecutive_positive >= VELOCITY_PAUSE_THRESHOLD:
        _pause_generators(f"velocity positive for {consecutive_positive} windows "
                         f"(depth={depth}, velocity={velocity:+d})")
    elif velocity <= 0:
        _unpause_generators()

    # D (derivative): aggressive compact when acceleration positive
    if acceleration > 0 and consecutive_positive >= 2 and depth > 200:
        # Queue is growing AND getting worse — compact aggressively
        compact_count = min(50, int(depth * 0.05))
        _shelve_lowest_ev(compact_count)
        print(f"[queue-velocity] D-action: compacted {compact_count} (acceleration={acceleration:+d})")

    # I (integral): shelve lowest-EV when cumulative surplus is too high — but
    # only after the pressure has held for SHELVE_CONSECUTIVE_REQUIRED samples
    # in a row. A single over-threshold sample builds pressure; it never shelves.
    shelved = 0
    i_action = False
    # Gate on effective_depth for the same reason the integral does: a pinned burst must not be
    # what pushes the queue over the minimum-depth gate and starts shelving other work.
    if integral > INTEGRAL_SHELVE_THRESHOLD and effective_depth > SHELVE_MIN_DEPTH:
        shelve_pressure += 1
    else:
        shelve_pressure = 0
    if shelve_pressure >= SHELVE_CONSECUTIVE_REQUIRED:
        i_action = True
        shelve_count = int(effective_depth * SHELVE_PCT)
        shelved = _shelve_lowest_ev(shelve_count)
        integral = max(0, integral - shelve_count)  # reduce integral after shelving
        shelve_pressure = 0
        print(f"[queue-velocity] I-action: shelved {shelved}/{shelve_count} (integral={integral})")

    # Log state
    print(f"[queue-velocity] depth={depth} (pinned={pinned_depth} effective={effective_depth}) "
          f"velocity={velocity:+d} eff_velocity={effective_velocity:+d} accel={acceleration:+d} "
          f"integral={integral} consecutive_positive={consecutive_positive} "
          f"shelve_pressure={shelve_pressure}")

    state = {"history": history, "integral": integral, "paused_at": state.get("paused_at"),
             "shelve_pressure": shelve_pressure}
    _save_state(state)
    decision = {"depth": depth, "pinned_depth": pinned_depth,
                "effective_depth": effective_depth,
                "velocity": velocity, "effective_velocity": effective_velocity,
                "acceleration": acceleration,
                "integral": integral, "integral_clamped": integral_clamped,
                "consecutive_positive": consecutive_positive,
                "shelve_pressure": shelve_pressure, "i_action": i_action,
                "shelved": shelved}
    _last_decision = decision
    return decision


def is_generator_paused(job_name):
    """Called by _fire_periodic to check if a generator should be skipped."""
    try:
        data = json.load(open(GENERATOR_PAUSE_FILE))
        if data.get("paused") and job_name in (data.get("jobs") or []):
            # Auto-expire after 2 hours (safety valve)
            if time.time() - data.get("at", 0) > 7200:
                _unpause_generators()
                return False
            return True
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return False


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
