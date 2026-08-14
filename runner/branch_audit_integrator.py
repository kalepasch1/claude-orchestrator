#!/usr/bin/env python3
"""
branch_audit_integrator.py — consolidated branch management auditor + review gate.

Integrates branch lifecycle auditing with approval-merge policy to provide:
  1. Audit: scan all agent/* branches, classify as healthy/stale/orphan/conflicting
  2. Risk scoring: configurable risk criteria for auto-approval decisions
  3. Review gate: determine if a branch needs human review or can auto-merge
  4. Monitoring: real-time health summary for the branch fleet

This module consolidates several backlog intents:
  - improve-enhanced-branch-management-system-integrate-auditor
  - improve-automate-code-review-and-approval-process
  - improve-implement-real-time-monitoring-and-approval
  - improve-optimize-task-routing-algorithm (patch analysis)

Config (env vars or risk_config dict):
  ORCH_AUDIT_STALE_DAYS     days before branch is stale (default 7)
  ORCH_AUDIT_ORPHAN_ACTION  what to do with orphans: "flag"|"delete" (default "flag")
  ORCH_RISK_SENSITIVE_GLOB  comma-separated sensitive path globs
  ORCH_RISK_MAX_FILES       max changed files for auto-approve (default 20)
  ORCH_RISK_MAX_LINES       max changed lines for auto-approve (default 500)
"""
import os
import re
import subprocess
import fnmatch
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enums & dataclasses
# ---------------------------------------------------------------------------

class BranchHealth(Enum):
    HEALTHY = "healthy"
    STALE = "stale"
    ORPHAN = "orphan"
    CONFLICTING = "conflicting"
    MERGED = "merged"


class ReviewVerdict(Enum):
    AUTO_APPROVE = "auto_approve"
    HUMAN_REVIEW = "human_review"
    BLOCK = "block"


@dataclass
class RiskConfig:
    """Configurable risk criteria for auto-approval decisions."""
    stale_days: int = 7
    orphan_action: str = "flag"       # "flag" or "delete"
    max_files: int = 20               # more → human review
    max_lines: int = 500              # more → human review
    sensitive_globs: list = field(default_factory=lambda: [
        "*/pricing*", "*/price*", "*/cost*",
        "*/regulatory*", "*/compliance*", "*/legal*",
        "*/auth*", "*/login*", "*/password*", "*/token*",
        "*/rls*", "*/security*", "*/policy*", "*/permission*",
        "*/.env*", "*/secrets*",
    ])

    @classmethod
    def from_env(cls):
        cfg = cls()
        cfg.stale_days = int(os.environ.get("ORCH_AUDIT_STALE_DAYS", str(cfg.stale_days)))
        cfg.orphan_action = os.environ.get("ORCH_AUDIT_ORPHAN_ACTION", cfg.orphan_action)
        globs_env = os.environ.get("ORCH_RISK_SENSITIVE_GLOB", "")
        if globs_env:
            cfg.sensitive_globs = [g.strip() for g in globs_env.split(",") if g.strip()]
        cfg.max_files = int(os.environ.get("ORCH_RISK_MAX_FILES", str(cfg.max_files)))
        cfg.max_lines = int(os.environ.get("ORCH_RISK_MAX_LINES", str(cfg.max_lines)))
        return cfg


@dataclass
class BranchAuditResult:
    """Audit result for a single branch."""
    name: str
    health: BranchHealth = BranchHealth.HEALTHY
    age_days: float = 0.0
    has_task: bool = True
    files_changed: int = 0
    lines_changed: int = 0
    touches_sensitive: bool = False
    conflict_files: list = field(default_factory=list)
    review_verdict: ReviewVerdict = ReviewVerdict.HUMAN_REVIEW
    reasons: list = field(default_factory=list)


