#!/usr/bin/env python3
"""
backlog_recovery.py — automated assessment and triage of stale legacy branches.

Consolidates the repeated pattern of 17+ legacy merge tasks into a single
automated pipeline. Instead of manually merging each branch, this module:

1. Scans all candidate branches for divergence from master
2. Classifies branches as: mergeable, conflicting, obsolete, or already-merged
3. Produces a prioritized recovery plan
4. Optionally executes safe merges for branches with zero conflicts

Env vars:
    ORCH_BACKLOG_MAX_DIVERGENCE   max commits behind master before marking obsolete (default 500)
    ORCH_BACKLOG_DRY_RUN          "true" to only report, never merge (default "true")
"""
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod

_log = _log_mod.get("backlog_recovery")

MAX_DIVERGENCE = int(os.environ.get("ORCH_BACKLOG_MAX_DIVERGENCE", "500"))
DRY_RUN = os.environ.get("ORCH_BACKLOG_DRY_RUN", "true").lower() in ("1", "true", "yes")


@dataclass
class BranchAssessment:
    """Assessment of a single legacy branch."""
    branch: str
    slug: str
    status: str  # "mergeable", "conflicting", "obsolete", "already_merged", "error"
    commits_ahead: int = 0
    commits_behind: int = 0
    files_changed: int = 0
    insertions: int = 0
    deletions: int = 0
    has_conflicts: bool = False
    reason: str = ""
    priority: int = 0  # higher = more important to merge


@dataclass
class RecoveryPlan:
    """Prioritized recovery plan for a batch of legacy branches."""
    timestamp: float = field(default_factory=time.time)
    assessments: List[BranchAssessment] = field(default_factory=list)
    total_branches: int = 0
    mergeable_count: int = 0
    obsolete_count: int = 0
    conflicting_count: int = 0
    already_merged_count: int = 0

    def summary(self) -> Dict:
        return {
            "total": self.total_branches,
            "mergeable": self.mergeable_count,
            "obsolete": self.obsolete_count,
            "conflicting": self.conflicting_count,
            "already_merged": self.already_merged_count,
        }


def _git(repo_path: str, *args, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a git command and return the result."""
    return subprocess.run(
        ["git"] + list(args),
        cwd=repo_path, capture_output=True, text=True, timeout=timeout,
    )


def assess_branch(repo_path: str, branch: str, base: str = "origin/master") -> BranchAssessment:
    """Assess a single branch's merge status against base."""
    slug = branch.replace("origin/agent/", "").replace("agent/", "")
    assessment = BranchAssessment(branch=branch, slug=slug, status="error")

    try:
        # Check commits ahead/behind
        r = _git(repo_path, "rev-list", "--left-right", "--count", f"{base}...{branch}")
        if r.returncode != 0:
            assessment.reason = f"rev-list failed: {r.stderr.strip()}"
            return assessment

        parts = r.stdout.strip().split()
        if len(parts) == 2:
            assessment.commits_behind = int(parts[0])
            assessment.commits_ahead = int(parts[1])

        # Already merged (0 commits ahead)
        if assessment.commits_ahead == 0:
            assessment.status = "already_merged"
            assessment.reason = "all commits already in base"
            return assessment

        # Too divergent → obsolete
        if assessment.commits_behind > MAX_DIVERGENCE:
            assessment.status = "obsolete"
            assessment.reason = f"too divergent ({assessment.commits_behind} commits behind)"
            return assessment

        # Check diff stats
        r = _git(repo_path, "diff", "--shortstat", f"{base}...{branch}")
        if r.returncode == 0 and r.stdout.strip():
            stat_line = r.stdout.strip()
            # Parse "X files changed, Y insertions(+), Z deletions(-)"
            for part in stat_line.split(","):
                part = part.strip()
                if "file" in part:
                    assessment.files_changed = int(part.split()[0])
                elif "insertion" in part:
                    assessment.insertions = int(part.split()[0])
                elif "deletion" in part:
                    assessment.deletions = int(part.split()[0])

        # Check for merge conflicts (dry-run merge)
        r = _git(repo_path, "merge-tree", base, branch)
        if r.returncode != 0:
            assessment.has_conflicts = True
            assessment.status = "conflicting"
            assessment.reason = "merge conflicts detected"
        else:
            assessment.status = "mergeable"
            assessment.reason = "clean merge possible"

        # Priority: more files changed = higher priority, but penalize huge diffs
        if assessment.files_changed > 100:
            assessment.priority = 1  # too large, low priority
        elif assessment.files_changed > 0:
            assessment.priority = min(10, assessment.files_changed)

    except Exception as e:
        assessment.reason = str(e)

    return assessment


def build_recovery_plan(repo_path: str, branches: List[str],
                        base: str = "origin/master") -> RecoveryPlan:
    """Build a prioritized recovery plan for a list of branches."""
    plan = RecoveryPlan(total_branches=len(branches))

    for branch in branches:
        assessment = assess_branch(repo_path, branch, base)
        plan.assessments.append(assessment)

        if assessment.status == "mergeable":
            plan.mergeable_count += 1
        elif assessment.status == "obsolete":
            plan.obsolete_count += 1
        elif assessment.status == "conflicting":
            plan.conflicting_count += 1
        elif assessment.status == "already_merged":
            plan.already_merged_count += 1

    # Sort by priority descending
    plan.assessments.sort(key=lambda a: a.priority, reverse=True)
    return plan


def scan_legacy_branches(repo_path: str, pattern: str = "origin/agent/rework-secret*",
                         base: str = "origin/master") -> RecoveryPlan:
    """Scan all branches matching pattern and build a recovery plan."""
    try:
        r = _git(repo_path, "branch", "-r", "--list", pattern)
        if r.returncode != 0:
            return RecoveryPlan()
        branches = [b.strip() for b in r.stdout.splitlines() if b.strip()]
    except Exception:
        return RecoveryPlan()

    return build_recovery_plan(repo_path, branches, base)


def format_plan(plan: RecoveryPlan) -> str:
    """Format a recovery plan as a human-readable report."""
    lines = [
        f"Backlog Recovery Plan — {time.strftime('%Y-%m-%d %H:%M', time.localtime(plan.timestamp))}",
        f"Total branches: {plan.total_branches}",
        f"  Mergeable: {plan.mergeable_count}",
        f"  Conflicting: {plan.conflicting_count}",
        f"  Obsolete: {plan.obsolete_count}",
        f"  Already merged: {plan.already_merged_count}",
        "",
    ]
    for a in plan.assessments:
        lines.append(f"  [{a.status.upper():15s}] {a.slug}")
        lines.append(f"    ahead={a.commits_ahead} behind={a.commits_behind} "
                      f"files={a.files_changed} +{a.insertions}/-{a.deletions}")
        lines.append(f"    reason: {a.reason}")
    return "\n".join(lines)
