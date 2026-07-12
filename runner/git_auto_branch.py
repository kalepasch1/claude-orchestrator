#!/usr/bin/env python3
"""git_auto_branch.py - automated branch lifecycle management.

Slice-3: eliminates manual branch handling that causes inconsistencies and merge delays.
  - Auto-creates correctly-named branches for new tasks
  - Auto-deletes merged/abandoned branches after a grace period
  - Auto-rebases stale branches onto fresh base to prevent conflicts
  - Enforces naming conventions (agent/<slug>)

Runs periodically via the runner loop. Only operates on local repos.
"""
import datetime, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import branch_naming

STALE_DAYS = int(os.environ.get("ORCH_BRANCH_STALE_DAYS", "7"))
GRACE_HOURS = int(os.environ.get("ORCH_BRANCH_GRACE_HOURS", "24"))
GIT_TIMEOUT = int(os.environ.get("ORCH_GIT_TIMEOUT", "60"))
BRANCH_PREFIX = "agent/"


def _git(args, repo):
    """Run a git command, return (stdout, ok)."""
    try:
        r = subprocess.run(["git"] + args, cwd=repo, capture_output=True,
                           text=True, timeout=GIT_TIMEOUT)
        return r.stdout.strip(), r.returncode == 0
    except Exception:
        return "", False


def _active_slugs():
    """Slugs with tasks in non-terminal states — these branches must not be touched."""
    active = set()
    for state in ("QUEUED", "RUNNING", "RETRY", "BLOCKED", "TESTFAIL", "CONFLICT"):
        try:
            rows = db.select("tasks", {"select": "slug", "state": f"eq.{state}"}) or []
            active.update(r["slug"] for r in rows if r.get("slug"))
        except Exception:
            continue
    return active


def _merged_slugs():
    """Slugs that reached MERGED — safe for branch cleanup after grace."""
    try:
        rows = db.select("tasks", {"select": "slug,updated_at", "state": "eq.MERGED",
                                   "limit": "500"}) or []
        return {r["slug"]: r.get("updated_at", "") for r in rows if r.get("slug")}
    except Exception:
        return {}


def _done_slugs():
    """Slugs in DONE state — branches can be cleaned after grace."""
    try:
        rows = db.select("tasks", {"select": "slug,updated_at", "state": "eq.DONE",
                                   "limit": "500"}) or []
        return {r["slug"]: r.get("updated_at", "") for r in rows if r.get("slug")}
    except Exception:
        return {}


def cleanup_merged_branches(repo):
    """Delete local branches for tasks that are MERGED or DONE past the grace period."""
    if not repo or not os.path.isdir(repo):
        return 0
    active = _active_slugs()
    merged = _merged_slugs()
    done = _done_slugs()
    terminal = {**merged, **done}
    now = datetime.datetime.utcnow()

    out, ok = _git(["branch", "--list", f"{BRANCH_PREFIX}*"], repo)
    if not ok:
        return 0
    branches = [b.strip().lstrip("* ") for b in out.splitlines() if b.strip()]
    removed = 0
    for branch in branches:
        slug = branch.removeprefix(BRANCH_PREFIX)
        if slug in active:
            continue
        if slug not in terminal:
            continue
        # Check grace period
        ts_str = terminal.get(slug, "")
        if ts_str:
            try:
                updated = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00").replace("+00:00", ""))
                if (now - updated).total_seconds() < GRACE_HOURS * 3600:
                    continue
            except Exception:
                pass
        _, ok = _git(["branch", "-D", branch], repo)
        if ok:
            removed += 1
    return removed


def ensure_branch(repo, slug, base="master"):
    """Create a correctly-named branch for a task if it doesn't exist yet.
    Returns the branch name or None on failure."""
    branch = f"{BRANCH_PREFIX}{slug}"
    # Check if branch already exists
    _, exists = _git(["rev-parse", "--verify", branch], repo)
    if exists:
        return branch
    # Create from base
    _, ok = _git(["branch", branch, base], repo)
    if ok:
        return branch
    # Base might need fetching
    _git(["fetch", "origin", base], repo)
    _, ok = _git(["branch", branch, f"origin/{base}"], repo)
    return branch if ok else None


def ensure_branch_safe(repo, slug, base="master"):
    """Like ensure_branch but deduplicates the slug against existing branches first.

    Returns (branch_name, final_slug) or (None, slug) on failure.
    """
    out, ok = _git(["branch", "--list", f"{BRANCH_PREFIX}*"], repo)
    existing = set()
    if ok:
        for b in out.splitlines():
            existing.add(b.strip().lstrip("* ").removeprefix(BRANCH_PREFIX))
    final_slug = branch_naming.deduplicate_slug(slug, existing)
    branch = ensure_branch(repo, final_slug, base)
    return (branch, final_slug) if branch else (None, slug)


def rebase_stale_branches(repo, base="master"):
    """Rebase active task branches that are far behind base to prevent conflicts.
    Only touches branches for QUEUED tasks (not yet started)."""
    if not repo or not os.path.isdir(repo):
        return 0
    active = _active_slugs()
    # Only rebase queued tasks — running ones shouldn't be disturbed
    try:
        queued = {r["slug"] for r in (db.select("tasks", {"select": "slug", "state": "eq.QUEUED"}) or []) if r.get("slug")}
    except Exception:
        return 0

    out, ok = _git(["branch", "--list", f"{BRANCH_PREFIX}*"], repo)
    if not ok:
        return 0
    branches = [b.strip().lstrip("* ") for b in out.splitlines() if b.strip()]
    rebased = 0
    for branch in branches:
        slug = branch.removeprefix(BRANCH_PREFIX)
        if slug not in queued:
            continue
        # Check how far behind base
        behind_out, ok = _git(["rev-list", "--count", f"{branch}..{base}"], repo)
        if not ok:
            continue
        try:
            behind = int(behind_out)
        except ValueError:
            continue
        if behind < 10:  # not stale enough to warrant rebase
            continue
        _, ok = _git(["rebase", base, branch], repo)
        if ok:
            rebased += 1
        else:
            _git(["rebase", "--abort"], repo)  # clean up failed rebase
    return rebased


def run():
    """Periodic branch lifecycle management across all registered projects."""
    try:
        projects = db.select("projects", {"select": "id,name,repo_path,default_base"}) or []
    except Exception:
        print("git_auto_branch: could not load projects")
        return {"cleaned": 0, "rebased": 0}
    total_cleaned = 0
    total_rebased = 0
    for p in projects:
        repo = p.get("repo_path")
        if not repo or not os.path.isdir(repo):
            continue
        base = p.get("default_base") or "master"
        total_cleaned += cleanup_merged_branches(repo)
        total_rebased += rebase_stale_branches(repo, base)
    print(f"git_auto_branch: cleaned {total_cleaned}, rebased {total_rebased}")
    return {"cleaned": total_cleaned, "rebased": total_rebased}


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