@dataclass
class FleetHealthSummary:
    """Aggregate health of the entire branch fleet."""
    total: int = 0
    healthy: int = 0
    stale: int = 0
    orphan: int = 0
    conflicting: int = 0
    merged: int = 0
    auto_approvable: int = 0
    needs_human: int = 0
    blocked: int = 0
    timestamp: str = ""


# ---------------------------------------------------------------------------
# Core audit logic
# ---------------------------------------------------------------------------

def _git(repo, *args, timeout=10):
    """Run a git command and return stdout, or empty string on error."""
    try:
        r = subprocess.run(
            ["git"] + list(args),
            cwd=repo, capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _branch_age_days(repo, branch):
    """How old is the latest commit on this branch, in days."""
    ts = _git(repo, "log", "-1", "--format=%ct", branch)
    if not ts:
        return 999.0
    commit_time = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    delta = datetime.now(tz=timezone.utc) - commit_time
    return round(delta.total_seconds() / 86400, 1)


def _diff_stats(repo, branch, base="master"):
    """Get files changed and lines changed between base and branch."""
    stat = _git(repo, "diff", "--shortstat", f"{base}...{branch}")
    if not stat:
        return 0, 0
    files = 0
    lines = 0
    # e.g. "3 files changed, 120 insertions(+), 5 deletions(-)"
    m_files = re.search(r"(\d+) file", stat)
    m_ins = re.search(r"(\d+) insertion", stat)
    m_del = re.search(r"(\d+) deletion", stat)
    if m_files:
        files = int(m_files.group(1))
    if m_ins:
        lines += int(m_ins.group(1))
    if m_del:
        lines += int(m_del.group(1))
    return files, lines


def _changed_paths(repo, branch, base="master"):
    """List of changed file paths between base and branch."""
    raw = _git(repo, "diff", "--name-only", f"{base}...{branch}")
    return [p for p in raw.split("\n") if p] if raw else []


def _touches_sensitive(paths, globs):
    """Check if any path matches a sensitive glob pattern."""
    for p in paths:
        for g in globs:
            if fnmatch.fnmatch(p, g):
                return True
    return False


def _has_conflicts(repo, branch, base="master"):
    """Check if branch would conflict when merged into base."""
    # Try a dry-run merge
    result = _git(repo, "merge-tree", base, branch)
    # merge-tree outputs conflict markers if any
    if result and "<<<<<<" in result:
        # extract conflict file names
        conflict_files = re.findall(r"^(?:CONFLICT|changed in both)\s.*?(\S+)$", result, re.MULTILINE)
        return conflict_files or ["unknown"]
    return []


def _is_merged(repo, branch, base="master"):
    """Check if branch is already merged into base. Works for LOCAL and REMOTE refs.

    Was `git branch --merged <base>`, which only ever lists LOCAL branches — so every
    remote-tracking ref read as unmerged, and once the fleet audit learned to see origin
    (see audit_fleet) that would have mislabelled all 479 already-merged branches as work
    still owing. `merge-base --is-ancestor` answers the same question for any ref.
    """
    proc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", branch, base],
        cwd=repo, capture_output=True, text=True, timeout=10,
    )
    return proc.returncode == 0


def _remote_agent_branches(repo, remote="origin"):
    """agent/* refs on `remote`, named as `<remote>/agent/<slug>`. Never raises.

    THE STRANDED-WORK GAP. Agent work is pushed to origin and the local ref is then
    deleted along with its worktree, so on any machine that has pruned — which is every
    executor host — the local branch list is nearly empty while the pushed work sits on
    origin. The measured population was 250 stranded branches against 479 already merged;
    a local-only audit reported none of them.
    """
    out = _git(repo, "for-each-ref", "--format=%(refname:short)",
               f"refs/remotes/{remote}/agent/")
    return [line.strip() for line in (out or "").split("\n") if line.strip()]


def _local_agent_branches(repo):
    """agent/* local branches. Never raises."""
    raw = _git(repo, "branch", "--list", "agent/*")
    return [b.strip().lstrip("* +").strip() for b in (raw or "").split("\n") if b.strip()]


