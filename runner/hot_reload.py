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
_deferred_log_t = 0.0


def _active_count(active_slugs):
    """How many tasks the caller reports in flight. None means 'caller did not say'."""
    if active_slugs is None:
        return None
    try:
        return len(active_slugs)
    except TypeError:
        return int(bool(active_slugs))


def _idle_enough(active_slugs):
    """True only when it is safe to swap code under this process.

    Safe means: the caller told us how many tasks are in flight AND that number is zero.
    An unknown in-flight count is treated as unsafe — the whole point of the gate is that
    we must not guess. Override with ORCH_HOT_RELOAD_REQUIRE_IDLE=0.
    """
    if os.environ.get("ORCH_HOT_RELOAD_REQUIRE_IDLE", "1").strip().lower() not in ("1", "true", "yes", "on"):
        return True
    return _active_count(active_slugs) == 0


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
    """Reload changed modules + env — but ONLY at a clean boundary with no in-flight tasks.

    DRAIN-THEN-SWAP (root cause #5). This function used to `importlib.reload()` any changed
    module every 5 seconds while worker threads were mid-task. `active_slugs` was accepted and
    then never used, and `_SKIP` was a static three-name set, so the docstring's promise that it
    "never reloads the module that's mid-execution" was not actually implemented. A task running
    against half-old/half-new module objects destroyed in-flight work three times in one session,
    and the fleet then reconciled the wreckage with bulk UPDATEs.

    Now: env re-reads stay live (values are read at call time, so that is safe), but CODE swaps
    are deferred until the runner reports zero in-flight tasks. Changes are not lost — they are
    remembered and applied at the next clean boundary.

    Pass `active_slugs` (the runner's in-flight set/list) to enable the drain. Callers that pass
    nothing are treated as "unknown in-flight state" and, with ORCH_HOT_RELOAD_REQUIRE_IDLE on
    (the default), are refused — fail safe rather than swapping under a running task.
    Set ORCH_HOT_RELOAD_REQUIRE_IDLE=0 to restore the old always-swap behaviour.
    """
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
    # DRAIN GATE: never swap code under a running task.
    cur = _scan()
    pending = [n for n, mt in cur.items()
               if n not in _SKIP and mt > _mtimes.get(n, 0)]
    if pending and not _idle_enough(active_slugs):
        global _deferred_log_t
        if time.time() - _deferred_log_t > 60:
            _deferred_log_t = time.time()
            print(f"[hot-reload] DEFERRED code swap of {len(pending)} module(s) "
                  f"({', '.join(sorted(pending)[:6])}{'...' if len(pending) > 6 else ''}) — "
                  f"{_active_count(active_slugs)} task(s) in flight. Will apply at the next "
                  f"clean boundary (drain-then-swap). ORCH_HOT_RELOAD_REQUIRE_IDLE=0 to override.")
        return reloaded    # mtimes deliberately NOT advanced, so the swap happens once idle

    # changed modules -> importlib.reload the already-imported ones
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
