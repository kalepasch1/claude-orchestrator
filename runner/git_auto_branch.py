#!/usr/bin/env python3
"""git_auto_branch.py - automated branch lifecycle management.

Slice-3: eliminates manual branch handling that causes inconsistencies and merge delays.
  - Auto-creates correctly-named branches for new tasks
  - Auto-deletes merged/abandoned branches after a grace period
  - Auto-rebases stale branches onto fresh base to prevent conflicts
  - Enforces naming conventions (agent/<slug>)
  - Cleans up stale worktrees that block branch operations

Runs periodically via the runner loop. Only operates on local repos.
"""
import datetime, os, subprocess, sys, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import branch_naming

STALE_DAYS = int(os.environ.get("ORCH_BRANCH_STALE_DAYS", "7"))
GRACE_HOURS = int(os.environ.get("ORCH_BRANCH_GRACE_HOURS", "24"))
GIT_TIMEOUT = int(os.environ.get("ORCH_GIT_TIMEOUT", "60"))
BRANCH_PREFIX = "agent/"

# Maximum slug length to prevent filesystem/git issues
MAX_SLUG_LENGTH = int(os.environ.get("ORCH_MAX_SLUG_LENGTH", "200"))
# Pattern for valid slug characters
_SLUG_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")


def _log_info(msg):
    """Structured log output."""
    print(f"git_auto_branch: {msg}")


def _log_warn(msg):
    """Warning-level log output."""
    print(f"git_auto_branch [WARN]: {msg}")


def _git(args, repo):
    """Run a git command, return (stdout, ok)."""
    try:
        r = subprocess.run(["git"] + args, cwd=repo, capture_output=True,
                           text=True, timeout=GIT_TIMEOUT)
        return r.stdout.strip(), r.returncode == 0
    except subprocess.TimeoutExpired:
        _log_warn(f"git timeout ({GIT_TIMEOUT}s) for: git {' '.join(args[:3])}")
        return "", False
    except Exception as exc:
        _log_warn(f"git error for {args[:3]}: {exc}")
        return "", False


def validate_slug(slug):
    """Validate a branch slug. Returns (ok, reason)."""
    if not slug:
        return False, "empty slug"
    if len(slug) > MAX_SLUG_LENGTH:
        return False, f"slug exceeds {MAX_SLUG_LENGTH} chars ({len(slug)})"
    if slug.startswith("-") or slug.startswith("."):
        return False, "slug must not start with - or ."
    if slug.endswith(".lock"):
        return False, "slug must not end with .lock (git restriction)"
    if ".." in slug:
        return False, "slug must not contain .. (git restriction)"
    # Allow the common slug pattern but warn on unusual chars
    if not _SLUG_RE.match(slug):
        # Don't reject — many existing slugs have unusual patterns — just flag it
        _log_warn(f"slug has unusual characters: {slug[:80]}")
    return True, "valid"


def _active_slugs():
    """Slugs with tasks in non-terminal states — these branches must not be touched."""
    active = set()
    for state in ("QUEUED", "RUNNING", "RETRY", "BLOCKED", "TESTFAIL", "CONFLICT"):
        try:
            rows = db.select("tasks", {"select": "slug", "state": f"eq.{state}"}) or []
            active.update(r["slug"] for r in rows if r.get("slug"))
        except Exception as e:
            print(f"git_auto_branch: Error fetching active slugs for state {state}: {e}", file=sys.stderr)
            continue
    return active


def _merged_slugs():
    """Slugs that reached MERGED — safe for branch cleanup after grace."""
    try:
        rows = db.select("tasks", {"select": "slug,updated_at", "state": "eq.MERGED",
                                   "limit": "500"}) or []
        return {r["slug"]: r.get("updated_at", "") for r in rows if r.get("slug")}
    except Exception as e:
        print(f"git_auto_branch: Error fetching merged slugs: {e}", file=sys.stderr)
        return {}


def _done_slugs():
    """Slugs in DONE state — branches can be cleaned after grace."""
    try:
        rows = db.select("tasks", {"select": "slug,updated_at", "state": "eq.DONE",
                                   "limit": "500"}) or []
        return {r["slug"]: r.get("updated_at", "") for r in rows if r.get("slug")}
    except Exception as e:
        print(f"git_auto_branch: Error fetching done slugs: {e}", file=sys.stderr)
        return {}


