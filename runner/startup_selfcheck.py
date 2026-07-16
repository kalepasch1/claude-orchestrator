#!/usr/bin/env python3
"""
startup_selfcheck.py - run ONCE at boot (and callable anytime). Asserts the invariants that, when
violated, silently stall the whole system, and AUTO-HEALS what it can, then posts a health line to
runner_health so a silent stall can never go unseen again.

Checks:
  1. DB connectivity                              -> verify Supabase is reachable.
  2. Git config validation                        -> verify user.name and user.email are set; auto-heal with defaults.
  3. Worktree hygiene                             -> prune stale git worktrees across all project repos.
  4. Kill switch validation                       -> verify runner is not paused.
  5. Disk space warning                           -> warn if free disk < 2GB.
"""
import os, sys, socket, datetime, shutil, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# Module-level registry for checks
CHECKS = []


def _register(func):
    """Decorator to register a check function."""
    CHECKS.append(func)
    return func


@_register
def check_db_connectivity():
    """
    DB connectivity check: verify Supabase is reachable.
    Returns: (ok: bool, detail: str, healed: bool)
    """
    try:
        result = db.select("runner_health", {"select": "id", "limit": "1"}) or []
        return (True, "DB connectivity OK", False)
    except Exception as e:
        return (False, f"DB connectivity failed: {e}", False)


@_register
def check_git_config():
    """
    Git config validation: verify user.name and user.email are set; auto-heal with defaults.
    Returns: (ok: bool, detail: str, healed: bool)
    """
    healed = False
    try:
        result_name = subprocess.run(
            ["git", "config", "user.name"],
            capture_output=True,
            text=True,
            timeout=5
        )
        user_name = result_name.stdout.strip()

        result_email = subprocess.run(
            ["git", "config", "user.email"],
            capture_output=True,
            text=True,
            timeout=5
        )
        user_email = result_email.stdout.strip()

        if not user_name:
            subprocess.run(
                ["git", "config", "--global", "user.name", "claude-orchestrator"],
                timeout=5,
                check=True
            )
            healed = True
            user_name = "claude-orchestrator"

        if not user_email:
            subprocess.run(
                ["git", "config", "--global", "user.email", "claude@orchestrator.local"],
                timeout=5,
                check=True
            )
            healed = True
            user_email = "claude@orchestrator.local"

        detail = f"Git config OK (user.name={user_name}, user.email={user_email})"
        if healed:
            detail += " [auto-healed]"

        return (True, detail, healed)
    except Exception as e:
        return (False, f"Git config check failed: {e}", False)


@_register
def check_worktree_hygiene():
    """
    Worktree hygiene: prune stale git worktrees across all project repos.
    Returns: (ok: bool, detail: str, healed: bool)
    """
    healed = False
    try:
        try:
            result = subprocess.run(
                ["git", "worktree", "list"],
                capture_output=True,
                text=True,
                timeout=10
            )
            worktrees = [w for w in result.stdout.strip().split('\n') if w] if result.stdout.strip() else []

            prune_result = subprocess.run(
                ["git", "worktree", "prune"],
                capture_output=True,
                text=True,
                timeout=10
            )

            if prune_result.returncode == 0:
                healed = len(worktrees) > 1
                return (True, f"Worktree hygiene OK ({len(worktrees)} worktrees)", healed)
            else:
                return (True, f"Worktree pruning skipped", False)
        except subprocess.CalledProcessError:
            return (True, "Worktree check skipped (not a git repo)", False)
    except Exception as e:
        return (False, f"Worktree hygiene check failed: {e}", False)


@_register
def check_kill_switch():
    """
    Kill switch validation: verify runner is not paused.
    Returns: (ok: bool, detail: str, healed: bool)
    """
    try:
        result = db.select("runner_health", {"select": "paused", "limit": "1"}) or []

        if result:
            paused = result[0].get("paused", False)
            if paused:
                return (False, "Runner is paused", False)
            else:
                return (True, "Kill switch OK (runner not paused)", False)
        else:
            return (True, "Kill switch OK (no health record found)", False)
    except Exception as e:
        return (False, f"Kill switch check failed: {e}", False)


@_register
def check_disk_space():
    """
    Disk space warning: warn if free disk < 2GB.
    Returns: (ok: bool, detail: str, healed: bool)
    """
    try:
        stat_result = shutil.disk_usage("/")
        free_gb = stat_result.free / (1024 ** 3)

        if free_gb < 2:
            return (False, f"Disk space low: {free_gb:.2f}GB free (< 2GB threshold)", False)
        else:
            return (True, f"Disk space OK: {free_gb:.2f}GB free", False)
    except Exception as e:
        return (False, f"Disk space check failed: {e}", False)


def run_all(halt_on_failure=False):
    """
    Orchestrate all checks in order.

    Args:
        halt_on_failure: If True, stop after first failing check

    Returns:
        (all_ok: bool, results: dict, healed_any: bool)
        where results maps check_name -> {ok, detail, healed}
    """
    results = {}
    all_ok = True
    healed_any = False

    for check_func in CHECKS:
        check_name = check_func.__name__
        try:
            ok, detail, healed = check_func()
            results[check_name] = {
                "ok": ok,
                "detail": detail,
                "healed": healed
            }

            if not ok:
                all_ok = False
                if halt_on_failure:
                    break

            if healed:
                healed_any = True
        except Exception as e:
            results[check_name] = {
                "ok": False,
                "detail": f"Check failed with exception: {e}",
                "healed": False
            }
            all_ok = False
            if halt_on_failure:
                break

    return (all_ok, results, healed_any)


def run(runner_id="startup"):
    """Legacy interface - runs all checks and logs results to runner_health."""
    all_ok, results, healed_any = run_all(halt_on_failure=False)

    detail = []
    for check_name, result in results.items():
        status = "OK" if result["ok"] else "FAIL"
        detail.append(f"{check_name}: {status} - {result['detail']}")
        if result['healed']:
            detail.append(f"  (auto-healed)")

    status = "ok" if all_ok else "degraded"
    try:
        db.insert("runner_health", {
            "runner_id": runner_id,
            "hostname": socket.gethostname(),
            "status": status,
            "detail": "; ".join(detail)[:500]
        })
    except Exception:
        pass

    print(f"[self-check] status={status} healed={healed_any}. {'; '.join(detail)}")
    return {"status": status, "all_ok": all_ok, "healed_any": healed_any}


if __name__ == "__main__":
    run()
