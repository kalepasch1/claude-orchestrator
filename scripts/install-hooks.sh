#!/usr/bin/env bash
# Install git hooks for convention linting
# Run this once after cloning or when updating hooks

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
HOOKS_DIR="$PROJECT_ROOT/.git/hooks"

echo "Installing git hooks for convention linting..."

# Ensure hooks directory exists
mkdir -p "$HOOKS_DIR"

# Create pre-commit hook
cat > "$HOOKS_DIR/pre-commit" << 'EOF'
#!/usr/bin/env bash
# Pre-commit hook: convention linting

set -euo pipefail

# Get project root (walk up from hook location)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Skip if there are no staged changes
if git diff --cached --quiet; then
    exit 0
fi

# Run convention linter on staged Python files
echo "Running convention linter..."

# Collect staged Python files (filter for .py only)
STAGED_PY_FILES=$(git diff --cached --name-only --diff-filter=ACM | grep '\.py$' || true)

if [ -z "$STAGED_PY_FILES" ]; then
    exit 0
fi

# Check with non-blocking behavior by default (--fail-on=fail)
# To make warnings fail the commit, use --fail-on=warn
if ! python3 tools/convention_linter.py $STAGED_PY_FILES --fail-on=fail; then
    echo ""
    echo "❌ Convention linting failed. Fix violations or use: git commit --no-verify"
    exit 1
fi

echo "✓ Convention linting passed"
exit 0
EOF

chmod +x "$HOOKS_DIR/pre-commit"

echo "✓ Pre-commit hook installed at $HOOKS_DIR/pre-commit"

# Create prepare-commit-msg hook (if needed, for adding context)
# This is optional and can be enhanced later

echo "✓ Git hooks installation complete"
echo ""
echo "To test: git commit -m 'test' (will run convention linter on staged files)"
echo "To skip: git commit --no-verify"