def cleanup_stale_worktrees(repo):
    """Prune git worktrees that reference missing directories, then remove
    worktrees for terminal-state tasks. This prevents 'already checked out'
    errors that block branch operations.
    Returns count of worktrees removed."""
    if not repo or not os.path.isdir(repo):
        return 0
    # First: let git prune broken worktree references
    _git(["worktree", "prune"], repo)

    out, ok = _git(["worktree", "list", "--porcelain"], repo)
    if not ok:
        return 0

    active = _active_slugs()
    terminal = {**_merged_slugs(), **_done_slugs()}

    # Parse worktree list — format: "worktree <path>\nHEAD <sha>\nbranch refs/heads/<name>\n\n"
    removed = 0
    current_path = None
    current_branch = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            current_path = line[len("worktree "):]
            current_branch = None
        elif line.startswith("branch refs/heads/"):
            current_branch = line[len("branch refs/heads/"):]
        elif line == "" and current_path and current_branch:
            # End of a worktree entry — evaluate for removal
            if current_branch.startswith(BRANCH_PREFIX):
                slug = current_branch.removeprefix(BRANCH_PREFIX)
                if slug not in active and slug in terminal:
                    _, ok = _git(["worktree", "remove", "--force", current_path], repo)
                    if ok:
                        removed += 1
                        _log_info(f"removed stale worktree: {current_path}")
            current_path = None
            current_branch = None

    return removed


def cleanup_merged_branches(repo):
    """Delete local branches for tasks that are MERGED or DONE past the grace period."""
    if not repo or not os.path.isdir(repo):
        return 0
    active = _active_slugs()
    merged = _merged_slugs()
    done = _done_slugs()
    terminal = {**merged, **done}
    now = datetime.datetime.now(datetime.timezone.utc) # Use timezone-aware UTC now

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
                updated = datetime.datetime.fromisoformat(ts_str)
                if updated.tzinfo is None: # If naive, assume UTC
                    updated = updated.replace(tzinfo=datetime.timezone.utc)

                if (now - updated).total_seconds() < GRACE_HOURS * 3600:
                    continue
            except ValueError as e: # Catch specific error for fromisoformat
                print(f"git_auto_branch: Error parsing timestamp for slug {slug}: {e}", file=sys.stderr)
                pass
            except Exception as e: # Catch other potential errors during comparison
                print(f"git_auto_branch: Unexpected error during grace period check for slug {slug}: {e}", file=sys.stderr)
                pass
        _, ok = _git(["branch", "-D", branch], repo)
        if ok:
            removed += 1
            _log_info(f"deleted branch: {branch}")
    return removed


def ensure_branch(repo, slug, base="master"):
    """Create a correctly-named branch for a task if it doesn't exist yet.
    Validates the slug before creating. Returns the branch name or None on failure."""
    ok, reason = validate_slug(slug)
    if not ok:
        _log_warn(f"ensure_branch rejected slug: {reason}")
        return None

    branch = f"{BRANCH_PREFIX}{slug}"
    # Check if branch already exists
    _, exists = _git(["rev-parse", "--verify", branch], repo)
    if exists:
        return branch
    # Create from base
    _, ok = _git(["branch", branch, base], repo)
    if ok:
        _log_info(f"created branch: {branch}")
        return branch
    # Base might need fetching
    _git(["fetch", "origin", base], repo)
    _, ok = _git(["branch", branch, f"origin/{base}"], repo)
    if ok:
        _log_info(f"created branch: {branch} (after fetch)")
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
    except Exception as e:
        print(f"git_auto_branch: Error fetching queued slugs for rebase: {e}", file=sys.stderr)
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
        except ValueError as e:
            print(f"git_auto_branch: Error parsing rev-list count for branch {branch}: {e}", file=sys.stderr)
            continue
        if behind < 10:  # not stale enough to warrant rebase
            continue
        _, ok = _git(["rebase", base, branch], repo)
        if ok:
            rebased += 1
            _log_info(f"rebased {branch} onto {base} (was {behind} commits behind)")
        else:
            _git(["rebase", "--abort"], repo)  # clean up failed rebase
            _log_warn(f"rebase failed for {branch}, aborted")
    return rebased


def run():
    """Periodic branch lifecycle management across all registered projects."""
    try:
        projects = db.select("projects", {"select": "id,name,repo_path,default_base"}) or []
    except Exception:
        _log_warn("could not load projects")
        return {"cleaned": 0, "rebased": 0, "worktrees_removed": 0}
    total_cleaned = 0
    total_rebased = 0
    total_worktrees = 0
    for p in projects:
        repo = p.get("repo_path")
        if not repo or not os.path.isdir(repo):
            continue
        base = p.get("default_base") or "master"
        # Clean worktrees first — this unblocks branch deletion
        total_worktrees += cleanup_stale_worktrees(repo)
        total_cleaned += cleanup_merged_branches(repo)
        total_rebased += rebase_stale_branches(repo, base)
    _log_info(f"cleaned {total_cleaned}, rebased {total_rebased}, worktrees removed {total_worktrees}")
    return {"cleaned": total_cleaned, "rebased": total_rebased, "worktrees_removed": total_worktrees}


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
