#!/usr/bin/env python
"""
Apply the security fix to remove settings.local.json from git tracking.

This script:
1. Verifies .gitignore is configured correctly
2. Removes .claude/settings.local.json from git tracking (but keeps the local file)
3. Stages the new test and documentation files
4. Creates a commit with proper message

Run with: python apply_security_fix.py
"""
import subprocess
import os
import sys


def run_cmd(cmd, description):
    """Run a command and report results."""
    print(f"  {description}...")
    result = subprocess.run(
        cmd,
        shell=isinstance(cmd, str),
        cwd=os.getcwd(),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"    ✗ FAILED: {result.stderr}")
        return False
    print(f"    ✓ Done")
    return True


def main():
    """Apply the security fix."""
    print()
    print("═══════════════════════════════════════════════════════════════════")
    print("  Security Fix: Remove settings.local.json from Git Tracking")
    print("═══════════════════════════════════════════════════════════════════")
    print()

    # Step 1: Verify configuration
    print("[1/4] Verifying .gitignore configuration...")
    with open(".gitignore") as f:
        gitignore_content = f.read()
    if ".claude/settings.local.json" in gitignore_content:
        print("  ✓ .claude/settings.local.json is in .gitignore")
    else:
        print("  ✗ ERROR: .claude/settings.local.json is NOT in .gitignore")
        return False
    print()

    # Step 2: Check tracking status
    print("[2/4] Checking git tracking status...")
    result = subprocess.run(
        ["git", "ls-files", ".claude/settings.local.json"],
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        print("  ! File is currently tracked in git (this is the issue we're fixing)")
    else:
        print("  ✓ File is already not tracked (fix already applied?)")
        return True
    print()

    # Step 3: Stage and remove
    print("[3/4] Staging fixes and removing tracked file...")
    files_to_add = [
        "runner/tests/test_settings_hygiene.py",
        "SECURITY_FIX_SETTINGS.md",
        "fix_settings_tracking.sh",
        "APPLY_SECURITY_FIX.sh",
        "apply_security_fix.py",
    ]

    for f in files_to_add:
        if not run_cmd(["git", "add", f], f"Adding {f}"):
            return False

    if not run_cmd(
        ["git", "rm", "--cached", ".claude/settings.local.json"],
        "Removing .claude/settings.local.json from git index",
    ):
        return False
    print()

    # Step 4: Commit
    print("[4/4] Creating commit...")
    commit_msg = """fix: remove settings.local.json from git tracking, add hygiene test

- Remove .claude/settings.local.json from git index (remains in .gitignore)
- Add test_settings_hygiene.py to prevent regression
- Add SECURITY_FIX_SETTINGS.md documentation
- Add fix_settings_tracking.sh and apply_security_fix.py helper scripts

Security: Settings files containing allowlists and credentials should never
be in git history. This machine-specific config was accidentally committed.
The hygiene test will now catch any future attempts to commit these files.

Fixes: Security regression where .claude/settings.local.json (with overly
permissive Bash/Read allowlists and database access) was in git history."""

    if not run_cmd(
        ["git", "commit", "-m", commit_msg],
        "Creating commit",
    ):
        return False
    print()

    # Summary
    print("═══════════════════════════════════════════════════════════════════")
    print("  ✓ Security fix applied successfully!")
    print("═══════════════════════════════════════════════════════════════════")
    print()

    # Verify
    print("Verification:")
    subprocess.run(["git", "log", "--oneline", "-1"])
    print()
    print("The following test will prevent this regression in the future:")
    print("  runner/tests/test_settings_hygiene.py")
    print()

    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
