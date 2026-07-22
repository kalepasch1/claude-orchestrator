#!/usr/bin/env python3
"""
build_gate.py - scan unmerged agent/* branches for build failure reasons.

Scans local git branches matching agent/* that have not been merged into
the base branch (master/main).  For each branch, inspects the most recent
commit message and any CI-style notes for build failure indicators.
Extracts structured failure reasons so downstream modules (e.g.
branch_reconciler) can cluster and propose fixes.

Feature flag: ORCH_BUILD_GATE_ENABLED (default true)
Fail-soft: every public function returns a safe default on error.
"""
import os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

ENABLED = os.environ.get("ORCH_BUILD_GATE_ENABLED", "true").lower() in ("1", "true", "yes", "on")

_FAILURE_PATTERNS = [
    (re.compile(r"ModuleNotFoundError:\s*No module named ['\"]?(\S+)['\"]?", re.I), "missing_module"),
    (re.compile(r"ImportError:\s*cannot import name ['\"]?(\S+)['\"]?", re.I), "import_error"),
    (re.compile(r'relation "(\S+)" does not exist', re.I), "missing_table"),
    (re.compile(r"column [\"']?(\S+?)[\"']? (?:does not exist|of relation)", re.I), "missing_column"),
    (re.compile(r"FileNotFoundError:.*No such file.*?['\"]([^'\"]+)['\"]", re.I), "missing_file"),
    (re.compile(r"(SyntaxError:.*)", re.I), "syntax_error"),
    (re.compile(r"(TypeError:.*)", re.I), "type_error"),
    (re.compile(r"build[_ ]?fail|compilation[_ ]?error", re.I), "build_failure"),
    (re.compile(r"test[_ ]?fail", re.I), "test_failure"),
]


def _git(repo, *args, timeout=30):
    """Run a git command, return (returncode, stdout, stderr). Fail-soft."""
    try:
        r = subprocess.run(
            ["git"] + list(args), cwd=repo,
            capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return -1, "", str(e)


def _default_repo():
    """Resolve the repo path from the first project in the DB, or cwd."""
    try:
        rows = db.select("projects", {"select": "repo_path", "limit": "1"}) or []
        if rows and rows[0].get("repo_path"):
            return rows[0]["repo_path"]
    except Exception:
        pass
    return os.getcwd()


def scan_branches(repo=None):
    """List unmerged agent/* branches.

    Returns a list of branch name strings.  Fail-soft: returns [] on error.
    """
    if not ENABLED:
        return []
    repo = repo or _default_repo()
    rc, out, _ = _git(repo, "branch", "--no-merged", "master", "--list", "agent/*")
    if rc != 0:
        # Try 'main' as fallback base branch
        rc, out, _ = _git(repo, "branch", "--no-merged", "main", "--list", "agent/*")
    if rc != 0 or not out:
        return []
    branches = []
    for line in out.splitlines():
        name = line.strip().lstrip("* ")
        if name:
            branches.append(name)
    return branches


def _extract_failures(text):
    """Extract failure reasons from text using known patterns.

    Returns a list of dicts: [{type, detail}]
    """
    failures = []
    seen = set()
    for pattern, kind in _FAILURE_PATTERNS:
        for m in pattern.finditer(text):
            detail = m.group(1) if m.lastindex else m.group(0)
            key = (kind, detail)
            if key not in seen:
                seen.add(key)
                failures.append({"type": kind, "detail": detail})
    return failures


def check_build_status(branch, repo=None):
    """Check if a branch has build failures, extract failure reasons.

    Returns dict: {branch, has_failures, reasons: [{type, detail}]}
    Fail-soft: returns {has_failures: False, reasons: []} on error.
    """
    if not ENABLED:
        return {"branch": branch, "has_failures": False, "reasons": []}
    repo = repo or _default_repo()
    # Gather evidence: last few commit messages + notes
    rc, log_text, _ = _git(repo, "log", branch, "--not", "master",
                           "--format=%B%n---", "-n", "5")
    if rc != 0:
        rc, log_text, _ = _git(repo, "log", branch, "--not", "main",
                               "--format=%B%n---", "-n", "5")
    # Also check git notes (CI annotations)
    rc2, notes_text, _ = _git(repo, "notes", "--ref=ci", "show", branch)
    combined = (log_text or "") + "\n" + (notes_text if rc2 == 0 else "")
    # Check task table for notes about this branch
    try:
        slug = branch.replace("agent/", "", 1)
        rows = db.select("tasks", {"select": "note,log_tail", "slug": f"eq.{slug}", "limit": "1"}) or []
        if rows:
            combined += "\n" + (rows[0].get("note") or "") + "\n" + (rows[0].get("log_tail") or "")
    except Exception:
        pass
    reasons = _extract_failures(combined)
    return {"branch": branch, "has_failures": bool(reasons), "reasons": reasons}


def get_failure_reasons(branches, repo=None):
    """Batch check all branches, return dict of branch -> failure_reasons list.

    Fail-soft: branches that error out get an empty list.
    """
    if not ENABLED:
        return {}
    repo = repo or _default_repo()
    result = {}
    for branch in (branches or []):
        try:
            status = check_build_status(branch, repo=repo)
            result[branch] = status.get("reasons", [])
        except Exception:
            result[branch] = []
    return result


def stats():
    """Module statistics."""
    try:
        repo = _default_repo()
        branches = scan_branches(repo)
        failures = get_failure_reasons(branches, repo)
        with_failures = sum(1 for v in failures.values() if v)
        return {
            "enabled": ENABLED,
            "unmerged_agent_branches": len(branches),
            "branches_with_failures": with_failures,
        }
    except Exception:
        return {"enabled": ENABLED, "unmerged_agent_branches": 0, "branches_with_failures": 0}
