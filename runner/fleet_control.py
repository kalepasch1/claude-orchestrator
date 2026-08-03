#!/usr/bin/env python3
"""
fleet_control.py - the Mac-1 <-> Mac-2 (N-machine) coordination gateway.

Both runners already share one Supabase queue; this closes the last siloed gaps so you configure the
WHOLE fleet from one place (Mission Control / the DB) and never touch a second machine's terminal:

  1. CENTRAL CONFIG  - `fleet_config` (key/value) is loaded into env every loop on EVERY machine. Change
     MAX_PARALLEL / ORCH_EXTRA_CODERS / model policy / any ORCH_* knob once here and both Macs converge.
     Only safe config keys are applied (never secrets/keys/tokens).
  2. CENTRAL CONTROL - `fleet_control` rows (action: restart | git_pull | reload_config | pause | resume;
     target: hostname or 'all') are honored by the targeted machine(s), each acking into handled_by.
     Restart, pull-and-restart, or pause/resume a single Mac or the whole fleet from the cockpit — no
     ssh, no second terminal. pause is a soft, keepalive-safe stop: the runner stops claiming new work
     but stays resident (a hard launchd stop would fight keepalive and be un-resumable remotely), and
     resume lifts it on the next loop. Implemented via kill_switch's host scope.
  3. AUTO-UPDATE     - with ORCH_AUTO_PULL=true, each machine periodically `git pull --ff-only`, so a push
     from Mac 1 propagates to every machine automatically (no "now go run it on Mac 2 too").

Pure DB + git; no model spend. Fail-soft: any error is swallowed so it can never wedge the runner.
"""
import os, sys, time, socket, subprocess, datetime, asyncio, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import kill_switch
import config_approval

try:
    import websockets
    import websockets.exceptions
    _WEBSOCKETS_AVAILABLE = True
except ImportError:
    _WEBSOCKETS_AVAILABLE = False

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST = socket.gethostname()
_last_pull = {"t": 0.0}
_ws_server = None


def set_websocket_server(ws):
    """Inject a WebSocket server so update_fleet_config can publish ConfigChanged events."""
    global _ws_server
    _ws_server = ws

# only these config keys may be pushed fleet-wide (never secrets). Anything containing a credential
# marker is rejected outright. Note: ORCH_GIT_PAT is *not* stored in fleet_config (PAT value comes
# from local env). Use ORCH_GIT_AUTH_REQUIRED to signal that auth is needed; the actual PAT is
# managed per-machine via environment.
_SAFE_PREFIXES = ("ORCH_", "MAX_PARALLEL", "PER_TASK_GB", "RAM_FLOOR_GB", "RAM_", "RELEASE_", "QUEUE_",
                  "CONT_", "JANITOR_", "REMEDIATION_", "DEFAULT_TEST_CMD", "TASK_TIMEOUT", "ENABLE_",
                  "SESSION_", "ACCOUNT_COOLDOWN", "MERGE_", "DEPLOY_", "INTEGRATE_", "COST_",
                  # 2026-07-30: these families were pushed to fleet_config but silently NOT applied
                  # (prefix missing here) — OLLAMA model selection, committee/docket cadence, and
                  # dedupe thresholds are all secret-free tuning knobs; _DENY_MARKERS still blocks
                  # anything key/token-shaped regardless of prefix.
                  "OLLAMA_", "COMMITTEE_", "LEGAL_DOCKET", "SEMANTIC_DEDUPE", "SWARM_", "CADE_")
_DENY_MARKERS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "PWD", "CREDENTIAL", "PAT")


def _safe_key(k):
    ku = k.upper()
    if any(m in ku for m in _DENY_MARKERS):
        return False
    return any(ku.startswith(p) for p in _SAFE_PREFIXES)


# CONFIG PRECEDENCE (2026-08-03). fleet_config (the DB) is the fleet-wide SOURCE OF TRUTH and
# deliberately outranks runner/.env — but it used to do so SILENTLY and unconditionally, on every
# loop. A machine-local memory retune written into .env (MAX_PARALLEL_CEILING=24, RAM_FLOOR_GB=6,
# PER_TASK_GB=0.75) was therefore replaced by stale DB values (10 / 1.0 / 0.5) on the very next
# tick, and the two sources disagreed with nothing in any log to say so. RAM_FLOOR_GB=1.0 in
# particular let the governor admit tasks until only 1GB was free, which is how the runner earned
# its SIGKILL(137) deaths. Two changes, both reversible:
#   1. ORCH_CONFIG_ENV_PINS — comma-separated keys whose LOCAL .env value wins over the DB, for
#      genuinely per-machine knobs. Empty by default, so DB precedence is unchanged out of the box.
#   2. every *effective* change is logged once (both sides shown), so precedence is auditable
#      instead of invisible. Logged on change only — this runs every loop.
_applied_config = {}


