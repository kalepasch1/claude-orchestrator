#!/usr/bin/env python3
"""worktree_preflight.py - per-project, once-per-day hermetic worktree preflight.

Before 2026-08-06 every task claimed against a JavaScript project paid for its own
discovery that the toolchain was unusable: a fresh worktree was created, a model run
was spent, and the build died on `npm: command not found` or a half-installed
node_modules. The failure was per-task, so N queued tasks burned N model runs to
learn one repo-level fact.

This module makes that fact repo-level and cheap:

  1. once per project per day, verify `node` and `npm` are on PATH;
  2. run the install into the shared per-project snapshot cache (delegated to
     ``dependency_prewarm.ensure_all``, which already owns manifest-keyed locking,
     content-addressed snapshots and readiness validation - this module deliberately
     does not reimplement any of it);
  3. hand new worktrees the warmed node_modules via
     ``dependency_prewarm.link_shared_runtime`` instead of installing per worktree;
  4. if the preflight is RED, mark the project blocked *with a reason* so the claimer
     skips it, rather than letting every task rediscover the same breakage.

Everything here is fail-soft. A bug in the preflight itself must never be able to
block a project: unexpected exceptions degrade to "green (unverified)". Only a
positively-observed RED result blocks.
"""
import json
import os
import shutil
import time

_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR)

#: Reason code used for the project-scoped pause, so pause_arbiter can attribute
#: (and only ever auto-lift) pauses this module owns.
REASON_CODE = "worktree_preflight_red"

STATUS_GREEN = "green"
STATUS_BLOCKED = "blocked"
STATUS_SKIPPED = "skipped"


def _truthy(name, default=True):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).lower() in ("1", "true", "yes", "on")


def _state_dir():
    return os.environ.get(
        "ORCH_WORKTREE_PREFLIGHT_DIR",
        os.path.join(_ROOT, ".runtime", "worktree_preflight"),
    )


def _safe_name(project):
    keep = "-_."
    return "".join(c if (c.isalnum() or c in keep) else "_" for c in str(project or "unknown"))


def _stamp_path(project):
    return os.path.join(_state_dir(), _safe_name(project) + ".json")


def _today():
    """Local calendar day. Overridable so tests can drive the cache boundary."""
    override = os.environ.get("ORCH_WORKTREE_PREFLIGHT_TODAY")
    if override:
        return override
    return time.strftime("%Y-%m-%d")


