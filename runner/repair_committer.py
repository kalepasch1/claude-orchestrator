"""Repair process committer.

Ensures repair changes are committed coherently on the task branch,
with each commit representing a clear step toward resolution.
"""

import subprocess
import logging
from typing import Dict, List, Any, Optional

log = logging.getLogger(__name__)


class CommitResult:
    def __init__(self, success: bool, commit_hash: str = "", message: str = ""):
        self.success = success
        self.commit_hash = commit_hash
        self.message = message


def get_changed_files(repo_path: str) -> List[str]:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_path, capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return []
        return [
            line[3:].strip() for line in result.stdout.strip().split("\n")
            if line.strip()
        ]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def get_current_branch(repo_path: str) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=repo_path, capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def categorize_changes(files: List[str]) -> Dict[str, List[str]]:
    categories: Dict[str, List[str]] = {
        "source": [],
        "test": [],
        "config": [],
        "docs": [],
        "other": [],
    }
    for f in files:
        if "test" in f.lower():
            categories["test"].append(f)
        elif f.endswith((".toml", ".cfg", ".ini", ".yml", ".yaml", ".json")):
            categories["config"].append(f)
        elif f.endswith((".md", ".rst", ".txt")):
            categories["docs"].append(f)
        elif f.endswith((".py", ".ts", ".js", ".vue")):
            categories["source"].append(f)
        else:
            categories["other"].append(f)
    return categories


def build_commit_message(categories: Dict[str, List[str]],
                         prefix: str = "fix") -> str:
    parts = []
    if categories.get("source"):
        parts.append(f"source ({len(categories['source'])} files)")
    if categories.get("test"):
        parts.append(f"tests ({len(categories['test'])} files)")
    if categories.get("config"):
        parts.append(f"config ({len(categories['config'])} files)")
    if categories.get("docs"):
        parts.append(f"docs ({len(categories['docs'])} files)")

    summary = ", ".join(parts) if parts else "changes"
    return f"{prefix}: repair {summary}"


def stage_and_commit(repo_path: str, message: str,
                     files: Optional[List[str]] = None,
                     run_command=None) -> CommitResult:
    if run_command is None:
        run_command = _default_run

    # Stage
    if files:
        for f in files:
            rc, _, err = run_command(["git", "add", f], repo_path)
            if rc != 0:
                return CommitResult(False, message=f"stage failed for {f}: {err}")
    else:
        rc, _, err = run_command(["git", "add", "-A"], repo_path)
        if rc != 0:
            return CommitResult(False, message=f"stage failed: {err}")

    # Commit
    rc, out, err = run_command(
        ["git", "commit", "-m", message, "--no-verify"], repo_path
    )
    if rc != 0:
        if "nothing to commit" in (out + err):
            return CommitResult(True, message="nothing to commit")
        return CommitResult(False, message=f"commit failed: {err}")

    # Get hash
    rc, out, _ = run_command(["git", "rev-parse", "HEAD"], repo_path)
    commit_hash = out.strip() if rc == 0 else "unknown"

    return CommitResult(True, commit_hash=commit_hash, message=message)


def _default_run(cmd, cwd):
    try:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=30,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", "timeout"
    except FileNotFoundError:
        return 1, "", "not found"