def _env_pins():
    """Keys pinned to this machine's local .env value; fleet_config cannot override them."""
    raw = os.environ.get("ORCH_CONFIG_ENV_PINS", "")
    return {p.strip().upper() for p in raw.split(",") if p.strip()}


def load_config():
    """Apply central fleet_config into this process's env (safe keys only, gated keys skipped).

    Precedence: fleet_config (DB) > runner/.env, EXCEPT for keys named in ORCH_CONFIG_ENV_PINS,
    where the local .env wins. Every change is logged to stderr with both values.
    """
    n = 0
    try:
        blocked = config_approval.blocked_keys()
        pins = _env_pins()
        for row in (db.select("fleet_config", {"select": "key,value"}) or []):
            k, v = row.get("key"), row.get("value")
            if k and v is not None and _safe_key(k) and k not in blocked:
                new = str(v)
                if k.upper() in pins:
                    if _applied_config.get(k) != "\0pin\0" + new:
                        _applied_config[k] = "\0pin\0" + new
                        sys.stderr.write(
                            f"[fleet_control] config {k}: PINNED to local .env value "
                            f"{os.environ.get(k, '<unset>')!r}; ignoring fleet_config {new!r}\n")
                    continue
                cur = os.environ.get(k)
                if cur != new and _applied_config.get(k) != new:
                    sys.stderr.write(
                        f"[fleet_control] config {k}: fleet_config {new!r} overrides local {cur!r}\n")
                _applied_config[k] = new
                os.environ[k] = new
                n += 1
    except Exception as e:
        # FIX 2026-07-29: `log` was never defined — a config-load failure made the error handler
        # itself raise NameError, masking the real failure. Plain stderr keeps it dependency-free.
        import sys
        sys.stderr.write(f"[fleet_control] fleet_config load failed: {e}\n")
    return n


def get_fleet_config(key, default=""):
    """Get a fleet_config value from environment with ORCH_ prefix validation.

    Reads ORCH_{key} from env (loaded via load_config). Returns default on
    missing/invalid keys. Never raises — fail-soft by design.
    """
    if not key or not isinstance(key, str):
        return default
    try:
        env_key = f"ORCH_{key}".upper()
        value = os.environ.get(env_key, "").strip()
        return value if value else default
    except Exception:
        return default


def update_fleet_config(key, value):
    """Upsert a fleet config key and publish a ConfigChanged event for ORCH_* keys.

    Emits to 'config/*' via the injected WebSocket server when:
      - the key starts with ORCH_
      - the new value differs from what was stored
      - a WebSocket server has been registered via set_websocket_server()
    Fail-soft: errors in event emission are swallowed.
    """
    if not _safe_key(key):
        raise ValueError(f"refusing unsafe fleet config key: {key}")
    new_value = str(value)
    old_value = None
    try:
        rows = db.select("fleet_config", {"select": "value", "key": f"eq.{key}", "limit": "1"}) or []
        if rows:
            old_value = str(rows[0].get("value") or "")
    except Exception:
        pass
    row = {
        "key": key,
        "value": new_value,
        "updated_by": HOST,
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    db.insert("fleet_config", row, upsert=True)
    if _ws_server is not None and key.upper().startswith("ORCH_") and new_value != old_value:
        try:
            _ws_server.publish_event("config/*", {
                "event_type": "config_changed",
                "key": key,
                "old_value": old_value,
                "new_value": new_value,
                "timestamp": int(time.time() * 1000),
                "publisher": "fleet_control",
            })
        except Exception:
            pass
    return row


def _git(*args, timeout=120):
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, timeout=timeout)


def _host_aliases():
    aliases = {HOST}
    if HOST.endswith(".local"):
        aliases.add(HOST[:-6])
    else:
        aliases.add(HOST + ".local")
    return aliases


def _target_matches(target):
    return target == "all" or target in _host_aliases()


def _restart():
    """Exit; keepalive.sh respawns a fresh runner with new code/config.

    Do not unlink runner.lock here. The running process holds an flock on that file; deleting it
    creates a new inode that another supervisor can lock before this process exits, causing two
    runners to operate on the same machine. Exiting naturally releases the existing flock.
    """
    print(f"fleet_control: restart requested — exiting for keepalive respawn ({HOST})", flush=True)
    os._exit(0)


