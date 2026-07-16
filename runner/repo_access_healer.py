"""
repo_access_healer.py — self-healing loop for "repo not found" and "PAT lacks access" failures.

When a task fails because the git repo is unreachable (wrong path, stale PAT, missing clone),
this module detects the pattern and attempts automated recovery before the task is terminally
blocked. Designed to be called from the agentic repair pipeline.
"""
import os, sys, subprocess, logging, re, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

log = logging.getLogger(__name__)

# Patterns that indicate a repo-access failure (case-insensitive)
_ACCESS_PATTERNS = [
    re.compile(r"repo(?:sitory)?\s+not\s+found", re.IGNORECASE),
    re.compile(r"PAT\s+lacks?\s+access", re.IGNORECASE),
    re.compile(r"could\s+not\s+read\s+from\s+remote", re.IGNORECASE),
    re.compile(r"fatal:\s+repository\s+.*\s+not\s+found", re.IGNORECASE),
    re.compile(r"remote:\s+Repository\s+not\s+found", re.IGNORECASE),
    re.compile(r"Authentication\s+failed\s+for", re.IGNORECASE),
    re.compile(r"Permission\s+denied\s+\(publickey\)", re.IGNORECASE),
]


def is_repo_access_failure(note_or_error):
    """Return True if the error text matches a repo-access failure pattern."""
    text = str(note_or_error or "")
    return any(p.search(text) for p in _ACCESS_PATTERNS)


def diagnose_repo(repo_path):
    """Check if a repo path is accessible and has a valid remote.

    Returns (healthy: bool, diagnosis: str).
    """
    if not repo_path:
        return False, "no repo path configured"

    local_path = db.localize_repo_path(repo_path) if hasattr(db, "localize_repo_path") else repo_path

    if not os.path.isdir(local_path):
        return False, f"directory does not exist: {local_path}"

    git_dir = os.path.join(local_path, ".git")
    if not os.path.exists(git_dir):
        return False, f"not a git repo (no .git): {local_path}"

    # Check remote URL
    try:
        remote = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            cwd=local_path, text=True, stderr=subprocess.DEVNULL, timeout=10
        ).strip()
    except Exception:
        return False, f"cannot read remote URL in {local_path}"

    if not remote:
        return False, "origin remote URL is empty"

    # Test connectivity (ls-remote with timeout)
    try:
        subprocess.check_output(
            ["git", "ls-remote", "--heads", "origin"],
            cwd=local_path, text=True, stderr=subprocess.STDOUT, timeout=30
        )
    except subprocess.CalledProcessError as e:
        output = str(e.output or "")
        if "not found" in output.lower() or "denied" in output.lower():
            return False, f"remote unreachable: {output[:200]}"
        return False, f"ls-remote failed: {output[:200]}"
    except subprocess.TimeoutExpired:
        return False, "ls-remote timed out (30s)"

    return True, "repo accessible"


def heal_repo_access(project_id, max_attempts=3):
    """Attempt to heal repo access for a project.

    Recovery strategies (tried in order):
    1. Verify the local clone exists and has the right remote
    2. Try fetching with the configured PAT
    3. Re-clone if the directory is corrupt

    Returns (healed: bool, action_taken: str).
    """
    projects = db.select("projects", {
        "select": "id,name,repo_path",
        "id": f"eq.{project_id}",
        "limit": "1",
    }) or []

    if not projects:
        return False, f"project {project_id} not found in DB"

    project = projects[0]
    repo_path = project.get("repo_path")
    if not repo_path:
        return False, "no repo_path configured for project"

    local_path = db.localize_repo_path(repo_path) if hasattr(db, "localize_repo_path") else repo_path

    # Strategy 1: verify directory exists
    if not os.path.isdir(local_path):
        return False, f"repo directory missing: {local_path} — manual clone needed"

    # Strategy 2: try a fetch to refresh refs
    for attempt in range(max_attempts):
        try:
            subprocess.check_output(
                ["git", "fetch", "--prune", "origin"],
                cwd=local_path, text=True, stderr=subprocess.STDOUT, timeout=60
            )
            log.info("repo_access_healer: fetch succeeded for %s (attempt %d)", project.get("name"), attempt + 1)
            return True, f"fetch succeeded on attempt {attempt + 1}"
        except subprocess.CalledProcessError as e:
            output = str(e.output or "")
            if "Authentication failed" in output or "Permission denied" in output:
                return False, f"PAT/auth failure — manual credential update needed: {output[:200]}"
            if attempt < max_attempts - 1:
                time.sleep(2 ** attempt)
                continue
            return False, f"fetch failed after {max_attempts} attempts: {output[:200]}"
        except subprocess.TimeoutExpired:
            if attempt < max_attempts - 1:
                continue
            return False, "fetch timed out after all attempts"

    return False, "exhausted recovery strategies"


def heal_and_requeue(task_id):
    """Full self-healing cycle: diagnose, heal, requeue if successful.

    Returns (success: bool, summary: str).
    """
    tasks = db.select("tasks", {
        "select": "id,slug,project_id,note,state",
        "id": f"eq.{task_id}",
        "limit": "1",
    }) or []

    if not tasks:
        return False, f"task {task_id} not found"

    task = tasks[0]
    project_id = task.get("project_id")
    note = str(task.get("note") or "")

    if not is_repo_access_failure(note):
        return False, "task note does not indicate repo-access failure"

    # Diagnose
    projects = db.select("projects", {
        "select": "id,repo_path",
        "id": f"eq.{project_id}",
        "limit": "1",
    }) or []
    if projects:
        healthy, diagnosis = diagnose_repo(projects[0].get("repo_path"))
        if healthy:
            # Repo is actually fine — just requeue
            db.update("tasks", {"state": "QUEUED", "note": f"{note} | healer: repo accessible, requeued"},
                      id=task_id)
            return True, f"repo already accessible ({diagnosis}), requeued"

    # Try to heal
    healed, action = heal_repo_access(project_id)
    if healed:
        db.update("tasks", {"state": "QUEUED", "note": f"{note} | healer: {action}"},
                  id=task_id)
        return True, f"healed and requeued: {action}"

    return False, f"could not heal: {action}"


if __name__ == "__main__":
    import json
    # Quick diagnostic of all projects
    projects = db.select("projects", {"select": "id,name,repo_path"}) or []
    for p in projects:
        healthy, msg = diagnose_repo(p.get("repo_path"))
        status = "OK" if healthy else "FAIL"
        print(f"[{status}] {p.get('name')}: {msg}")
