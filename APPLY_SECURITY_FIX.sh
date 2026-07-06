#!/bin/bash
# APPLY_SECURITY_FIX.sh
#
# This script applies the complete security fix for the settings.local.json regression.
# Run this to remove the machine-specific config file from git tracking and commit all fixes.

set -e

REPO_ROOT=$(git rev-parse --show-toplevel)
cd "$REPO_ROOT"

echo "═══════════════════════════════════════════════════════════════════"
echo "  Security Fix: Remove settings.local.json from Git Tracking"
echo "═══════════════════════════════════════════════════════════════════"
echo ""

# Step 1: Verify .gitignore has the entry
echo "[1/4] Verifying .gitignore configuration..."
if grep -q ".claude/settings.local.json" "$REPO_ROOT/.gitignore"; then
    echo "  ✓ .claude/settings.local.json is in .gitignore"
else
    echo "  ✗ ERROR: .claude/settings.local.json is NOT in .gitignore"
    exit 1
fi
echo ""

# Step 2: Check if file is currently tracked
echo "[2/4] Checking git tracking status..."
if git ls-files | grep -q "\.claude/settings.local.json"; then
    echo "  ! File is currently tracked in git (this is the issue we're fixing)"
else
    echo "  ✓ File is already not tracked (nothing to do)"
    exit 0
fi
echo ""

# Step 3: Stage new files and remove tracking
echo "[3/4] Staging fixes and removing tracked file..."
git add runner/tests/test_settings_hygiene.py SECURITY_FIX_SETTINGS.md fix_settings_tracking.sh
git rm --cached .claude/settings.local.json
echo "  ✓ Staged: test_settings_hygiene.py, SECURITY_FIX_SETTINGS.md, fix_settings_tracking.sh"
echo "  ✓ Removed: .claude/settings.local.json from git index"
echo ""

# Step 4: Commit
echo "[4/4] Creating commit..."
git commit -m "fix: remove settings.local.json from git tracking, add hygiene test

- Remove .claude/settings.local.json from git index (remains in .gitignore)
- Add test_settings_hygiene.py to prevent regression
- Add SECURITY_FIX_SETTINGS.md documentation
- Add fix_settings_tracking.sh helper script

Security: Settings files containing allowlists and credentials should never
be in git history. This machine-specific config was accidentally committed.
The hygiene test will now catch any future attempts to commit these files.

Fixes: Security regression where .claude/settings.local.json (with overly
permissive Bash/Read allowlists and database access) was in git history."

echo ""
echo "═══════════════════════════════════════════════════════════════════"
echo "  ✓ Security fix applied successfully!"
echo "═══════════════════════════════════════════════════════════════════"
echo ""
echo "Verification:"
git log --oneline -1
echo ""
echo "The following test will prevent this regression in the future:"
echo "  runner/tests/test_settings_hygiene.py"
echo ""
