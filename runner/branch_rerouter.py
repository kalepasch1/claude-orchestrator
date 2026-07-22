#!/usr/bin/env python3
"""
branch_rerouter.py - reroutes broken branch references to canonical branches.

When the fleet executes parallel improvements via worktrees, branch references can
desync across machines (e.g., agent/slug branch missing on some runners, or references
pointing to stale commits). This module detects and reroutes broken references to the
canonical branch/commit.

Module-level singleton pattern: provides module-level functions that delegate to
thread-safe internal state. Fail-soft error handling: returns input unchanged on any
error (missing git state, permission errors, etc.); never raises.

Config keys (ORCH_BRANCH_REROUTE_*):
  ORCH_BRANCH_REROUTE_<BRANCH>=<canonical>   — if <BRANCH> is missing/stale, use <canonical>
  ORCH_BRANCH_REROUTE_FALLBACK=<default>    — catch-all for unmapped missing branches
"""
import os
import sys
import subprocess
import threading
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import events

log = logging.getLogger(__name__)

_lock = threading.Lock()
_stats = {"rerouted": 0, "stale_detected": 0, "errors": 0}
_config = {}
_repo = None


def _get_enabled():
    """Return True if branch rerouting is enabled (default: false)."""
    return os.environ.get("ORCH_BRANCH_REROUTE_ENABLED", "false").lower() in ("true", "1", "yes")


def _get_strategy():
    """Return the rerouting strategy (default: 'default')."""
    return os.environ.get("ORCH_BRANCH_REROUTE_STRATEGY", "default")


def _get_timeout_sec():
    """Return the git command timeout in seconds (default: 30)."""
    try:
        return int(os.environ.get("ORCH_BRANCH_REROUTE_TIMEOUT_SEC", "30"))
    except (ValueError, TypeError):
        return 30


def _git(repo, *args, timeout=None):
    """Run a git command in the given repo. Returns CompletedProcess or None on error."""
    if not repo:
        return None
    if timeout is None:
        timeout = _get_timeout_sec()
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception:
        return None


def _branch_exists(repo, branch):
    """Return True if branch exists locally or on origin."""
    if not repo or not branch:
        return False
    r = _git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}")
    if r and r.returncode == 0:
        return True
    r = _git(repo, "show-ref", "--verify", "--quiet", f"refs/remotes/origin/{branch}")
    if r and r.returncode == 0:
        return True
    return False


def _get_commit(repo, branch):
    """Return the commit SHA for a branch, or None if not found."""
    if not repo or not branch:
        return None
    r = _git(repo, "rev-parse", "--verify", "--quiet", branch)
    if r and r.returncode == 0:
        return r.stdout.strip()
    return None


def _is_stale(repo, branch, canonical_branch):
    """Return True if branch's commit is not in canonical_branch's history."""
    if not repo or not branch or not canonical_branch:
        return False
    commit = _get_commit(repo, branch)
    if not commit:
        return True
    r = _git(repo, "merge-base", "--is-ancestor", commit, canonical_branch)
    if r is None:
        return True
    return r.returncode != 0


def _load_repo():
    """Detect the current repo. Cached after first call."""
    global _repo
    if _repo is not None:
        return _repo
    cwd = os.getcwd()
    if os.path.isdir(os.path.join(cwd, ".git")):
        _repo = cwd
        return _repo
    parent = os.path.dirname(cwd)
    if os.path.isdir(os.path.join(parent, ".git")):
        _repo = parent
        return _repo
    return None


def _get_reroute_config():
    """Return a dict of all ORCH_BRANCH_REROUTE_* config keys (from env and in-memory config)."""
    mappings = {}
    special_keys = {
        "ORCH_BRANCH_REROUTE_FALLBACK",
        "ORCH_BRANCH_REROUTE_ENABLED",
        "ORCH_BRANCH_REROUTE_STRATEGY",
        "ORCH_BRANCH_REROUTE_TIMEOUT_SEC",
    }
    try:
        with _lock:
            for k, v in _config.items():
                if k.startswith("ORCH_BRANCH_REROUTE_") and k not in special_keys:
                    branch = k[len("ORCH_BRANCH_REROUTE_"):]
                    if branch and v:
                        mappings[branch] = str(v)
        for k, v in os.environ.items():
            if k.startswith("ORCH_BRANCH_REROUTE_") and k not in special_keys:
                branch = k[len("ORCH_BRANCH_REROUTE_"):]
                if branch and v:
                    mappings[branch] = str(v)
    except Exception:
        pass
    return mappings


