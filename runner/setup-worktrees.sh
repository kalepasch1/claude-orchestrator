#!/usr/bin/env bash
# setup-worktrees.sh - give every task its own isolated git worktree + branch.
# This is the FIX for your recurring merge conflicts: agents never edit the same
# working directory, so their file changes physically cannot collide. They only
# meet again at integration time, one at a time (see integrate.sh).
#
# Usage:
#   ./setup-worktrees.sh <task-slug> [base-branch]
# Example:
#   ./setup-worktrees.sh simplify-ui main
#
# Creates: ../<repo>-wt/<task-slug>  on branch  agent/<task-slug>

set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel)"
REPO_NAME="$(basename "$REPO_ROOT")"
WT_ROOT="$(dirname "$REPO_ROOT")/${REPO_NAME}-wt"

SLUG="${1:?usage: setup-worktrees.sh <task-slug> [base-branch]}"
BASE="${2:-main}"
BRANCH="agent/${SLUG}"
DEST="${WT_ROOT}/${SLUG}"
STAGING="${ORCH_STAGING_BRANCH:-orchestrator/dev}"

mkdir -p "$WT_ROOT"
git -C "$REPO_ROOT" fetch origin "$BASE" --quiet || true

# ZERO-CONFLICT MODEL: branch every agent off the CURRENT staging tip (which already contains all
# prior merged work), not a fixed base. New work stacks on what's already done, so merging back into
# staging is a clean fast-forward and merge conflicts stop being manufactured.
if git -C "$REPO_ROOT" show-ref --verify --quiet "refs/heads/${STAGING}"; then
  BASE="$STAGING"
fi

if git -C "$REPO_ROOT" show-ref --verify --quiet "refs/heads/${BRANCH}"; then
  git -C "$REPO_ROOT" worktree add "$DEST" "$BRANCH"
else
  git -C "$REPO_ROOT" worktree add "$DEST" -b "$BRANCH" "$BASE"
fi

# Each worktree inherits .claude/settings.json from the repo automatically.
# copy the repo's permission allowlist into the worktree so agents CANNOT push / trigger CI
mkdir -p "$DEST/.claude"
[ -f "$REPO_ROOT/.claude/settings.local.json" ] && cp "$REPO_ROOT/.claude/settings.local.json" "$DEST/.claude/settings.local.json" || true
echo "✅ worktree ready: $DEST  (branch $BRANCH, based on $BASE)"
echo "   run an agent there with: scripts/orchestrate.sh"
