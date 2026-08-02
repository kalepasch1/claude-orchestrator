"""Repository setup checker and dependency installer.

Verifies build/test/runtime dependencies are present and installs
any missing ones before proceeding with repairs.
"""

import os
import subprocess
import logging
from typing import Dict, List, Any, Optional

log = logging.getLogger(__name__)

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
        "has_git": os.path.isdir(os.path.join(repo_path, ".git")),
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
