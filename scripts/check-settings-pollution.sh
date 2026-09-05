#!/bin/bash
# check-settings-pollution.sh — CI/lint check to prevent .claude/settings.local.json pollution
# Fails if settings.local.json contains non-whitelisted permission entries
# Whitelisted entries: basic tool permissions (Edit, Write, Read, Bash, etc.) and deny rules
set -euo pipefail

SETTINGS_FILE=".claude/settings.local.json"

# ── Guard 0: the file must not be COMMITTED, whatever it contains ──────────────
#
# The content whitelist below only ever inspected the working copy. The failure that
# actually blocks merges is different and simpler: the file gets `git add -f`-ed and
# arrives in a PR carrying /Users/kpasch and /Users/mandypasch paths. It is in
# .gitignore, so this only happens by force — and a reviewer catching it by eye is what
# shelved rework-secret-merge-train-serializer seven times over.
#
# Checked first because it is unconditional: a tracked or staged settings.local.json is
# wrong even if every permission entry in it is pristine.
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  # STAGED is checked first because `git ls-files` also reports a staged-but-never-
  # committed file as tracked, and "git restore --staged" is the instruction that fits
  # the case an author is actually in when the hook stops them.
  if git diff --cached --name-only 2>/dev/null | grep -qx "$SETTINGS_FILE"; then
    echo "ERROR: $SETTINGS_FILE is STAGED. It is machine-local and must not be committed."
    echo "Fix with:  git restore --staged $SETTINGS_FILE"
    exit 1
  fi
  if git ls-files --error-unmatch "$SETTINGS_FILE" >/dev/null 2>&1; then
    echo "ERROR: $SETTINGS_FILE is TRACKED by git. It is machine-local and .gitignored."
    echo "Fix with:  git rm --cached $SETTINGS_FILE"
    exit 1
  fi
fi

if [[ ! -f "$SETTINGS_FILE" ]]; then
  echo "OK: $SETTINGS_FILE does not exist (clean)"
  exit 0
fi

# jq drives the content checks below. Without it every `jq` call returns empty and the
# script reports OK on a polluted file — a checker that passes because its dependency is
# missing is worse than no checker.
if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq is required to inspect $SETTINGS_FILE (install: brew install jq)"
  exit 1
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