def _read_stamp(project):
    try:
        with open(_stamp_path(project), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _write_stamp(project, record):
    try:
        os.makedirs(_state_dir(), exist_ok=True)
        with open(_stamp_path(project), "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, sort_keys=True)
    except Exception:
        pass  # fail-soft: losing the stamp costs a re-run, never correctness


def _package_roots(repo_path):
    try:
        import dependency_prewarm
        return dependency_prewarm.package_roots(repo_path)
    except Exception:
        # Without the prewarm module we can still answer the only question that
        # matters here: does this repo look like a JS project at all?
        if repo_path and os.path.isfile(os.path.join(repo_path, "package.json")):
            return [repo_path]
        return []


def missing_tools():
    """Return the required JS toolchain binaries that are not on PATH."""
    return [t for t in ("node", "npm") if not shutil.which(t)]


def _block_project(project, reason):
    """Mark the project paused with an attributable reason. Best-effort."""
    try:
        import pause_arbiter
        pause_arbiter.pause(
            REASON_CODE,
            f"worktree preflight RED: {reason}",
            by="worktree_preflight",
            scope="project",
            project=project,
        )
        return True
    except Exception:
        return False


def _unblock_project(project):
    """Lift only a pause this module owns; never touch another caller's pause."""
    try:
        import pause_arbiter
        key = f"project:{project or ''}"
        state = pause_arbiter._load_state() or {}
        entry = state.get(key) or {}
        if entry.get("reason_code") != REASON_CODE:
            return False
        if entry.get("escalated"):
            # Escalated to a human by pause_arbiter; respect that and stay out of it.
            return False
        pause_arbiter.resume(scope="project", project=project, by="worktree_preflight")
        return True
    except Exception:
        return False


def _result(project, status, reason=None, cached=False, **extra):
    out = {
        "project": project,
        "status": status,
        "reason": reason,
        "cached": bool(cached),
        "blocked": status == STATUS_BLOCKED,
        "claimable": status != STATUS_BLOCKED,
        "date": _today(),
    }
    out.update(extra)
    return out


def preflight(project, repo_path, force=False, timeout=None):
    """Run (or replay today's cached) preflight for one project.

    Returns a dict with ``status`` in {green, blocked, skipped}. ``blocked`` results
    always carry a human-readable ``reason``; callers must not claim tasks for a
    project whose result has ``claimable`` False.
    """
    if not _truthy("ORCH_WORKTREE_PREFLIGHT", True):
        return _result(project, STATUS_SKIPPED, "disabled")

    try:
        if not repo_path or not os.path.isdir(repo_path):
            # A missing checkout is not this module's problem to diagnose, and
            # blocking on it would hide the real repo-setup error from the executor.
            return _result(project, STATUS_SKIPPED, "missing-repo")

        cached = _read_stamp(project)
        if not force and cached and cached.get("date") == _today():
            return _result(
                project,
                cached.get("status") or STATUS_GREEN,
                cached.get("reason"),
                cached=True,
                checked_at=cached.get("checked_at"),
            )

        roots = _package_roots(repo_path)
        if not roots:
            res = _result(project, STATUS_SKIPPED, "no-package-json")
            _write_stamp(project, {"date": _today(), "status": STATUS_SKIPPED,
                                   "reason": "no-package-json", "checked_at": time.time()})
            _unblock_project(project)
            return res

        missing = missing_tools()
        if missing:
            reason = (f"{', '.join(missing)} not found on PATH; "
                      f"cannot install dependencies for {len(roots)} package root(s)")
            _write_stamp(project, {"date": _today(), "status": STATUS_BLOCKED,
                                   "reason": reason, "checked_at": time.time()})
            _block_project(project, reason)
            return _result(project, STATUS_BLOCKED, reason, missing_tools=missing)

        install = _install(repo_path, timeout=timeout)
        if not install.get("ok"):
            reason = f"dependency install failed: {install.get('error') or 'unknown error'}"
            _write_stamp(project, {"date": _today(), "status": STATUS_BLOCKED,
                                   "reason": reason, "checked_at": time.time()})
            _block_project(project, reason)
            return _result(project, STATUS_BLOCKED, reason, install=install)

        _write_stamp(project, {"date": _today(), "status": STATUS_GREEN,
                               "reason": None, "checked_at": time.time()})
        _unblock_project(project)
        return _result(project, STATUS_GREEN, None, roots=len(roots), install=install)
    except Exception as e:
        # Fail-soft: a defect in the preflight must not be able to stall a project.
        return _result(project, STATUS_GREEN, f"preflight-error (not blocking): {e}",
                       unverified=True)


def _install(repo_path, timeout=None):
    try:
        import dependency_prewarm
    except Exception as e:
        return {"ok": True, "skipped": f"dependency_prewarm unavailable: {e}"}
    try:
        return dependency_prewarm.ensure_all(
            repo_path, reason="worktree_preflight", timeout=timeout) or {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def claimable(project, repo_path=None, force=False):
    """True when tasks for this project may be claimed.

    Uses today's cached verdict when present so the claim path stays cheap; only
    runs a real preflight when ``repo_path`` is supplied and no verdict exists yet.
    """
    cached = _read_stamp(project)
    if cached and cached.get("date") == _today() and not force:
        return cached.get("status") != STATUS_BLOCKED
    if not repo_path:
        return True  # unknown is not blocked - never invent a stall
    return preflight(project, repo_path, force=force).get("claimable", True)


def blocked_reason(project):
    """The recorded reason this project is blocked today, or None."""
    cached = _read_stamp(project)
    if cached and cached.get("date") == _today() and cached.get("status") == STATUS_BLOCKED:
        return cached.get("reason")
    return None


def prepare_worktree(repo_path, worktree):
    """Give a freshly created worktree the warmed dependencies.

    Thin delegation to dependency_prewarm.link_shared_runtime so worktrees share one
    install instead of each running their own `npm ci`.
    """
    try:
        import dependency_prewarm
        return dependency_prewarm.link_shared_runtime(repo_path, worktree) or []
    except Exception:
        return []