# Code-drift self-restart (2026-07-31): Python doesn't hot-reload. Whenever code lands
# on disk by ANY path (committer local commit, manual pull, another process's pull),
# the running runner used to keep executing stale in-memory modules until a HUMAN
# restarted it (the Mac-2 "0 live machines" incident). This closes that class:
# capture HEAD at import; every tick, if disk HEAD differs AND the diff touches
# runner code, self-restart via keepalive — debounced by minimum uptime.
_STARTED_AT = time.time()
try:
    _STARTUP_HEAD = _git("rev-parse", "HEAD").stdout.strip()
except Exception:
    _STARTUP_HEAD = ""


_drift_seen = {"t": 0.0}


def _local_active_tasks():
    """Best-effort count of tasks in flight on THIS host. Returns 0 when unknown.

    Fail-soft by design: if we cannot tell, we return 0 so drift restart keeps its
    original (eager) behaviour rather than deferring forever on a broken query.
    """
    try:
        rows = db.select("runner_heartbeats", {
            "select": "active_tasks,last_seen,hostname",
            "hostname": f"eq.{HOST}",
        }) or []
        now = datetime.datetime.now(datetime.timezone.utc)
        total = 0
        for r in rows:
            try:
                seen = datetime.datetime.fromisoformat(
                    str(r.get("last_seen") or "").replace("Z", "+00:00"))
            except Exception:
                continue
            # only trust heartbeats from live runners
            if (now - seen).total_seconds() <= 300:
                total += int(r.get("active_tasks") or 0)
        return total
    except Exception:
        return 0


def code_drift_restart():
    """Self-restart when the running process is older than the code on disk."""
    if os.environ.get("ORCH_CODE_DRIFT_RESTART", "true").lower() not in ("true", "1", "yes"):
        return False
    min_uptime = float(os.environ.get("ORCH_CODE_DRIFT_MIN_UPTIME", "300"))
    if not _STARTUP_HEAD or (time.time() - _STARTED_AT) < min_uptime:
        return False
    try:
        head = _git("rev-parse", "HEAD").stdout.strip()
        if not head or head == _STARTUP_HEAD:
            return False
        changed = _git("diff", "--name-only", _STARTUP_HEAD, head).stdout or ""
        touched = [l for l in changed.splitlines()
                   if l.startswith("runner/") and l.endswith(".py")]
        if not touched:
            return False
        # GRACEFUL DRAIN (2026-08-02): _restart() is os._exit(0) — it kills every
        # in-flight task mid-execution, which reverts them to QUEUED and throws away
        # the work. When the orchestrator is improving its OWN runner/ code, drift is
        # near-continuous (~6 commits/hr to runner/*.py), so an eager restart livelocks
        # the fleet: measured 5 restarts in one hour vs 1 merge in that hour, with the
        # runner never surviving long enough to finish a task. Defer while work is in
        # flight — but never past the deadline, so stale code cannot run indefinitely.
        busy = _local_active_tasks()
        max_defer = float(os.environ.get("ORCH_CODE_DRIFT_MAX_DEFER", "3600"))
        if busy > 0:
            if not _drift_seen["t"]:
                _drift_seen["t"] = time.time()
            waited = time.time() - _drift_seen["t"]
            if waited < max_defer:
                print(f"fleet_control: code drift {_STARTUP_HEAD[:8]}->{head[:8]} "
                      f"({len(touched)} runner .py files) — deferring restart, {busy} task(s) "
                      f"in flight ({waited:.0f}s/{max_defer:.0f}s) on {HOST}", flush=True)
                return False
            print(f"fleet_control: code drift defer deadline reached after {waited:.0f}s — "
                  f"restarting with {busy} task(s) still in flight on {HOST}", flush=True)
        print(f"fleet_control: code drift {_STARTUP_HEAD[:8]}->{head[:8]} "
              f"({len(touched)} runner .py files) — self-restarting on {HOST}", flush=True)
        _restart()
        return True  # unreachable; keeps the contract explicit
    except Exception as e:
        print(f"fleet_control: code-drift check failed ({e})", flush=True)
        return False


