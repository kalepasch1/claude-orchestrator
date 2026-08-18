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


def _detect_base_branch(repo_path):
    """Detect whether the repo uses main or master."""
    try:
        subprocess.check_output(
            ["git", "rev-parse", "--verify", "master"],
            cwd=repo_path, stderr=subprocess.DEVNULL, timeout=5
        )
        return "master"
    except subprocess.CalledProcessError:
        return "main"


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
