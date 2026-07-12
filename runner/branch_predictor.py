#!/usr/bin/env python3
"""
branch_predictor.py - predict and prevent missing branches proactively.

Slice-3: builds on missing_branch_audit.py to add forward-looking prediction:
  - Learns which task patterns historically lose their branches
    (e.g., long-running tasks, tasks on busy repos, specific kinds)
  - Flags at-risk tasks BEFORE they complete, so branches can be preserved
  - Auto-creates backup refs for high-risk branches
  - Periodic audit with auto-remediation: re-create branches from commits

Uses the outcomes table and task history to build a risk model.
"""
import collections, json, os, subprocess, sys, time, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import log as _log_mod
_log = _log_mod.get("branch_predictor")

RISK_THRESHOLD = float(os.environ.get("ORCH_BRANCH_RISK_THRESHOLD", "0.4"))
BACKUP_REF_PREFIX = os.environ.get("ORCH_BRANCH_BACKUP_PREFIX", "refs/backup/agent/")
ENABLED = os.environ.get("ORCH_BRANCH_PREDICTOR", "true").lower() in ("true", "1")

_lock = threading.Lock()
_risk_factors = {}  # kind -> miss_rate
_stats = {"predictions": 0, "backups_created": 0, "branches_recovered": 0}


def _learn_risk_factors():
    """Learn which task kinds/patterns historically lose branches."""
    try:
        done = db.select("tasks", {
            "select": "id,slug,kind,state,note,updated_at",
            "state": "eq.DONE",
            "order": "updated_at.desc",
            "limit": "300",
        }) or []
    except Exception:
        return

    kind_totals = collections.Counter()
    kind_missing = collections.Counter()

    for t in done:
        kind = t.get("kind", "build")
        kind_totals[kind] += 1
        note = (t.get("note") or "").lower()
        if "missing" in note or "branch not found" in note or "no branch" in note:
            kind_missing[kind] += 1

    with _lock:
        _risk_factors.clear()
        for kind, total in kind_totals.items():
            if total >= 3:
                _risk_factors[kind] = kind_missing.get(kind, 0) / total


def predict_risk(task):
    """Predict the likelihood that a task's branch will be lost.

    Args:
        task: dict with at least "kind", "slug" fields

    Returns:
        {"risk": float, "factors": list[str], "action": "backup"|"monitor"|"safe"}
    """
    if not ENABLED or not task:
        return {"risk": 0, "factors": [], "action": "safe"}

    kind = task.get("kind", "build")
    factors = []
    risk = 0.0

    # Factor 1: historical miss rate for this kind
    with _lock:
        kind_risk = _risk_factors.get(kind, 0)
    if kind_risk > 0.1:
        risk += kind_risk * 0.5
        factors.append(f"kind '{kind}' has {kind_risk:.0%} historical miss rate")

    # Factor 2: long slug names (proxy for complex/multi-slice tasks)
    slug = task.get("slug", "")
    if len(slug) > 60:
        risk += 0.1
        factors.append("long slug (complex task)")

    # Factor 3: high attempt count (task has been retried)
    attempt = task.get("attempt", 0) or 0
    if attempt > 1:
        risk += 0.15 * min(attempt, 3)
        factors.append(f"attempt #{attempt}")

    risk = min(1.0, risk)
    _stats["predictions"] += 1

    if risk >= RISK_THRESHOLD:
        action = "backup"
    elif risk >= RISK_THRESHOLD * 0.5:
        action = "monitor"
    else:
        action = "safe"

    return {"risk": round(risk, 3), "factors": factors, "action": action}


def create_backup_ref(repo_path, slug):
    """Create a backup ref for a task's branch to prevent loss."""
    if not repo_path or not os.path.isdir(repo_path):
        return False
    branch = f"agent/{slug}"
    backup = f"{BACKUP_REF_PREFIX}{slug}"
    try:
        r = subprocess.run(
            ["git", "update-ref", backup, branch],
            cwd=repo_path, capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            _stats["backups_created"] += 1
            _log.info("branch_predictor: backed up %s -> %s", branch, backup)
            return True
    except Exception as e:
        _log.debug("branch_predictor: backup failed for %s: %s", slug, e)
    return False


def recover_branch(repo_path, slug):
    """Attempt to recover a missing branch from backup ref or reflog."""
    if not repo_path or not os.path.isdir(repo_path):
        return False

    branch = f"agent/{slug}"
    backup = f"{BACKUP_REF_PREFIX}{slug}"

    # Try backup ref first
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--verify", backup],
            cwd=repo_path, capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            commit = r.stdout.strip()
            subprocess.run(
                ["git", "branch", branch, commit],
                cwd=repo_path, capture_output=True, timeout=10)
            _stats["branches_recovered"] += 1
            _log.info("branch_predictor: recovered %s from backup", branch)
            return True
    except Exception:
        pass

    # Try reflog as fallback
    try:
        r = subprocess.run(
            ["git", "reflog", "show", branch, "--format=%H", "-n1"],
            cwd=repo_path, capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            commit = r.stdout.strip()
            subprocess.run(
                ["git", "branch", branch, commit],
                cwd=repo_path, capture_output=True, timeout=10)
            _stats["branches_recovered"] += 1
            _log.info("branch_predictor: recovered %s from reflog", branch)
            return True
    except Exception:
        pass

    return False


def run():
    """Periodic: refresh risk model, scan at-risk tasks, backup as needed."""
    _learn_risk_factors()

    # Find RUNNING tasks and assess risk
    try:
        running = db.select("tasks", {
            "select": "id,slug,kind,attempt,project_id",
            "state": "eq.RUNNING",
            "limit": "50",
        }) or []
    except Exception:
        running = []

    backed_up = 0
    for t in running:
        prediction = predict_risk(t)
        if prediction["action"] == "backup":
            # Get repo path
            try:
                projs = db.select("projects", {
                    "select": "repo_path",
                    "id": f"eq.{t.get('project_id', '')}",
                    "limit": "1",
                }) or []
                if projs:
                    repo = db.localize_repo_path(projs[0].get("repo_path", ""))
                    if create_backup_ref(repo, t.get("slug", "")):
                        backed_up += 1
            except Exception:
                pass

    return {"risk_factors": dict(_risk_factors), "backed_up": backed_up, "stats": dict(_stats)}


def stats():
    """Return predictor statistics."""
    return dict(_stats)


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