def _pull_safe():
    """Check if it's safe to git pull. Returns (ok, reason).

    Untracked files (`??`) do NOT block a pull — git pull never touches them.
    Counting them made every machine with intake/processed/*.md droppings skip
    auto-pull forever (the Mac-2 stale-code incident, 2026-07-31). Only tracked
    modifications (M/A/D/R/U) are genuinely unsafe.
    """
    try:
        status = _git("status", "--porcelain")
        if status.returncode != 0:
            return False, "git status failed"
        dirty = [l for l in (status.stdout or "").strip().splitlines()
                 if l.strip() and not l.startswith("??")]
        if dirty:
            return False, f"{len(dirty)} dirty tracked files"
        branch = _git("rev-parse", "--abbrev-ref", "HEAD")
        current = (branch.stdout or "").strip()
        default = os.environ.get("ORCH_DEFAULT_BRANCH", "master")
        if current != default:
            return False, f"on branch {current}, not {default}"
        return True, "ok"
    except Exception as e:
        return False, str(e)


def self_update():
    """Periodic git pull so every machine tracks the pushed code without manual per-Mac steps."""
    if os.environ.get("ORCH_AUTO_PULL", "false").lower() not in ("true", "1", "yes"):
        return False
    interval = float(os.environ.get("ORCH_AUTO_PULL_MIN", "5")) * 60
    if time.time() - _last_pull["t"] < interval:
        return False
    _last_pull["t"] = time.time()
    try:
        ok, reason = _pull_safe()
        if not ok:
            print(f"fleet_control: auto-pull skipped ({reason})", flush=True)
            return False
        before = _git("rev-parse", "HEAD").stdout.strip()
        pulled = _git("pull", "--ff-only")
        if pulled.returncode != 0:
            msg = (pulled.stderr or pulled.stdout or "git pull failed").strip()
            raise RuntimeError(msg[-500:])
        after = _git("rev-parse", "HEAD").stdout.strip()
        if before and after and before != after:
            print(f"fleet_control: auto-pulled {before[:8]}->{after[:8]} on {HOST}", flush=True)
            if os.environ.get("ORCH_AUTO_PULL_RESTART", "true").lower() in ("true", "1", "yes"):
                _restart()
            return True
    except Exception as e:
        print(f"fleet_control: auto-pull failed ({e})")
    return False