def _get_fallback():
    """Return the fallback canonical branch (default: main)."""
    return os.environ.get("ORCH_BRANCH_REROUTE_FALLBACK", "main")


def reroute(branch_name):
    """
    Reroute a branch name to its canonical version if missing or stale.

    Args:
        branch_name (str): The branch to check (e.g., "agent/my-task")

    Returns:
        str: The canonical branch name if input is missing/stale, unchanged otherwise.
             On any error, returns input unchanged (fail-soft).

    Side effects:
        - Logs rerouting decisions
        - Updates _stats for observability
        - Emits events on successful reroute
    """
    if not isinstance(branch_name, str):
        return ""
    if not branch_name:
        return ""

    if not _get_enabled():
        return branch_name

    repo = _load_repo()
    if not repo:
        return branch_name

    try:
        with _lock:
            mappings = _get_reroute_config()
            fallback = _get_fallback()

            canonical = mappings.get(branch_name)
            if canonical:
                if not _branch_exists(repo, branch_name):
                    _stats["rerouted"] += 1
                    log.info(f"reroute: {branch_name} -> {canonical} (missing, explicit mapping)")
                    try:
                        events.emit("branch_reroute", branch=branch_name, canonical=canonical, reason="missing_explicit_map")
                    except Exception:
                        pass
                    return canonical
                if _is_stale(repo, branch_name, canonical):
                    _stats["stale_detected"] += 1
                    log.info(f"reroute: {branch_name} -> {canonical} (stale, explicit mapping)")
                    try:
                        events.emit("branch_reroute", branch=branch_name, canonical=canonical, reason="stale_explicit_map")
                    except Exception:
                        pass
                    return canonical
                return branch_name

            if not _branch_exists(repo, branch_name):
                _stats["rerouted"] += 1
                log.info(f"reroute: {branch_name} -> {fallback} (missing, using fallback)")
                try:
                    events.emit("branch_reroute", branch=branch_name, canonical=fallback, reason="missing_fallback")
                except Exception:
                    pass
                return fallback

            for check_against in [fallback, "master", "dev"]:
                if check_against != branch_name and _branch_exists(repo, check_against):
                    if _is_stale(repo, branch_name, check_against):
                        _stats["stale_detected"] += 1
                        log.info(f"reroute: {branch_name} -> {fallback} (stale vs {check_against})")
                        try:
                            events.emit("branch_reroute", branch=branch_name, canonical=fallback, reason="stale_fallback")
                        except Exception:
                            pass
                        return fallback
                    break

            return branch_name
    except Exception as e:
        with _lock:
            _stats["errors"] += 1
        log.error(f"reroute: error processing {branch_name}: {e}")
        return branch_name


def set_branch_config(key, value):
    """
    Store a branch rerouting config key in memory (thread-safe).

    Args:
        key (str): Config key (must start with ORCH_BRANCH_REROUTE_)
        value (str): Config value

    Returns:
        bool: True if set successfully, False if key is invalid (fail-soft)
    """
    if not isinstance(key, str) or not key.startswith("ORCH_BRANCH_REROUTE_"):
        return False
    try:
        with _lock:
            _config[key] = str(value) if value is not None else ""
        return True
    except Exception:
        return False


def get_branch_config(key):
    """
    Retrieve a branch rerouting config key from memory (thread-safe).

    Args:
        key (str): Config key (must start with ORCH_BRANCH_REROUTE_)

    Returns:
        str: Config value, or empty string if not found or invalid key (fail-soft)
    """
    if not isinstance(key, str) or not key.startswith("ORCH_BRANCH_REROUTE_"):
        return ""
    try:
        with _lock:
            return _config.get(key, "")
    except Exception:
        return ""


def stats():
    """Return observability stats: rerouted count, stale detections, errors."""
    with _lock:
        return dict(_stats)


def reset_stats():
    """Reset stats counters (useful for testing)."""
    with _lock:
        global _stats
        _stats = {"rerouted": 0, "stale_detected": 0, "errors": 0}


def invalidate_repo():
    """Clear cached repo path (useful for testing or repo changes)."""
    global _repo
    _repo = None


def invalidate():
    """Clear cached repo path and in-memory config (useful for testing or state reset)."""
    global _repo
    _repo = None
    with _lock:
        global _config
        _config.clear()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        result = reroute(sys.argv[1])
        print(f"reroute({sys.argv[1]}) -> {result}")
        print(f"stats: {stats()}")
    else:
        print("Usage: branch_rerouter.py <branch_name>")
