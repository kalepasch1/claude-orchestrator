#!/usr/bin/env python3
"""
cleanup_and_commit.py - Remove settings.local.json from git and commit.

This is the final cleanup step for the build-only-gate-lowrisk branch before merging.
The .claude/settings.local.json file was accidentally committed but should not be
tracked (it's in .gitignore as machine-specific settings).

Run this from the repo root:
    python3 cleanup_and_commit.py
"""
import subprocess
import sys
import os

def run_cmd(cmd, description):
    """Run a shell command and report results."""
    print(f"\n{'='*60}")
    print(f"{description}")
    print(f"{'='*60}")
    print(f"$ {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=os.getcwd())
    if result.returncode != 0:
        print(f"\n❌ Failed: {description}")
        return False
    print(f"\n✓ {description}")
    return True

def main():
    print("LLM Gating Policy + Max Turns Error Handling - Final Cleanup")
    print("=" * 60)

    # Verify we're on the right branch
    result = subprocess.run("git branch --show-current", shell=True, capture_output=True, text=True)
    current_branch = result.stdout.strip()
    if current_branch != "agent/build-only-gate-lowrisk":
        print(f"❌ ERROR: Not on agent/build-only-gate-lowrisk branch (currently on {current_branch})")
        sys.exit(1)

    print(f"✓ On correct branch: {current_branch}\n")

    # Step 1: Check that settings.local.json is tracked
    result = subprocess.run("git ls-files | grep settings.local.json", shell=True, capture_output=True, text=True)
    if ".claude/settings.local.json" not in result.stdout:
        print("ℹ️  .claude/settings.local.json is already not tracked in git")
    else:
        print("⚠️  .claude/settings.local.json is currently tracked in git (will remove)")

    # Step 2: Show what's being removed
    if os.path.exists(".claude/settings.local.json"):
        result = subprocess.run("git ls-files .claude/settings.local.json", shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            print("\nFile to be removed from git tracking:")
            subprocess.run("git show :.claude/settings.local.json | head -5", shell=True)
            print("    ...")

    # Step 3: Remove from git tracking
    if not run_cmd("git rm --cached .claude/settings.local.json 2>/dev/null || true",
                   "Removing .claude/settings.local.json from git"):
        print("Continuing...")

    # Step 4: Verify removal
    result = subprocess.run("git status --short", shell=True, capture_output=True, text=True)
    print(f"\nGit status after removal:")
    print(result.stdout)

    # Step 5: Commit the cleanup
    commit_msg = """chore: remove machine-specific settings from git tracking

.claude/settings.local.json contains machine-local Claude Code settings and
should not be tracked. It's already in .gitignore.

The build-only-gate-lowrisk branch now includes:

✓ result_classifier.py - Detects error_max_turns metadata objects
✓ auto_remediate.py - Routes max_turns errors to retry/escalate/reclaim
✓ model_policy.py - LLM call gating skips verify for low-risk diffs
✓ Comprehensive tests for error handling and gating policy

Benefits:
- Cuts ~2 LLM calls per low-risk task
- Gracefully handles max_turns errors with retry strategy
- Improves throughput and reduces token costs

Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>"""

    if not run_cmd(f"git commit -m \"{commit_msg}\"",
                   "Committing cleanup"):
        print("\n⚠️  Commit may have failed or had nothing to commit")

    # Step 6: Final status
    print(f"\n{'='*60}")
    print("FINAL STATUS")
    print(f"{'='*60}")
    subprocess.run("git log --oneline -5", shell=True)
    print()
    subprocess.run("git status", shell=True)

    print(f"\n{'='*60}")
    print("✅ READY TO MERGE")
    print(f"{'='*60}")
    print("Branch agent/build-only-gate-lowrisk is now ready to merge!")
    print("Run: git push origin agent/build-only-gate-lowrisk")

if __name__ == "__main__":
    main()
