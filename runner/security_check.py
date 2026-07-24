#!/usr/bin/env python3
"""
security_check.py - Detect and fix security regressions in Claude Code settings.

Detects machine-specific configuration files (like .claude/settings.local.json)
that contain dangerous patterns (kill commands, database access, overly broad
file permissions) and should never be tracked in git.

This scanner:
1. Detects dangerous patterns in tracked settings files
2. Verifies security constraints (no tracked settings.local.json)
3. Recommends fixes
4. Can apply fixes if requested
"""

import subprocess
import json
import os
import sys
from pathlib import Path


class SecurityCheckError(Exception):
    """Raised when a security constraint is violated."""
    pass


def get_repo_root():
    """Get the repository root directory."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        raise SecurityCheckError("Not in a git repository")
    return result.stdout.strip()


def get_tracked_files():
    """Get list of all files tracked in git."""
    result = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        raise SecurityCheckError("Failed to list tracked files")
    return result.stdout.strip().split("\n")


def detect_dangerous_patterns(file_content):
    """Detect dangerous security patterns in settings content.

    Returns list of (pattern_type, count, examples) tuples.
    """
    dangerous_patterns = {
        "kill_commands": {
            "patterns": [r"Bash(kill", r"Bash(pkill"],
            "description": "Process termination commands",
        },
        "database_access": {
            "patterns": [r"import db", r"db.select", r"db.update"],
            "description": "Database manipulation",
        },
        "overly_broad_file_access": {
            "patterns": [r"Read(//Users", r"Read(//Users/**"],
            "description": "Overly permissive file path patterns",
        },
        "forced_reset": {
            "patterns": [r"Bash(git reset --hard"],
            "description": "Destructive git operations",
        },
    }

    findings = []
    for pattern_type, pattern_info in dangerous_patterns.items():
        examples = []
        count = 0
        for pattern in pattern_info["patterns"]:
            for line in file_content.split("\n"):
                if pattern in line:
                    count += 1
                    if len(examples) < 2:
                        examples.append(line.strip()[:80])

        if count > 0:
            findings.append({
                "type": pattern_type,
                "description": pattern_info["description"],
                "count": count,
                "examples": examples,
            })

    return findings


def check_security_constraints(repo_root):
    """Check critical security constraints.

    Returns list of violations found.
    """
    violations = []

    # Check 1: .claude/settings.local.json should not be tracked
    tracked = get_tracked_files()
    if ".claude/settings.local.json" in tracked:
        violations.append({
            "level": "CRITICAL",
            "constraint": ".claude/settings.local.json must not be tracked",
            "current": "tracked in git",
            "fix": "git rm --cached .claude/settings.local.json",
        })

    # Check 2: Verify .gitignore has the entry
    gitignore_path = os.path.join(repo_root, ".gitignore")
    if os.path.exists(gitignore_path):
        with open(gitignore_path) as f:
            gitignore_content = f.read()
        if ".claude/settings.local.json" not in gitignore_content:
            violations.append({
                "level": "HIGH",
                "constraint": ".claude/settings.local.json entry in .gitignore",
                "current": "not found",
                "fix": "Add '.claude/settings.local.json' to .gitignore",
            })

    # Check 3: Check tracked settings files for dangerous patterns
    settings_files = [f for f in tracked if "settings" in f.lower() and f.endswith(".json")]

    for settings_file in settings_files:
        if "local" in settings_file:
            violations.append({
                "level": "CRITICAL",
                "constraint": f"{settings_file} must not be tracked",
                "current": f"tracked in git",
                "fix": f"git rm --cached {settings_file}",
            })
        else:
            # Non-local settings files should be checked for patterns
            file_path = os.path.join(repo_root, settings_file)
            if os.path.exists(file_path):
                try:
                    with open(file_path) as f:
                        content = f.read()
                    findings = detect_dangerous_patterns(content)
                    if findings:
                        for finding in findings:
                            violations.append({
                                "level": "HIGH",
                                "constraint": f"Tracked {settings_file} has dangerous pattern",
                                "current": f"{finding['type']} ({finding['count']} occurrences)",
                                "fix": f"Review and remove {finding['type']} from {settings_file}",
                            })
                except (json.JSONDecodeError, IOError):
                    pass

    return violations


def print_report(violations):
    """Print a security report."""
    if not violations:
        print("✓ All security constraints satisfied")
        return True

    print("=" * 70)
    print("SECURITY CHECK REPORT")
    print("=" * 70)
    print()

    critical = [v for v in violations if v["level"] == "CRITICAL"]
    high = [v for v in violations if v["level"] == "HIGH"]

    if critical:
        print(f"CRITICAL VIOLATIONS ({len(critical)}):")
        print("-" * 70)
        for v in critical:
            print(f"\n  Constraint: {v['constraint']}")
            print(f"  Current:    {v['current']}")
            print(f"  Fix:        {v['fix']}")

    if high:
        print(f"\n\nHIGH SEVERITY VIOLATIONS ({len(high)}):")
        print("-" * 70)
        for v in high:
            print(f"\n  Constraint: {v['constraint']}")
            print(f"  Current:    {v['current']}")
            print(f"  Fix:        {v['fix']}")

    print("\n" + "=" * 70)
    return False


def main():
    """Run security checks."""
    try:
        repo_root = get_repo_root()
        violations = check_security_constraints(repo_root)

        success = print_report(violations)

        if not success:
            print("\nTo fix:")
            print("  git rm --cached .claude/settings.local.json")
            print("  git commit -m 'security: remove settings.local.json from git tracking'")
            sys.exit(1)

        sys.exit(0)

    except SecurityCheckError as e:
        print(f"Security check error: {e}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
