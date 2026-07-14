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
# Inherited NODE_ENV=production makes npm omit devDependencies (broken installs/builds) — strip it.
unset NODE_ENV || true
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

# LOCK the worktree while a task is using it. Concurrent GC/prune loops (worktree_gc,
# resource_governor) must not delete an in-use worktree; `git worktree remove --force`
# refuses locked worktrees unless doubly forced. worktree_gc unlocks after its safety
# guards (task terminal + clean + aged) pass, so this never leaks disk.
git -C "$REPO_ROOT" worktree lock "$DEST" --reason "task ${SLUG} in use" 2>/dev/null || true

# Each worktree inherits .claude/settings.json from the repo automatically.
# copy the repo's permission allowlist into the worktree so agents CANNOT push / trigger CI
mkdir -p "$DEST/.claude"
[ -f "$REPO_ROOT/.claude/settings.local.json" ] && cp "$REPO_ROOT/.claude/settings.local.json" "$DEST/.claude/settings.local.json" || true

# WARM DEPS: the agent's build-to-green loop dominates wall-clock, and a fresh worktree would
# `npm install` from scratch every time (minutes). Symlink the main checkout's node_modules (and
# reuse the build cache) so `npm run build`/tests start instantly. Symlink = zero copy, zero disk.
# Disable with ORCH_WARM_DEPS=false. (npm/pnpm resolve a symlinked node_modules fine for builds.)
if [ "${ORCH_WARM_DEPS:-true}" = "true" ]; then
  for depdir in node_modules .next/cache .nuxt node_modules/.cache; do
    src="$REPO_ROOT/$depdir"; dst="$DEST/$depdir"
    if [ -e "$src" ] && [ ! -e "$dst" ]; then
      mkdir -p "$(dirname "$dst")"
      ln -s "$src" "$dst" 2>/dev/null || true
    fi
  done
fi
# NUXT TYPES: resource_governor prunes **/.nuxt from the main checkout as a "build cache",
# so the symlink above often points at nothing and `tsc --noEmit` fails with thousands of
# missing-alias errors (unrelated to the task's change). Regenerate the type stubs once,
# best-effort, so tsc-based acceptance checks can actually go green. Cheap (~seconds), and
# skipped when .nuxt already exists or this isn't a Nuxt project.
if [ "${ORCH_NUXT_PREPARE:-true}" = "true" ] && [ ! -e "$DEST/.nuxt" ] && [ -f "$DEST/package.json" ] \
   && grep -q '"nuxt"' "$DEST/package.json" 2>/dev/null; then
  (cd "$DEST" && timeout 180 npx nuxi prepare >/dev/null 2>&1) || true
fi

echo "✅ worktree ready: $DEST  (branch $BRANCH, based on $BASE)"
echo "   run an agent there with: scripts/orchestrate.sh"
