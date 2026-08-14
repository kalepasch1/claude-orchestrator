"""
branch_manager.py — advanced branch management for the orchestrator.

Handles branch lifecycle: creation, cleanup of stale branches, conflict detection,
and automated pruning of merged branches. Reduces manual intervention and prevents
branch accumulation.
"""
import os, sys, subprocess, logging, re, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

log = logging.getLogger(__name__)

# Max age for unmerged agent branches before cleanup consideration
STALE_BRANCH_DAYS = int(os.environ.get("ORCH_STALE_BRANCH_DAYS", "14"))


def list_agent_branches(repo_path):
    """List all agent/* branches in a repo with their last commit date."""
    try:
        output = subprocess.check_output(
            ["git", "for-each-ref", "--sort=-committerdate",
             "--format=%(refname:short)|%(committerdate:iso)|%(subject)",
             "refs/heads/agent/"],
            cwd=repo_path, text=True, stderr=subprocess.DEVNULL, timeout=30
        ).strip()
    except Exception:
        return []

    branches = []
    for line in output.split("\n"):
        if not line.strip():
            continue
        parts = line.split("|", 2)
        if len(parts) >= 2:
            branches.append({
                "name": parts[0],
                "date": parts[1].strip(),
                "subject": parts[2].strip() if len(parts) > 2 else "",
            })
    return branches


def find_stale_branches(repo_path, max_age_days=None):
    """Find agent branches older than max_age_days that aren't merged."""
    if max_age_days is None:
        max_age_days = STALE_BRANCH_DAYS

    import datetime
    cutoff = datetime.datetime.now() - datetime.timedelta(days=max_age_days)
    branches = list_agent_branches(repo_path)
    stale = []

    for b in branches:
        try:
            # Parse the date (ISO format from git)
            date_str = b["date"].split(" +")[0].split(" -")[0].strip()
            branch_date = datetime.datetime.fromisoformat(date_str)
            if branch_date < cutoff:
                # Check if merged into master/main
                base = _detect_base_branch(repo_path)
                try:
                    subprocess.check_output(
                        ["git", "merge-base", "--is-ancestor", b["name"], base],
                        cwd=repo_path, stderr=subprocess.DEVNULL, timeout=10
                    )
                    # If no error, branch is merged — safe to delete
                    b["status"] = "merged"
                except subprocess.CalledProcessError:
                    b["status"] = "unmerged"
                stale.append(b)
        except Exception:
            continue

    return stale


def _ref_exists(repo_path, ref):
    """True when `ref` resolves in `repo_path`. Fail-soft: any error → False."""
    try:
        return subprocess.call(
            ["git", "rev-parse", "--verify", "--quiet", ref],
            cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=5,
        ) == 0
    except Exception:
        # git missing, timeout, repo_path not a directory, permission error —
        # a detector that raises wedges every caller that depends on it.
        return False


def _configured_base(repo_path):
    """
    The project's declared default_base for this checkout, or "".

    projects.default_base is the fleet's source of truth — db._guard_task_base_branch
    already treats it as authoritative when correcting task rows. Reading it here
    is what lets detection return a non-generic default like darwn's `medicalOnly`,
    which a main/master-only probe can never produce.
    """
    try:
        real = os.path.realpath(repo_path)
        for row in db.select("projects", {"select": "repo_path,default_base"}) or []:
            if os.path.realpath(str(row.get("repo_path") or "")) == real:
                return (row.get("default_base") or "").strip()
    except Exception:
        pass
    return ""


def _origin_head(repo_path):
    """The branch origin/HEAD points at, or "". Authoritative when it is set."""
    try:
        out = subprocess.check_output(
            ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
            cwd=repo_path, text=True, stderr=subprocess.DEVNULL, timeout=5,
        ).strip()
        return out.split("origin/", 1)[1] if out.startswith("origin/") else ""
    except Exception:
        return ""


