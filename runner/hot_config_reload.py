#!/usr/bin/env python3
"""
hot_config_reload.py - live config, env, and module reload without restart.

The orchestrator runs as a long-lived process. This module watches runner/ files,
.env changes, and DB config (controls table) in a background thread, reloading
schedule, env, and modules LIVE so improvements take effect with NO restart.

Builds on hot_reload.py with: background watcher thread, DB config awareness,
pause/resume for mid-task safety, change callbacks, and reload stats.

Fail-soft: every public function catches exceptions and returns safe defaults.
"""
import os, sys, time, importlib, threading, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

_DIR = os.path.dirname(os.path.abspath(__file__))
_ENV = os.path.join(_DIR, ".env")
# Modules we never hot-reload (entrypoint / low-level / self)
_SKIP = {"runner", "hot_reload", "hot_config_reload", "db"}

# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------
_file_mtimes: dict = {}          # module_name -> last mtime
_env_mtime: float = 0.0         # .env file mtime
_db_config_hash: str = ""       # hash of last DB config snapshot
_schedule_hash: str = ""        # hash of last schedule snapshot
_callbacks: list = []           # on-change callbacks
_task_running = threading.Lock() # held during task execution
_paused = threading.Event()      # clear = paused, set = running
_paused.set()                    # start unpaused
_watcher_thread = None
_watcher_stop = threading.Event()

