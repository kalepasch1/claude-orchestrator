#!/bin/bash
# Fix the security regression: remove .claude/settings.local.json from git tracking.
# This file contains machine-specific, overly permissive allowlists and should never
# be in git history. It is in .gitignore, but was accidentally committed.

set -e

echo "Removing .claude/settings.local.json from git tracking..."
git rm --cached .claude/settings.local.json

echo "Verifying the file is no longer tracked..."
if git ls-files .claude/settings.local.json | grep -q .; then
    echo "ERROR: File is still tracked!"
    exit 1
else
    echo "SUCCESS: File is no longer tracked."
fi

echo ""
echo "Next step: commit this change with:"
echo "  git add runner/tests/test_settings_hygiene.py"
echo "  git commit -m 'fix: remove settings.local.json from git tracking, add hygiene test'"
