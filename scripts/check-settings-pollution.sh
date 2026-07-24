#!/bin/bash
# check-settings-pollution.sh — CI/lint check to prevent .claude/settings.local.json pollution
# Fails if settings.local.json contains non-whitelisted permission entries
# Whitelisted entries: basic tool permissions (Edit, Write, Read, Bash, etc.) and deny rules
set -euo pipefail

SETTINGS_FILE=".claude/settings.local.json"

if [[ ! -f "$SETTINGS_FILE" ]]; then
  echo "OK: $SETTINGS_FILE does not exist (clean)"
  exit 0
fi

# Whitelist of allowed permission entries
WHITELIST=(
  "Edit"
  "Write"
  "Read"
  "Grep"
  "Glob"
  "Bash"
  "WebFetch"
  "WebSearch"
  "Agent"
  "Artifact"
  "Skill"
)

# Extract the allow array from settings.local.json
ALLOW_ENTRIES=$(jq -r '.permissions.allow[]?' "$SETTINGS_FILE" 2>/dev/null || echo "")

# Check for hardcoded paths or suspicious patterns
PROBLEMS=0

# Pattern 1: Hardcoded user paths
if echo "$ALLOW_ENTRIES" | grep -E '(/Users/kpasch|/Users/mandypasch|/private/tmp)' >/dev/null 2>&1; then
  echo "ERROR: Found hardcoded user paths in permissions:"
  echo "$ALLOW_ENTRIES" | grep -E '(/Users/kpasch|/Users/mandypasch|/private/tmp)' | head -5
  PROBLEMS=$((PROBLEMS + 1))
fi

# Pattern 2: Process kill commands
if echo "$ALLOW_ENTRIES" | grep -E '(kill|pkill|killall)' >/dev/null 2>&1; then
  echo "ERROR: Found process kill commands in permissions:"
  echo "$ALLOW_ENTRIES" | grep -E '(kill|pkill|killall)' | head -5
  PROBLEMS=$((PROBLEMS + 1))
fi

# Pattern 3: Suspicious Bash permissions (those with specific commands)
# Whitelist only bare "Bash" without parens
if echo "$ALLOW_ENTRIES" | grep -E '^Bash\(' >/dev/null 2>&1; then
  COUNT=$(echo "$ALLOW_ENTRIES" | grep -c '^Bash(' || echo 0)
  echo "ERROR: Found $COUNT specific Bash command permission(s):"
  echo "$ALLOW_ENTRIES" | grep '^Bash(' | head -5
  PROBLEMS=$((PROBLEMS + 1))
fi

# Pattern 4: Read permissions with wildcards to user directories
if echo "$ALLOW_ENTRIES" | grep -E '^Read\(.*(/Users|/private)' >/dev/null 2>&1; then
  echo "ERROR: Found Read permissions targeting user directories:"
  echo "$ALLOW_ENTRIES" | grep -E '^Read\(.*(/Users|/private)' | head -5
  PROBLEMS=$((PROBLEMS + 1))
fi

# Pattern 5: Too many allowed entries (more than ~20 whitelisted tools is suspicious)
BASIC_TOOL_COUNT=$(echo "$ALLOW_ENTRIES" | grep -E '^(Edit|Write|Read|Grep|Glob|Bash|WebFetch|WebSearch|Agent|Artifact|Skill)$' | wc -l)
TOTAL_ENTRIES=$(echo "$ALLOW_ENTRIES" | wc -l)
if [[ $TOTAL_ENTRIES -gt $((BASIC_TOOL_COUNT + 5)) ]]; then
  echo "ERROR: Found extra permission entries beyond basic tools (total: $TOTAL_ENTRIES, basic: $BASIC_TOOL_COUNT):"
  echo "$ALLOW_ENTRIES" | grep -v -E '^(Edit|Write|Read|Grep|Glob|Bash|WebFetch|WebSearch|Agent|Artifact|Skill)$' | head -10
  PROBLEMS=$((PROBLEMS + 1))
fi

if [[ $PROBLEMS -gt 0 ]]; then
  echo ""
  echo "FAILED: $SETTINGS_FILE has $PROBLEMS pollution issue(s)"
  echo "Fix by:"
  echo "  1. Remove hardcoded paths and specific Bash commands"
  echo "  2. Keep only basic tool permissions (Edit, Write, Read, Bash, etc.)"
  echo "  3. Keep deny rules for safety (git push --force, rm -rf, sudo, etc.)"
  echo "  4. If you need a local override, add it to .claude/settings.local.json manually"
  echo "     and document it in CONTRIBUTING.md"
  exit 1
fi

echo "OK: $SETTINGS_FILE is clean (no pollution detected)"
exit 0
