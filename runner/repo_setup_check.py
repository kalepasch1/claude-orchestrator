"""Repository setup checker and dependency installer.

Verifies build/test/runtime dependencies are present and installs
any missing ones before proceeding with repairs.
"""

import os
import subprocess
import logging
from typing import Dict, List, Any, Optional

log = logging.getLogger(__name__)

GIT_TIMEOUT = int(os.environ.get("ORCH_REPO_SETUP_GIT_TIMEOUT", "30"))

REQUIRED_TOOLS = {
    "python3": "python3 --version",
    "pip": "pip3 --version",
    "git": "git --version",
    "pytest": "python3 -m pytest --version",
}

OPTIONAL_TOOLS = {
    "node": "node --version",
    "npm": "npm --version",
    "npx": "npx --version",
}


class SetupCheckResult:
    def __init__(self):
        self.available: Dict[str, str] = {}
        self.missing: List[str] = []
        self.installed: List[str] = []
        self.errors: List[str] = []

    @property
    def ok(self) -> bool:
        return len(self.missing) == 0 and len(self.errors) == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "available": self.available,
            "missing": self.missing,
            "installed": self.installed,
            "errors": self.errors,
        }


def _run_check(cmd: str) -> Optional[str]:
    try:
        result = subprocess.run(
            cmd.split(), capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip().split("\n")[0]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def check_tools(tools: Dict[str, str]) -> Dict[str, Optional[str]]:
    results = {}
    for name, cmd in tools.items():
        results[name] = _run_check(cmd)
    return results


def check_repo_structure(repo_path: str) -> Dict[str, bool]:
    checks = {
        # .git is a directory in a normal checkout but a gitdir pointer *file* in
        # linked worktrees ({repo}-wt/{slug}), where all agent work runs.
        "has_git": os.path.exists(os.path.join(repo_path, ".git")),
        "has_runner": os.path.isdir(os.path.join(repo_path, "runner")),
        "has_tests": os.path.isdir(os.path.join(repo_path, "runner", "tests")),
        "has_requirements": os.path.isfile(os.path.join(repo_path, "requirements.txt")),
    }
    return checks


def verify_repo_setup(repo_path: str) -> SetupCheckResult:
    result = SetupCheckResult()

    # Check required tools
    tool_results = check_tools(REQUIRED_TOOLS)
    for name, version in tool_results.items():
        if version:
            result.available[name] = version
        else:
            result.missing.append(name)

    # Check optional tools
    opt_results = check_tools(OPTIONAL_TOOLS)
    for name, version in opt_results.items():
        if version:
            result.available[name] = version

    # Check repo structure
    structure = check_repo_structure(repo_path)
    for check_name, passed in structure.items():
        if not passed:
            result.errors.append(f"repo structure check failed: {check_name}")

    return result


def _git(args: List[str], cwd: str, timeout: int = GIT_TIMEOUT):
    """Run a git command, return (stdout, stderr, returncode). Never raises."""
    try:
        r = subprocess.run(
            ["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except FileNotFoundError:
        return "", "git not found", 127
    except Exception as e:
        return "", str(e), 1


def detect_default_branch(repo_path: str, remote: str = "origin") -> str:
    """Best-effort default branch for a repo: remote HEAD, then main/develop,
    then whatever is currently checked out. Returns "" if undeterminable."""
    out, _, rc = _git(["symbolic-ref", "--short", f"refs/remotes/{remote}/HEAD"], repo_path)
    if rc == 0 and out:
        return out.split("/", 1)[-1]
    for candidate in ("main", "develop"):
        for ref in (f"refs/remotes/{remote}/{candidate}", f"refs/heads/{candidate}"):
            _, _, rc = _git(["rev-parse", "--verify", "--quiet", ref], repo_path)
            if rc == 0:
                return candidate
    out, _, rc = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo_path)
    return out if rc == 0 else ""


def check_repo_ready(repo_path: str, remote: str = "origin") -> Dict[str, Any]:
    """Fail-soft local-repo readiness check.

    Returns a dict with:
      exists         - path is a valid git work tree
      clean          - no uncommitted changes
      current        - default branch is not behind its remote-tracking ref
                       (True when there is no remote to be behind)
      default_branch - detected default branch name ("" if unknown)
      ready          - exists and clean and current
      error          - "" or first blocking problem

    Never raises, including on None/missing paths.
    """
    result: Dict[str, Any] = {
        "exists": False, "clean": False, "current": False,
        "default_branch": "", "ready": False, "error": "",
    }
    try:
        if not repo_path or not os.path.isdir(repo_path):
            result["error"] = f"repo path does not exist: {repo_path}"
            return result
        _, err, rc = _git(["rev-parse", "--is-inside-work-tree"], repo_path)
        if rc != 0:
            result["error"] = f"not a git repository: {err}"
            return result
        result["exists"] = True

        out, err, rc = _git(["status", "--porcelain"], repo_path)
        if rc != 0:
            result["error"] = f"git status failed: {err}"
            return result
        result["clean"] = not out

        branch = detect_default_branch(repo_path, remote)
        result["default_branch"] = branch

        result["current"] = True
        if branch:
            _, _, rc = _git(
                ["rev-parse", "--verify", "--quiet", f"refs/remotes/{remote}/{branch}"],
                repo_path,
            )
            if rc == 0:
                out, _, rc = _git(
                    ["rev-list", "--count", f"{branch}..{remote}/{branch}"], repo_path
                )
                if rc == 0 and out.isdigit() and int(out) > 0:
                    result["current"] = False

        result["ready"] = result["exists"] and result["clean"] and result["current"]
    except Exception as e:
        result["error"] = str(e)
    return result


def install_python_deps(repo_path: str, requirements_file: str = "requirements.txt") -> bool:
    req_path = os.path.join(repo_path, requirements_file)
    if not os.path.isfile(req_path):
        return True  # No requirements = nothing to install
    try:
        result = subprocess.run(
            ["pip3", "install", "-r", req_path, "--quiet"],
            capture_output=True, text=True, timeout=120,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