def _slug_of(branch):
    """Slug for an agent branch, whatever prefix it carries.

    `origin/agent/foo` and `agent/foo` are the same work; the orphan check and the
    de-duplication in audit_fleet both depend on them resolving to one slug.
    """
    name = str(branch or "")
    if "/agent/" in name:
        name = name.split("/agent/", 1)[1]
    elif name.startswith("agent/"):
        name = name[len("agent/"):]
    return name


# ---------------------------------------------------------------------------
# Audit a single branch
# ---------------------------------------------------------------------------

def audit_branch(repo, branch, task_slugs=None, config=None, base="master"):
    """
    Audit a single agent branch. Returns BranchAuditResult.

    Args:
        repo:        path to git repo
        branch:      branch name (e.g. "agent/foo-bar")
        task_slugs:  set of known task slugs (to detect orphans)
        config:      RiskConfig instance
        base:        base branch name
    """
    cfg = config or RiskConfig()
    result = BranchAuditResult(name=branch)

    # Age
    result.age_days = _branch_age_days(repo, branch)

    # Orphan check: extract slug from branch name
    if task_slugs is not None:
        slug = _slug_of(branch)
        result.has_task = slug in task_slugs
        if not result.has_task:
            result.health = BranchHealth.ORPHAN
            result.reasons.append(f"no matching task for slug '{slug}'")

    # Already merged?
    if _is_merged(repo, branch, base):
        result.health = BranchHealth.MERGED
        result.reasons.append("already merged into base")
        result.review_verdict = ReviewVerdict.AUTO_APPROVE
        return result

    # Stale?
    if result.age_days > cfg.stale_days:
        if result.health != BranchHealth.ORPHAN:
            result.health = BranchHealth.STALE
        result.reasons.append(f"last commit {result.age_days}d ago (threshold {cfg.stale_days}d)")

    # Diff stats
    result.files_changed, result.lines_changed = _diff_stats(repo, branch, base)
    paths = _changed_paths(repo, branch, base)
    result.touches_sensitive = _touches_sensitive(paths, cfg.sensitive_globs)

    # Conflicts
    conflicts = _has_conflicts(repo, branch, base)
    if conflicts:
        result.health = BranchHealth.CONFLICTING
        result.conflict_files = conflicts
        result.reasons.append(f"conflicts in {len(conflicts)} file(s)")

    # If not set to a problem state, it's healthy
    if result.health == BranchHealth.HEALTHY and result.age_days <= cfg.stale_days:
        pass  # stays healthy

    # Review verdict
    result.review_verdict = _compute_verdict(result, cfg)

    return result


def _compute_verdict(result, cfg):
    """Determine review verdict based on audit result and risk config."""
    # Conflicting or orphan → block
    if result.health == BranchHealth.CONFLICTING:
        result.reasons.append("blocked: merge conflicts")
        return ReviewVerdict.BLOCK
    if result.health == BranchHealth.ORPHAN:
        result.reasons.append("blocked: orphan branch")
        return ReviewVerdict.BLOCK

    # Sensitive paths → human review
    if result.touches_sensitive:
        result.reasons.append("human review: touches sensitive paths")
        return ReviewVerdict.HUMAN_REVIEW

    # Too many changes → human review
    if result.files_changed > cfg.max_files:
        result.reasons.append(f"human review: {result.files_changed} files > {cfg.max_files} threshold")
        return ReviewVerdict.HUMAN_REVIEW
    if result.lines_changed > cfg.max_lines:
        result.reasons.append(f"human review: {result.lines_changed} lines > {cfg.max_lines} threshold")
        return ReviewVerdict.HUMAN_REVIEW

    # Stale → human review (might be outdated)
    if result.health == BranchHealth.STALE:
        result.reasons.append("human review: stale branch")
        return ReviewVerdict.HUMAN_REVIEW

    # Otherwise auto-approve
    return ReviewVerdict.AUTO_APPROVE


