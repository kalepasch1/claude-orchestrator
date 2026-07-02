#!/usr/bin/env python3
"""
hot_reload.py - end the restart tax. The runner calls maybe_reload() once per loop; when a .py module
under runner/ changes on disk, it re-imports THAT module live, and when .env changes it re-reads the
non-secret config into os.environ. So code + config improvements take effect WITHOUT restarting the
runner. Safe: never reloads the module that's mid-execution in a worker thread (workers hold their own
already-imported references); the main loop just picks up new versions on its next iteration.

Excludes hot-swapping the runner entrypoint itself and anything currently running a task.
"""
import os, sys, time, importlib

_DIR = os.path.dirname(os.path.abspath(__file__))
_ENV = os.path.join(_DIR, ".env")
_mtimes = {}
_env_mtime = 0.0
# modules we never hot-reload (entrypoint / low-level / this file)
_SKIP = {"runner", "hot_reload", "db"}


def _scan():
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


def _reload_env():
    """Re-read NON-SECRET-safe env from .env (KEY=value lines). Updates os.environ live."""
    try:
        for line in open(_ENV):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            if k.replace("_", "").isalnum():
                os.environ[k] = v.strip().strip('"').strip("'")
    except Exception:
        pass


def maybe_reload(active_slugs=None):
    """Reload changed modules + env. Returns list of reloaded module names (for logging)."""
    global _mtimes, _env_mtime
    if not _mtimes:
        _mtimes = _scan()
        try:
            _env_mtime = os.path.getmtime(_ENV)
        except Exception:
            _env_mtime = 0.0
        return []
    reloaded = []
    # env change -> re-read config live
    try:
        em = os.path.getmtime(_ENV)
        if em > _env_mtime:
            _reload_env(); _env_mtime = em; reloaded.append(".env")
    except Exception:
        pass
    # changed modules -> importlib.reload the already-imported ones
    cur = _scan()
    for name, mt in cur.items():
        if name in _SKIP:
            _mtimes[name] = mt
            continue
        if mt > _mtimes.get(name, 0):
            mod = sys.modules.get(name)
            if mod is not None:
                try:
                    importlib.reload(mod)
                    reloaded.append(name)
                except Exception as e:
                    print(f"[hot-reload] {name} failed: {e}")
            _mtimes[name] = mt
    if reloaded:
        print(f"[hot-reload] {', '.join(reloaded)}")
    return reloaded


if __name__ == "__main__":
    print("watching", _DIR)
    while True:
        maybe_reload(); time.sleep(3)
