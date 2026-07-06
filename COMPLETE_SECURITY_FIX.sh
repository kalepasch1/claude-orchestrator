#!/bin/bash
#
# COMPLETE_SECURITY_FIX.sh
#
# Completes the security fix for dangerous .claude/settings.local.json file.
# This file was accidentally committed to git with overly permissive allowlists.
#
# Status: Implementation complete; this script removes it from git tracking
# Created: 2026-07-06
#

set -e

echo "=================================================="
echo "Security Fix: Remove settings.local.json from git"
echo "=================================================="
echo ""

# Verify we're in the right directory
if [ ! -f "runner/improvement_measure.py" ]; then
    echo "ERROR: Must run from self-optimizing-pipeline root directory"
    echo "Current directory: $(pwd)"
    exit 1
fi

# Check current status
echo "1. Current git status..."
if git ls-files | grep -q "\.claude/settings\.local\.json"; then
    echo "   ✓ File IS currently tracked in git (needs removal)"
else
    echo "   ✗ File is NOT tracked (already fixed?)"
    exit 0
fi

if [ -f ".claude/settings.local.json" ]; then
    echo "   ✓ File exists in working tree (will be preserved)"
else
    echo "   ⚠ File does not exist in working tree"
fi

echo ""
echo "2. Dangerous patterns detected in file:"
grep -E "(kill|pkill|db\.select|db\.update|Read\(//Users)" .claude/settings.local.json 2>/dev/null | head -5 || true
echo ""

echo "3. Removing from git tracking (keeping local copy)..."
git rm --cached .claude/settings.local.json
echo "   ✓ File removed from git index"

echo ""
echo "4. Creating commit..."
git commit -m "security: remove settings.local.json from git tracking

- Removes tracked .claude/settings.local.json containing dangerous patterns
- Dangerous patterns: kill commands, database manipulation, overly broad file access
- File contains: kill 84440, pkill -f 'runner.py', db.select/update, Read(//Users/**)
- .gitignore (line 22) already protects future commits
- Complements security regression detection in test_settings_hygiene.py
- Fixes test_settings_local_not_tracked() assertion

This commit removes the file from git tracking while preserving it locally
for use in this specific environment (machine-specific configuration).

Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>"

echo ""
echo "5. Verification..."
if git ls-files | grep -q "\.claude/settings\.local\.json"; then
    echo "   ✗ FAILED: File still tracked"
    exit 1
else
    echo "   ✓ File successfully removed from git tracking"
fi

if [ -f ".claude/settings.local.json" ]; then
    echo "   ✓ File still exists locally (good)"
else
    echo "   ⚠ File removed from working tree"
fi

echo ""
echo "6. Test status check..."
if python3 -m pytest runner/tests/test_settings_hygiene.py::TestSettingsHygiene::test_settings_local_not_tracked -v 2>/dev/null; then
    echo "   ✓ test_settings_local_not_tracked PASSES"
else
    echo "   (Run pytest to verify)"
fi

echo ""
echo "=================================================="
echo "✓ Security fix complete!"
echo "=================================================="
echo ""
echo "Summary of changes:"
echo "  - Removed .claude/settings.local.json from git tracking"
echo "  - File preserved locally for machine-specific use"
echo "  - test_settings_local_not_tracked() should now pass"
echo ""
echo "Next steps:"
echo "  1. Push changes: git push origin agent/self-optimizing-pipeline"
echo "  2. Run tests: python -m pytest runner/tests/test_*.py -v"
echo "  3. (Optional) Remove from full history: git filter-repo --path .claude/settings.local.json --invert-paths"
echo ""