def process_controls():
    """Honor control actions targeted at this host (or 'all')."""
    done = 0
    try:
        rows = db.select("fleet_control", {"select": "*", "done": "eq.false",
                                           "order": "requested_at.asc", "limit": "50"}) or []
    except Exception:
        return 0
    # Restart-storm guard: only the NEWEST pending restart matters; a host coming back
    # after downtime must not churn through the whole backlog one respawn at a time.
    # Older pending restarts this host would act on are marked superseded up front.
    restart_ids = [r["id"] for r in rows if str(r.get("action") or "").lower() == "restart"]
    superseded = set(restart_ids[:-1]) if len(restart_ids) > 1 else set()
    for r in rows:
        target = str(r.get("target") or "all")
        handled = r.get("handled_by") or []
        aliases = _host_aliases()
        if not _target_matches(target) or any(h in handled for h in aliases):
            continue
        if r["id"] in superseded:
            try:
                db.update("fleet_control", {"id": r["id"]},
                          {"done": True, "last_error": f"superseded by newer restart ({HOST})"})
            except Exception:
                pass
            continue
        action = str(r.get("action") or "").lower()
        try:
            if action == "reload_config":
                load_config()
            elif action == "git_pull":
                ok, reason = _pull_safe()
                if not ok:
                    raise RuntimeError(f"git_pull unsafe: {reason}")
                pulled = _git("pull", "--ff-only")
                if pulled.returncode != 0:
                    msg = (pulled.stderr or pulled.stdout or "git pull failed").strip()
                    raise RuntimeError(msg[-500:])
            elif action == "restart":
                pass
            elif action == "pause":
                # soft, keepalive-safe: the runner's claim loop honors this host-scoped
                # pause (kill_switch.is_paused) and stops claiming without exiting.
                reason = str((r.get("params") or {}).get("reason") or "fleet pause")
                kill_switch.pause(scope="host", project=HOST, reason=reason, by="fleet_control")
            elif action == "resume":
                kill_switch.resume(scope="host", project=HOST, by="fleet_control")
            else:
                raise RuntimeError(f"unknown fleet action: {action}")
            # ack this host. A target='all' row completes when every LIVE fleet host has
            # handled it (from runner_heartbeats, fresh <30 min), or — heartbeats absent —
            # falls back to age-based completion (>6h old with at least this ack). The old
            # `done = (target != "all")` left 'all' rows pending forever (44-row backlog).
            new_handled = list(dict.fromkeys(handled + [HOST]))
            params = r.get("params") or {}
            all_done = target != "all"
            if not all_done:
                try:
                    hb = db.select("runner_heartbeats", {"select": "hostname", "limit": "20"}) or []
                    live = {str(h.get("hostname") or "") for h in hb if h.get("hostname")}
                    if live:
                        all_done = live.issubset(set(new_handled))
                except Exception:
                    pass
                if not all_done:
                    try:
                        import dateutil.parser as _dp  # optional; fall through on absence
                        age_h = (datetime.datetime.now(datetime.timezone.utc)
                                 - _dp.parse(str(r.get("requested_at")))).total_seconds() / 3600
                        all_done = age_h > 6
                    except Exception:
                        pass
            db.update("fleet_control", {"id": r["id"]},
                      {"handled_by": new_handled, "done": all_done})
            done += 1
            if action == "git_pull" and params.get("restart", True):
                _restart()
            if action == "restart":
                _restart()
        except Exception as e:
            print(f"fleet_control: action '{action}' failed on {HOST}: {e}")
            try:
                db.update("fleet_control", {"id": r["id"]}, {
                    "attempts": int(r.get("attempts") or 0) + 1,
                    "last_error": str(e)[:1000],
                    "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                })
            except Exception:
                pass
    return done


def tick():
    """One coordination cycle — call from the main loop and/or the scheduler. Fail-soft."""
    try:
        config_approval.sweep()
        load_config()
        process_controls()
        self_update()
        code_drift_restart()
    except Exception as e:
        print(f"fleet_control: tick error ({e})")


class FleetWebSocketServer:
    """WebSocket server for real-time fleet runner connections."""

    def __init__(self, port=None, heartbeat_interval=None):
        self._port = port if port is not None else int(os.environ.get("FLEET_WS_PORT", "8765"))
        self._heartbeat_interval = (
            heartbeat_interval if heartbeat_interval is not None
            else float(os.environ.get("FLEET_WS_PING_INTERVAL", "30"))
        )
        self._sessions = {}        # hostname -> websocket
        self._lock = asyncio.Lock()
        self._subscriptions = {}   # channel -> [callback]
        self._server = None

    async def start(self):
        if not _WEBSOCKETS_AVAILABLE:
            raise RuntimeError("websockets package required: pip install websockets")
        self._server = await websockets.serve(self._handle_connection, "0.0.0.0", self._port)

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        async with self._lock:
            for ws in list(self._sessions.values()):
                try:
                    await ws.close()
                except Exception:
                    pass
            self._sessions.clear()

    async def _handle_connection(self, websocket):
        hostname = None
        try:
            raw = await asyncio.wait_for(websocket.recv(), timeout=10)
            try:
                msg = json.loads(raw)
                hostname = msg.get("hostname") or str(websocket.remote_address[0])
            except Exception:
                hostname = str(websocket.remote_address[0])
            async with self._lock:
                self._sessions[hostname] = websocket
            recv_task = asyncio.create_task(self._recv_loop(websocket))
            beat_task = asyncio.create_task(self._heartbeat_loop(websocket))
            _done, pending = await asyncio.wait([recv_task, beat_task], return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
        except Exception:
            pass
        finally:
            if hostname:
                async with self._lock:
                    if self._sessions.get(hostname) is websocket:
                        del self._sessions[hostname]

    async def _recv_loop(self, websocket):
        async for raw in websocket:
            try:
                msg = json.loads(raw)
                channel = msg.get("channel")
                if channel:
                    for cb in list(self._subscriptions.get(channel, [])):
                        try:
                            result = cb(channel, msg)
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception:
                            pass
            except Exception:
                pass

    async def _heartbeat_loop(self, websocket):
        while True:
            await asyncio.sleep(self._heartbeat_interval)
            try:
                pong_waiter = await websocket.ping()
                await asyncio.wait_for(asyncio.shield(pong_waiter), timeout=10)
            except asyncio.TimeoutError:
                try:
                    await websocket.close(1001, "heartbeat timeout")
                except Exception:
                    pass
                return
            except Exception:
                return

    def subscribe(self, channel, callback):
        self._subscriptions.setdefault(channel, []).append(callback)

    async def publish(self, channel, message):
        payload = json.dumps({"channel": channel, "data": message})
        for cb in list(self._subscriptions.get(channel, [])):
            try:
                result = cb(channel, message)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                pass
        async with self._lock:
            sockets = list(self._sessions.values())
        for ws in sockets:
            try:
                await ws.send(payload)
            except Exception:
                pass


if __name__ == "__main__":
    print(f"fleet_control on {HOST}: config-keys={load_config()}, controls={process_controls()}")
