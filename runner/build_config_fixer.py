"""Build configuration fixer.

Identifies and resolves common build/test failures by reviewing
source code, configuration, and test scripts.
"""

import os
import re
import logging
from typing import Dict, List, Any, Optional

log = logging.getLogger(__name__)


class BuildIssue:
    def __init__(self, category: str, file_path: str, description: str,
                 fix_available: bool = False):
        self.category = category
        self.file_path = file_path
        self.description = description
        self.fix_available = fix_available

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "file_path": self.file_path,
            "description": self.description,
            "fix_available": self.fix_available,
        }


def scan_python_syntax(repo_path: str, subdir: str = "runner") -> List[BuildIssue]:
    issues = []
    scan_dir = os.path.join(repo_path, subdir)
    if not os.path.isdir(scan_dir):
        return issues
    for root, _, files in os.walk(scan_dir):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r") as f:
                    source = f.read()
                compile(source, fpath, "exec")
            except SyntaxError as e:
                issues.append(BuildIssue(
                    "syntax_error", fpath,
                    f"Line {e.lineno}: {e.msg}",
                    fix_available=False,
                ))
    return issues


def scan_missing_imports(repo_path: str, subdir: str = "runner") -> List[BuildIssue]:
    issues = []
    scan_dir = os.path.join(repo_path, subdir)
    if not os.path.isdir(scan_dir):
        return issues
    for root, _, files in os.walk(scan_dir):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r") as f:
                    for i, line in enumerate(f, 1):
                        m = re.match(r"^from\s+(\S+)\s+import|^import\s+(\S+)", line)
                        if m:
                            mod = m.group(1) or m.group(2)
                            if mod.startswith("."):
                                # Relative import - check file exists
                                rel_path = mod.lstrip(".").replace(".", "/")
                                candidate = os.path.join(root, rel_path + ".py")
                                candidate_pkg = os.path.join(root, rel_path, "__init__.py")
                                if not os.path.exists(candidate) and not os.path.exists(candidate_pkg):
                                    issues.append(BuildIssue(
                                        "missing_import", fpath,
                                        f"Line {i}: relative import '{mod}' target not found",
                                        fix_available=False,
                                    ))
            except (OSError, UnicodeDecodeError):
                continue
    return issues


def scan_config_issues(repo_path: str) -> List[BuildIssue]:
    issues = []
    # Check for common config problems
    setup_cfg = os.path.join(repo_path, "setup.cfg")
    pyproject = os.path.join(repo_path, "pyproject.toml")

    if not os.path.exists(setup_cfg) and not os.path.exists(pyproject):
        issues.append(BuildIssue(
            "config_missing", repo_path,
            "No setup.cfg or pyproject.toml found",
            fix_available=True,
        ))

    return issues


def full_scan(repo_path: str) -> Dict[str, Any]:
    syntax = scan_python_syntax(repo_path)
    imports = scan_missing_imports(repo_path)
    config = scan_config_issues(repo_path)
    all_issues = syntax + imports + config
    return {
        "total_issues": len(all_issues),
        "syntax_errors": len(syntax),
        "missing_imports": len(imports),
        "config_issues": len(config),
        "issues": [i.to_dict() for i in all_issues],
        "green": len(all_issues) == 0,
    }
