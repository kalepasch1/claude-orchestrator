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


def _restart():
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
