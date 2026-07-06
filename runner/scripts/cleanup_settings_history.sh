#!/bin/bash
##############################################################################
# cleanup_settings_history.sh - Remove machine-specific settings from git history
#
# SECURITY: This script removes .claude/settings.local.json from all git history.
# This file contains overly permissive allowlists and should NEVER be committed.
#
# CAUTION: This script rewrites git history. All collaborators must pull the
# new history and force-update their local branches after this runs.
#
# Usage: ./runner/scripts/cleanup_settings_history.sh
##############################################################################

set -e

REPO_ROOT=$(git rev-parse --show-toplevel)
echo "Repository root: $REPO_ROOT"

# Check if git-filter-repo is available; if not, provide installation instructions
if ! command -v git-filter-repo &> /dev/null; then
    echo "ERROR: git-filter-repo is not installed."
    echo ""
    echo "Install it with one of the following:"
    echo "  brew install git-filter-repo          (macOS)"
    echo "  apt-get install git-filter-repo        (Ubuntu/Debian)"
    echo "  pip install git-filter-repo            (pip)"
    echo ""
    echo "Alternatively, use git filter-branch:"
    echo "  git filter-branch --tree-filter 'rm -f .claude/settings.local.json' -- --all"
    echo ""
    exit 1
fi

# Verify that the file exists in history
OCCURRENCES=$(git log --all --full-history --name-only --pretty=format: | grep -c "\.claude/settings.local.json" || echo 0)
if [ "$OCCURRENCES" -eq 0 ]; then
    echo "✓ .claude/settings.local.json is not in git history. No cleanup needed."
    exit 0
fi

echo "Found .claude/settings.local.json in $OCCURRENCES commits."
echo ""
echo "⚠️  This will rewrite git history. All collaborators must force-pull after this runs."
echo "⚠️  Backup your current work or branches before proceeding."
read -p "Continue? (yes/no): " -r
if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
    echo "Aborted."
    exit 0
fi

echo "Removing .claude/settings.local.json from all branches..."
git filter-repo --path .claude/settings.local.json --invert-paths

echo ""
echo "✓ History cleaned successfully."
echo ""
echo "NEXT STEPS:"
echo "1. Verify cleanup: git log --all --full-history --name-only | grep settings.local"
echo "   (should return nothing)"
echo "2. Run tests: python -m pytest runner/tests/test_settings_hygiene.py"
echo "3. If all is well, force-push: git push --force --all"
echo "4. Inform all collaborators to re-clone or force-fetch the updated history"
echo ""
