#!/bin/bash
# Install git hooks from .githooks directory

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$REPO_ROOT" ]; then
    echo "ERROR: Not in a git repository"
    exit 1
fi

# Configure git to use .githooks directory
git config core.hooksPath .githooks

# Make all hooks executable
chmod +x "$REPO_ROOT/.githooks"/*

echo "✓ Git hooks installed successfully"
echo "  Hooks path: $(git config core.hooksPath)"
echo ""
echo "Installed hooks:"
ls -1 "$REPO_ROOT/.githooks" | grep -v "install.sh" | sed 's/^/  - /'