# ---------------------------------------------------------------------------
# Fleet-wide audit
# ---------------------------------------------------------------------------

def collect_agent_branches(repo, remote="origin", include_remote=True):
    """Every agent branch worth auditing, local first, de-duplicated by slug.

    Local wins when a slug exists both places: it is the same work, and the local ref is
    what a merge would operate on. `include_remote=False` restores the old local-only
    behaviour for a caller that genuinely wants it.
    """
    branches, seen = [], set()
    for branch in _local_agent_branches(repo):
        slug = _slug_of(branch)
        if slug not in seen:
            seen.add(slug)
            branches.append(branch)
    if include_remote:
        for branch in _remote_agent_branches(repo, remote):
            slug = _slug_of(branch)
            if slug not in seen:
                seen.add(slug)
                branches.append(branch)
    return branches


def audit_fleet(repo, task_slugs=None, config=None, base="master",
                remote="origin", include_remote=True):
    """
    Audit all agent/* branches in a repo — LOCAL AND REMOTE.
    Returns (list[BranchAuditResult], FleetHealthSummary).

    This used to list local branches only. On an executor host the local refs are deleted
    with each worktree after the push, so the audit reported a nearly empty fleet while
    the pushed-but-unmerged work accumulated on origin — the "stranded branches" finding
    (250 stranded against 479 merged) that this audit exists to surface and could not see.
    """
    cfg = config or RiskConfig()

    branches = collect_agent_branches(repo, remote=remote, include_remote=include_remote)

    results = []
    for branch in branches:
        r = audit_branch(repo, branch, task_slugs=task_slugs, config=cfg, base=base)
        results.append(r)

    summary = FleetHealthSummary(
        total=len(results),
        timestamp=datetime.now(tz=timezone.utc).isoformat(),
    )
    for r in results:
        if r.health == BranchHealth.HEALTHY:
            summary.healthy += 1
        elif r.health == BranchHealth.STALE:
            summary.stale += 1
        elif r.health == BranchHealth.ORPHAN:
            summary.orphan += 1
        elif r.health == BranchHealth.CONFLICTING:
            summary.conflicting += 1
        elif r.health == BranchHealth.MERGED:
            summary.merged += 1

        if r.review_verdict == ReviewVerdict.AUTO_APPROVE:
            summary.auto_approvable += 1
        elif r.review_verdict == ReviewVerdict.HUMAN_REVIEW:
            summary.needs_human += 1
        elif r.review_verdict == ReviewVerdict.BLOCK:
            summary.blocked += 1

    return results, summary


def format_report(results, summary):
    """Format a human-readable audit report."""
    lines = [
        f"Branch Fleet Audit — {summary.timestamp}",
        f"{'='*60}",
        f"Total: {summary.total} | Healthy: {summary.healthy} | Stale: {summary.stale}",
        f"Orphan: {summary.orphan} | Conflicting: {summary.conflicting} | Merged: {summary.merged}",
        f"Auto-approvable: {summary.auto_approvable} | Needs human: {summary.needs_human} | Blocked: {summary.blocked}",
        "",
    ]

    # Group by verdict
    for verdict in (ReviewVerdict.BLOCK, ReviewVerdict.HUMAN_REVIEW, ReviewVerdict.AUTO_APPROVE):
        group = [r for r in results if r.review_verdict == verdict]
        if not group:
            continue
        lines.append(f"── {verdict.value.upper()} ({len(group)}) ──")
        for r in sorted(group, key=lambda x: -x.age_days):
            lines.append(f"  {r.name}  [{r.health.value}]  {r.age_days}d  "
                         f"{r.files_changed}f/{r.lines_changed}L"
                         f"{'  ⚠SENSITIVE' if r.touches_sensitive else ''}")
            for reason in r.reasons[:3]:
                lines.append(f"    → {reason}")
        lines.append("")

    return "\n".join(lines)