_stats = {
    "reloads": 0,
    "env_reloads": 0,
    "schedule_reloads": 0,
    "files_watched": 0,
    "last_check": 0.0,
    "errors": 0,
    "started_at": 0.0,
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _scan_files() -> dict:
    """Return {module_name: mtime} for all .py files in runner/."""
    out = {}
    try:
        for f in os.listdir(_DIR):
            if f.endswith(".py"):
                p = os.path.join(_DIR, f)
                try:
                    out[f[:-3]] = os.path.getmtime(p)
                except Exception:
                    pass
    except Exception:
        pass
    return out


def _hash_dict(d: dict) -> str:
    try:
        return str(hash(json.dumps(d, sort_keys=True, default=str)))
    except Exception:
        return ""


def _read_db_config() -> dict:
    """Read config from the controls table."""
    try:
        rows = db.select("controls", {"select": "key,value"}) or []
        return {r["key"]: r["value"] for r in rows}
    except Exception:
        return {}


def _read_schedule() -> dict:
    """Read schedule config from DB or file."""
    try:
        rows = db.select("controls", {
            "select": "key,value",
            "key": "like.schedule_*",
        }) or []
        return {r["key"]: r["value"] for r in rows}
    except Exception:
        return {}


def _fire_callbacks(changes: dict):
    """Notify all registered callbacks of changes."""
    for cb in _callbacks:
        try:
            cb(changes)
        except Exception:
            _stats["errors"] += 1


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_files() -> list:
    """Compare file mtimes against last known state. Returns list of changed module names."""
    global _file_mtimes
    changed = []
    try:
        cur = _scan_files()
        _stats["files_watched"] = len(cur)
        if not _file_mtimes:
            _file_mtimes = cur
            return []
        for name, mt in cur.items():
            if name in _SKIP:
                continue
            if mt > _file_mtimes.get(name, 0):
                changed.append(name)
        _file_mtimes = cur
    except Exception:
        _stats["errors"] += 1
    return changed


def reload_module(name: str) -> bool:
    """Safely reload a Python module. Guards against reloading mid-task."""
    if not _task_running.acquire(blocking=False):
        return False  # task running, skip reload
    try:
        mod = sys.modules.get(name)
        if mod is None:
            return False
        importlib.reload(mod)
        _stats["reloads"] += 1
        return True
    except Exception as e:
        _stats["errors"] += 1
        print(f"[hot-config-reload] reload {name} failed: {e}")
        return False
    finally:
        _task_running.release()


def reload_env() -> dict:
    """Re-read .env file and update os.environ with changed values. Returns dict of changed keys."""
    global _env_mtime
    changed = {}
    try:
        try:
            mt = os.path.getmtime(_ENV)
        except OSError:
            return changed
        if mt <= _env_mtime and _env_mtime > 0:
            return changed
        _env_mtime = mt
        with open(_ENV) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.split("#")[0].strip().strip('"').strip("'")
                if not k.replace("_", "").isalnum():
                    continue
                old = os.environ.get(k)
                if old != v:
                    changed[k] = v
                    os.environ[k] = v
        if changed:
            _stats["env_reloads"] += 1
    except Exception:
        _stats["errors"] += 1
    return changed


def reload_schedule() -> bool:
    """Re-read schedule config from DB. Returns True if schedule changed."""
    global _schedule_hash
    try:
        sched = _read_schedule()
        h = _hash_dict(sched)
        if h != _schedule_hash and _schedule_hash:
            _schedule_hash = h
            _stats["schedule_reloads"] += 1
            return True
        _schedule_hash = h
        return False
    except Exception:
        _stats["errors"] += 1
        return False


def on_change(callback: callable) -> None:
    """Register a callback to be called when any config changes."""
    if callback not in _callbacks:
        _callbacks.append(callback)


def pause() -> None:
    """Pause watching (used during task execution to prevent mid-task reloads)."""
    _paused.clear()


def resume() -> None:
    """Resume watching after task execution."""
    _paused.set()


def manual_reload(module_name: str = None) -> dict:
    """Force a manual reload. If module_name given, reload just that; otherwise reload all changed."""
    result = {"modules": [], "env": {}, "schedule": False, "errors": []}
    try:
        if module_name:
            ok = reload_module(module_name)
            if ok:
                result["modules"].append(module_name)
            else:
                result["errors"].append(f"failed to reload {module_name}")
        else:
            changed = check_files()
            for name in changed:
                if reload_module(name):
                    result["modules"].append(name)
            result["env"] = reload_env()
            result["schedule"] = reload_schedule()
    except Exception as e:
        result["errors"].append(str(e))
        _stats["errors"] += 1
    if result["modules"] or result["env"] or result["schedule"]:
        _fire_callbacks(result)
    return result


def stats() -> dict:
    """Module statistics: reloads performed, files watched, last check time, errors."""
    return dict(_stats)


def _watcher_loop(interval_s: float):
    """Background watcher thread body."""
    global _file_mtimes, _env_mtime
    # Initialize baselines
    _file_mtimes = _scan_files()
    try:
        _env_mtime = os.path.getmtime(_ENV)
    except OSError:
        pass
    _stats["started_at"] = time.time()

    while not _watcher_stop.is_set():
        _watcher_stop.wait(interval_s)
        if _watcher_stop.is_set():
            break
        # Respect pause
        if not _paused.is_set():
            continue
        _stats["last_check"] = time.time()
        try:
            changes = {}
            # 1. Check file changes
            changed_modules = check_files()
            reloaded = []
            for name in changed_modules:
                if reload_module(name):
                    reloaded.append(name)
            if reloaded:
                changes["modules"] = reloaded
            # 2. Check env changes
            env_changes = reload_env()
            if env_changes:
                changes["env"] = env_changes

            # 3. Check DB config / schedule changes
            if reload_schedule():
                changes["schedule"] = True

            # 4. Check DB controls table for config changes
            try:
                cfg = _read_db_config()
                h = _hash_dict(cfg)
                global _db_config_hash
                if h != _db_config_hash and _db_config_hash:
                    changes["db_config"] = True
                _db_config_hash = h
            except Exception:
                _stats["errors"] += 1

            if changes:
                print(f"[hot-config-reload] changes detected: {list(changes.keys())}")
                _fire_callbacks(changes)
        except Exception:
            _stats["errors"] += 1


def watch(interval_s: float = 5.0) -> None:
    """Start a background thread that periodically checks for changes."""
    global _watcher_thread
    if _watcher_thread is not None and _watcher_thread.is_alive():
        return  # already watching
    _watcher_stop.clear()
    _watcher_thread = threading.Thread(
        target=_watcher_loop,
        args=(interval_s,),
        daemon=True,
        name="hot-config-reload",
    )
    _watcher_thread.start()


def stop() -> None:
    """Stop the background watcher thread."""
    _watcher_stop.set()
    if _watcher_thread is not None:
        _watcher_thread.join(timeout=10)


if __name__ == "__main__":
    print(f"[hot-config-reload] watching {_DIR}")
    watch(interval_s=3.0)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop()
        print("\n[hot-config-reload] stopped")