def _detect_base_branch(repo_path):
    """
    Resolve this repo's base branch.

    The previous implementation probed local `master` and returned `main` on
    anything else. Three ways that was wrong:

      1. It only caught CalledProcessError. A TimeoutExpired, a missing git, or
         an unreadable repo_path propagated out and wedged find_stale_branches
         and detect_conflicts — both of which call this on every branch.
      2. It consulted local refs only. A fresh clone or an agent worktree may
         have `origin/master` and no local `master`, so a master repo was
         reported as `main` and every downstream `origin/main` lookup failed.
      3. It could only ever answer "main" or "master". darwn's default is
         `medicalOnly`, so detection was structurally incapable of being right
         there.

    Resolution order — declared intent first, observed repo state second:
      projects.default_base (when the ref actually exists here)
        → origin/HEAD
        → first of origin/master, origin/main, master, main that resolves
        → "master"

    A configured default that does not resolve in this checkout is deliberately
    NOT returned: naming a branch that is not there is the failure this is meant
    to prevent. Never raises.
    """
    configured = _configured_base(repo_path)
    if configured and (_ref_exists(repo_path, configured)
                       or _ref_exists(repo_path, f"origin/{configured}")):
        return configured

    head = _origin_head(repo_path)
    if head and (_ref_exists(repo_path, head) or _ref_exists(repo_path, f"origin/{head}")):
        return head

    for candidate in ("origin/master", "origin/main", "master", "main"):
        if _ref_exists(repo_path, candidate):
            return candidate.split("origin/", 1)[-1]

    return "master"


def cleanup_merged_branches(repo_path, dry_run=True):
    """Delete local agent branches that have been merged into the base branch.

    Returns list of deleted branch names. In dry_run mode, just lists them.
    """
    stale = find_stale_branches(repo_path)
    merged = [b for b in stale if b.get("status") == "merged"]
    deleted = []

    for b in merged:
        name = b["name"]
        if dry_run:
            log.info("branch_manager: would delete merged branch %s", name)
            deleted.append(name)
        else:
            try:
                subprocess.check_output(
                    ["git", "branch", "-d", name],
                    cwd=repo_path, text=True, stderr=subprocess.DEVNULL, timeout=10
                )
                deleted.append(name)
                log.info("branch_manager: deleted merged branch %s", name)
            except Exception as e:
                log.warning("branch_manager: failed to delete %s: %s", name, e)

    return deleted


def detect_conflicts(repo_path, branch_name, base_branch=None):
    """Check if a branch would conflict when merged into the base branch.

    Returns (has_conflict: bool, conflicting_files: list).
    """
    if base_branch is None:
        base_branch = _detect_base_branch(repo_path)

    try:
        # Use merge-tree to detect conflicts without modifying working tree
        result = subprocess.run(
            ["git", "merge-tree", "--write-tree", base_branch, branch_name],
            cwd=repo_path, capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            # Parse conflict file list from stderr
            conflicts = re.findall(r"CONFLICT.*?: (.+)", result.stderr)
            return True, conflicts
        return False, []
    except Exception as e:
        log.warning("branch_manager: conflict detection failed for %s: %s", branch_name, e)
        return False, []


def branch_health_report(repo_path):
    """Generate a health report for all agent branches."""
    branches = list_agent_branches(repo_path)
    stale = find_stale_branches(repo_path)
    merged_stale = [b for b in stale if b.get("status") == "merged"]
    unmerged_stale = [b for b in stale if b.get("status") == "unmerged"]

    return {
        "total_branches": len(branches),
        "stale_merged": len(merged_stale),
        "stale_unmerged": len(unmerged_stale),
        "active": len(branches) - len(stale),
        "stale_merged_names": [b["name"] for b in merged_stale[:10]],
        "stale_unmerged_names": [b["name"] for b in unmerged_stale[:10]],
    }


if __name__ == "__main__":
    import json
    repos = {
        "beethoven": os.path.expanduser("~/Documents/beethoven/claude-orchestrator"),
        "tomorrow": os.path.expanduser("~/Documents/tomorrow/tomorrow"),
    }
    for name, path in repos.items():
        if os.path.isdir(path):
            report = branch_health_report(path)
            print(f"\n{name}: {json.dumps(report, indent=2)}")
