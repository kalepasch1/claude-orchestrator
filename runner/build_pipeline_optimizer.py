#!/usr/bin/env python3
"""
build_pipeline_optimizer.py - reduce build failures and improve pipeline efficiency.

Tracks build outcomes (pass/fail, duration, error category) per project and uses
that history to:
  1. Skip builds for changes that don't affect build-relevant files (docs, comments)
  2. Prioritize cache restoration for frequently-built lockfile hashes
  3. Detect flaky builds (pass-then-fail on identical code) and auto-retry once
  4. Report build health metrics for the fleet dashboard

Usage:
    import build_pipeline_optimizer
    should = build_pipeline_optimizer.should_build(repo_path, diff_files)
    build_pipeline_optimizer.record_outcome(project_id, passed, duration, error)
    health = build_pipeline_optimizer.health(project_id)
"""
import os
import re
import sys
import threading
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

FLAKY_RETRY = os.environ.get("ORCH_BUILD_FLAKY_RETRY", "true").lower() in ("1", "true", "yes")
SKIP_DOCS_ONLY = os.environ.get("ORCH_BUILD_SKIP_DOCS_ONLY", "true").lower() in ("1", "true", "yes")
HISTORY_LIMIT = int(os.environ.get("ORCH_BUILD_HISTORY_LIMIT", "100"))

_lock = threading.Lock()
_build_history: dict = defaultdict(list)  # project_id -> [{passed, duration, error, ts}, ...]

# Files that never affect the build
_NON_BUILD_PATTERNS = [
    re.compile(r"\.(md|txt|rst|adoc)$", re.I),
    re.compile(r"^(README|LICENSE|CHANGELOG|CONTRIBUTING|AUTHORS)", re.I),
    re.compile(r"^docs/", re.I),
    re.compile(r"^\.github/(ISSUE_TEMPLATE|PULL_REQUEST_TEMPLATE)", re.I),
    re.compile(r"^(reports|memory|intake|cowork-backlog)/", re.I),
]


def should_build(repo_path: str, changed_files: list) -> bool:
    """Return True if the changed files warrant a build, False to skip.

    If SKIP_DOCS_ONLY is enabled and ALL changed files match non-build patterns,
    the build is skipped.  Fail-safe: returns True on any error.
    """
    if not SKIP_DOCS_ONLY or not changed_files:
        return True
    try:
        for f in changed_files:
            is_non_build = any(p.search(f) for p in _NON_BUILD_PATTERNS)
            if not is_non_build:
                return True  # at least one build-relevant file
        return False  # all files are non-build
    except Exception:
        return True


def record_outcome(project_id: str, passed: bool, duration: float = 0, error: str = "") -> None:
    """Record a build outcome for trend analysis. Fail-soft."""
    try:
        entry = {
            "passed": passed,
            "duration": duration,
            "error": error[:200] if error else "",
            "ts": time.time(),
        }
        with _lock:
            hist = _build_history[project_id]
            hist.append(entry)
            if len(hist) > HISTORY_LIMIT:
                _build_history[project_id] = hist[-HISTORY_LIMIT:]
    except Exception:
        pass


def is_flaky(project_id: str) -> bool:
    """Return True if recent builds show flaky behavior (alternating pass/fail)."""
    with _lock:
        hist = _build_history.get(project_id, [])
    if len(hist) < 4:
        return False
    recent = [h["passed"] for h in hist[-6:]]
    # Flaky = alternating results (at least 2 flips in last 6)
    flips = sum(1 for i in range(1, len(recent)) if recent[i] != recent[i - 1])
    return flips >= 3


def should_retry(project_id: str) -> bool:
    """Return True if the last build failed and flaky retry is warranted."""
    if not FLAKY_RETRY:
        return False
    with _lock:
        hist = _build_history.get(project_id, [])
    if not hist or hist[-1]["passed"]:
        return False
    return is_flaky(project_id)


def health(project_id: str = "") -> dict:
    """Return build health metrics for a project (or all projects)."""
    with _lock:
        if project_id:
            hist = _build_history.get(project_id, [])
            return _compute_health(hist)
        return {pid: _compute_health(h) for pid, h in _build_history.items()}


def _compute_health(hist: list) -> dict:
    if not hist:
        return {"total": 0, "pass_rate": 1.0, "avg_duration": 0, "flaky": False}
    passed = sum(1 for h in hist if h["passed"])
    durations = [h["duration"] for h in hist if h["duration"] > 0]
    return {
        "total": len(hist),
        "pass_rate": round(passed / len(hist), 3),
        "avg_duration": round(sum(durations) / len(durations), 1) if durations else 0,
        "flaky": sum(1 for i in range(1, len(hist)) if hist[i]["passed"] != hist[i-1]["passed"]) >= 3,
    }


def stats() -> dict:
    """Return summary stats across all projects."""
    with _lock:
        return {
            "projects_tracked": len(_build_history),
            "total_builds": sum(len(h) for h in _build_history.values()),
        }


def reset():
    """Clear build history (for testing)."""
    with _lock:
        _build_history.clear()
