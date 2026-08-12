#!/usr/bin/env python3
"""
supervisor.py - the last piece of hands-off reliability. A tiny EXTERNAL process (separate from the
runner) that makes the system self-recovering: if the runner's heartbeat goes stale — crash, hang,
OOM-kill, or a bad hot-reload — the supervisor restarts it automatically. No human needed.

Because hot_reload keeps a healthy runner current without restarts, the supervisor only ever acts on a
genuinely DEAD runner. Each restart is recorded so a silent crash-loop is visible (and rate-limited).

Run once (survives runner crashes; install via launchd for boot persistence):
    python3 supervisor.py &
Env:
    SUPERVISOR_STALE_S   heartbeat age that means "dead"   (default 180)
    SUPERVISOR_INTERVAL  check cadence seconds             (default 30)
    RUNNER_CMD           command to (re)start the runner
"""
import os, sys, time, subprocess, socket, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

STALE_S = int(os.environ.get("SUPERVISOR_STALE_S", "180"))
INTERVAL = int(os.environ.get("SUPERVISOR_INTERVAL", "30"))
_DIR = os.path.dirname(os.path.abspath(__file__))
RUNNER_CMD = os.environ.get("RUNNER_CMD",
    f"cd {_DIR} && set -a; source .env; set +a; python3 runner.py")
MAX_RESTARTS_HR = int(os.environ.get("SUPERVISOR_MAX_RESTARTS_HR", "6"))  # crash-loop brake


def _runner_alive_locally():
    try:
        out = subprocess.run(["pgrep", "-f", "runner.py"], capture_output=True, text=True)
        return out.returncode == 0 and bool(out.stdout.strip())
    except Exception:
        return False


def _heartbeat_fresh():
    """Is THIS host's runner heartbeat fresh in the DB? None if unknown (no DB)."""
    try:
        import db
        host = socket.gethostname()
        for r in (db.select("runner_heartbeats", {"select": "hostname,last_seen",
                            "order": "last_seen.desc", "limit": "10"}) or []):
            if r.get("hostname") == host and r.get("last_seen"):
                t = datetime.datetime.fromisoformat(r["last_seen"].replace("Z", "+00:00"))
                age = (datetime.datetime.now(datetime.timezone.utc) - t).total_seconds()
                return age <= STALE_S
    except Exception:
        pass
    return None


MAINTENANCE_LOCK = os.environ.get(
    "ORCH_MAINTENANCE_LOCK",
    os.path.join(os.environ.get("CLAUDE_ORCH_HOME", _DIR), "maintenance.lock"),
)


def _maintenance_present():
    """Read the fence NOW, not at startup.

    keepalive.sh has always honoured this lock; supervisor.py did not, so the fence
    held against one path into a restart and was silently absent from the other.
    That asymmetry is how a runner starts during declared maintenance without
    anything looking broken.
    """
    return os.path.exists(MAINTENANCE_LOCK)


def _observe_ownership():
    """Gather what supervisor_ownership needs. Best-effort and fail-soft: a
    supervisor that crashes while checking whether it may act is worse than one
    that acts on partial information, so an unreadable fact becomes an absent fact
    and the ownership check reports it."""
    from supervisor_ownership import (
        LockState,
        OwnershipObservation,
        ProcessInfo,
        parse_launchctl_list,
    )

    def _pgrep(pattern):
        try:
            out = subprocess.run(["pgrep", "-fl", pattern], capture_output=True, text=True)
            found = []
            for line in (out.stdout or "").strip().splitlines():
                pid, _, cmd = line.partition(" ")
                if pid.isdigit() and int(pid) != os.getpid():
                    found.append(ProcessInfo(int(pid), cmd))
            return tuple(found)
        except Exception:
            return ()

    def _lock(path):
        try:
            if not os.path.exists(path):
                return LockState(path=path, exists=False)
            holder = None
            pid_file = os.path.join(path, "pid") if os.path.isdir(path) else path
            try:
                with open(pid_file) as handle:
                    raw = handle.read().strip()
                holder = int(raw) if raw.isdigit() else None
            except Exception:
                holder = None
            alive = False
            if holder:
                try:
                    os.kill(holder, 0)
                    alive = True
                except Exception:
                    alive = False
            return LockState(path=path, exists=True, holder_pid=holder, holder_alive=alive)
        except Exception:
            return LockState(path=path, exists=False)

    service = None
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
        service = parse_launchctl_list(out.stdout or "")
    except Exception:
        service = None

    home = os.environ.get("CLAUDE_ORCH_HOME", _DIR)
    return OwnershipObservation(
        service=service,
        repo_path=home,
        supervisor_lock=_lock(os.path.join(home, ".runtime", "keepalive.lock")),
        runner_lock=_lock(os.path.join(home, ".runtime", "runner.lock")),
        keepalive_processes=_pgrep("keepalive.sh"),
        runner_processes=_pgrep("runner.py"),
        coder_processes=_pgrep("agentic_implementer"),
        maintenance_lock_present=_maintenance_present(),
    )


def _record_incident(incident):
    try:
        import db
        db.insert("runner_health", {
            "runner_id": incident.runner_id, "hostname": incident.hostname,
            "status": incident.status, "detail": incident.detail[:1000]})
    except Exception:
        pass
    print(f"[supervisor] OWNERSHIP INCIDENT: {', '.join(incident.codes)}")


def _restart():
    # THE GATE. Ownership and the maintenance fence are checked before anything is
    # started, and an incident is recorded rather than silently corrected — a
    # supervisor that quietly fixes ownership is one whose ownership nobody can
    # reason about.
    try:
        from supervisor_ownership import assess_ownership, build_incident, may_restart

        observation = _observe_ownership()
        decision = may_restart(observation, maintenance_check=_maintenance_present)

        incident = build_incident(assess_ownership(observation), socket.gethostname())
        if incident is not None:
            _record_incident(incident)

        if not decision.allowed:
            print(f"[supervisor] restart withheld: {decision.reason}")
            return
    except ImportError:
        # Fail-soft: if the ownership module is unavailable the supervisor still
        # restarts a dead runner, but it says the gate was skipped rather than
        # implying it passed.
        print("[supervisor] ownership gate unavailable; restarting without it")

    subprocess.Popen(["bash", "-lc", RUNNER_CMD], cwd=_DIR)
    try:
        import db
        db.insert("runner_health", {"runner_id": "supervisor", "hostname": socket.gethostname(),
                  "status": "restarted", "detail": "supervisor restarted a dead/stale runner"})
    except Exception:
        pass
    print(f"[supervisor] restarted runner at {datetime.datetime.now().isoformat()}")


def main():
    print(f"[supervisor] supervising (stale>{STALE_S}s, every {INTERVAL}s)")
    restarts = []
    while True:
        fresh = _heartbeat_fresh()
        alive = _runner_alive_locally()
        dead = (fresh is False) or (fresh is None and not alive)
        if dead:
            now = time.time(); restarts = [t for t in restarts if now - t < 3600]
            if len(restarts) < MAX_RESTARTS_HR:
                _restart(); restarts.append(now)
            else:
                print("[supervisor] restart cap hit this hour — holding; needs a look")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
