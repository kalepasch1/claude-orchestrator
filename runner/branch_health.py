#!/usr/bin/env python3
"""
branch_health.py — branch health scoring for the orchestrator.

Computes a health score (0.0–1.0) for agent branches based on:
  - staleness (days since last commit)
  - merge-readiness (ahead/behind counts relative to base)
  - naming validity

Used by branch_lifecycle and the merge train to prioritise cleanup
and surface unhealthy branches before they block the pipeline.

Env vars:
    ORCH_BRANCH_HEALTH_STALE_PENALTY   weight for staleness (default 0.4)
    ORCH_BRANCH_HEALTH_DRIFT_PENALTY   weight for drift from base (default 0.3)
"""
import os
import subprocess
import time

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

STALE_PENALTY = float(os.environ.get("ORCH_BRANCH_HEALTH_STALE_PENALTY", "0.4"))
DRIFT_PENALTY = float(os.environ.get("ORCH_BRANCH_HEALTH_DRIFT_PENALTY", "0.3"))
_STALE_THRESHOLD_DAYS = 7
_DRIFT_THRESHOLD_COMMITS = 50


def _git(repo, *args):
    """Run a git command, return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(
            ["git"] + list(args), cwd=repo,
            capture_output=True, text=True, timeout=30,
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return -1, "", str(e)


def branch_age_days(repo_path, branch):
    """Return the age in days of the last commit on *branch*, or None."""
    if not repo_path or not branch:
        return None
    rc, out, _ = _git(repo_path, "log", "-1", "--format=%ct", branch)
    if rc != 0 or not out:
        return None
    try:
        return (time.time() - int(out)) / 86400
    except (ValueError, TypeError):
        return None


def branch_drift(repo_path, branch, base="master"):
    """Return (ahead, behind) commit counts relative to *base*, or None on error."""
    if not repo_path or not branch:
        return None
    rc, out, _ = _git(repo_path, "rev-list", "--left-right", "--count",
                      f"{base}...{branch}")
    if rc != 0 or not out:
        return None
    parts = out.split()
    if len(parts) != 2:
        return None
    try:
        return int(parts[1]), int(parts[0])  # (ahead, behind)
    except (ValueError, TypeError):
        return None


def health_score(repo_path, branch, base="master"):
    """Compute a health score (0.0–1.0) for *branch*.

    Score components:
      - Staleness: branches older than _STALE_THRESHOLD_DAYS lose up to STALE_PENALTY
      - Drift: branches far from base lose up to DRIFT_PENALTY
      - Naming: invalid branch names get a flat 0.3 deduction

    Returns a dict with 'score', 'components', and 'branch'.
    Fail-soft: returns score 0.5 with reason on any error.
    """
    from branch_lifecycle import validate_branch_name

    result = {"branch": branch, "score": 1.0, "components": {}}

    # Naming check
    valid, reason = validate_branch_name(branch)
    if not valid:
        result["components"]["naming"] = {"penalty": 0.3, "reason": reason}
        result["score"] -= 0.3

    # Staleness check
    age = branch_age_days(repo_path, branch)
    if age is not None:
        if age > _STALE_THRESHOLD_DAYS:
            staleness_ratio = min(age / (_STALE_THRESHOLD_DAYS * 4), 1.0)
            penalty = STALE_PENALTY * staleness_ratio
            result["components"]["staleness"] = {
                "age_days": round(age, 1), "penalty": round(penalty, 3),
            }
            result["score"] -= penalty
    else:
        result["components"]["staleness"] = {"age_days": None, "penalty": 0}

    # Drift check
    drift = branch_drift(repo_path, branch, base)
    if drift is not None:
        ahead, behind = drift
        if behind > _DRIFT_THRESHOLD_COMMITS:
            drift_ratio = min(behind / (_DRIFT_THRESHOLD_COMMITS * 4), 1.0)
            penalty = DRIFT_PENALTY * drift_ratio
            result["components"]["drift"] = {
                "ahead": ahead, "behind": behind, "penalty": round(penalty, 3),
            }
            result["score"] -= penalty
        else:
            result["components"]["drift"] = {
                "ahead": ahead, "behind": behind, "penalty": 0,
            }
    else:
        result["components"]["drift"] = {"ahead": None, "behind": None, "penalty": 0}

    result["score"] = round(max(0.0, result["score"]), 3)
    return result


def bulk_health(repo_path, branches, base="master"):
    """Compute health scores for multiple branches, sorted worst-first."""
    results = []
    for branch in branches:
        try:
            results.append(health_score(repo_path, branch, base))
        except Exception:
            results.append({"branch": branch, "score": 0.5,
                            "components": {"error": "exception during scoring"}})
    results.sort(key=lambda r: r["score"])
    return results
