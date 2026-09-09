#!/usr/bin/env bash
# setup-worktrees.sh - give every task its own isolated git worktree + branch.
# This is the FIX for your recurring merge conflicts: agents never edit the same
# working directory, so their file changes physically cannot collide. They only
# meet again at integration time, one at a time (see integrate.sh).
#
# Usage:
#   ./setup-worktrees.sh <task-slug> [base-branch] <task-id> <lease-token>
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
TASK_ID="${3:-}"
LEASE_TOKEN="${4:-}"
BRANCH="agent/${SLUG}"
DEST="${WT_ROOT}/${SLUG}"
STAGING="${ORCH_STAGING_BRANCH:-orchestrator/dev}"
OWNER_ROOT="${WT_ROOT}/.orchestrator-owners"
OWNER_FILE="${OWNER_ROOT}/${SLUG}"

if [ -z "$TASK_ID" ] || [ -z "$LEASE_TOKEN" ]; then
  echo "branch lease required for ${BRANCH}" >&2
  exit 73
fi

mkdir -p "$WT_ROOT" "$OWNER_ROOT"
git -C "$REPO_ROOT" fetch origin "$BASE" --quiet || true

# A live directory may only be reused by the exact task+lease that created it.
# Never delete, reset, or force-adopt an unknown worktree: it may contain another
# executor's uncommitted code.
if [ -e "$DEST" ]; then
  if [ -f "$OWNER_FILE" ] && [ "$(sed -n '1p' "$OWNER_FILE")" = "$TASK_ID" ] \
     && [ "$(sed -n '2p' "$OWNER_FILE")" = "$LEASE_TOKEN" ]; then
    echo "✅ worktree already owned: $DEST"
    exit 0
  fi
  echo "refusing to overwrite worktree owned by another task: $DEST" >&2
  exit 74
fi

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

printf '%s\n%s\n%s\n' "$TASK_ID" "$LEASE_TOKEN" "$BRANCH" > "$OWNER_FILE"

# LOCK the worktree while a task is using it. Concurrent GC/prune loops (worktree_gc,
# resource_governor) must not delete an in-use worktree; `git worktree remove --force`
# refuses locked worktrees unless doubly forced. worktree_gc unlocks after its safety
# guards (task terminal + clean + aged) pass, so this never leaks disk.
git -C "$REPO_ROOT" worktree lock "$DEST" --reason "task ${SLUG} in use" 2>/dev/null || true

# Each worktree inherits .claude/settings.json from the repo automatically.
# copy the repo's permission allowlist into the worktree so agents CANNOT push / trigger CI
mkdir -p "$DEST/.claude"
[ -f "$REPO_ROOT/.claude/settings.local.json" ] && cp "$REPO_ROOT/.claude/settings.local.json" "$DEST/.claude/settings.local.json" || true

# PORTABLE TIMEOUT: coreutils `timeout` is NOT present on a stock macOS box (it ships as
# `gtimeout` only if someone `brew install coreutils`). Every call site below used to be
# `timeout N ... || true`, so on macOS the command failed instantly with
# "command not found" and the `|| true` swallowed it — the step silently never ran.
# Prefer timeout/gtimeout when present, otherwise run with a watchdog kill.
# ORCH_TIMEOUT_FORCE_FALLBACK=1 exercises the watchdog path on a host that does have
# coreutils; it exists so the fallback is actually covered by tests rather than only
# running on machines nobody tests on.
orch_timeout() {
  _secs="$1"; shift
  if [ "${ORCH_TIMEOUT_FORCE_FALLBACK:-0}" != "1" ]; then
    if command -v timeout  >/dev/null 2>&1; then timeout  "$_secs" "$@"; return $?; fi
    if command -v gtimeout >/dev/null 2>&1; then gtimeout "$_secs" "$@"; return $?; fi
  fi
  "$@" &
  _cmd_pid=$!
  # Watchdog. `sleep` is POSIX and present on every Unix (unlike GNU `timeout`), so it
  # is a safe dependency here. It is still guarded: if sleep is somehow unavailable it
  # returns immediately, and killing the guarded command on that basis would be far
  # worse than not enforcing the bound — these call sites are all best-effort prep.
  # So the watchdog only fires when sleep actually completed the full delay.
  ( if sleep "$_secs" 2>/dev/null; then kill -TERM "$_cmd_pid" 2>/dev/null || true; fi ) &
  _watchdog_pid=$!
  # `set -e` must not abort on a non-zero exit we are deliberately capturing.
  _rc=0; wait "$_cmd_pid" 2>/dev/null || _rc=$?
  kill -TERM "$_watchdog_pid" 2>/dev/null || true
  wait "$_watchdog_pid" 2>/dev/null || true
  return $_rc
}

# REPO-NATIVE PREP FIRST: some repos ship their own worktree provisioning script that knows
# exactly which generated dirs must be linked vs. regenerated (e.g. tomorrow's
# `npm run prepare:worktree` links node_modules AND .nuxt). When a repo declares one, it is
# authoritative — the generic symlink pass below cannot know a repo's private layout, and
# guessing wrong is what left fresh worktrees without node_modules, so every dependency-
# importing lint died on ERR_MODULE_NOT_FOUND and was recorded as a genuine `testfail`.
WT_PREPARED=false
if [ "${ORCH_WARM_DEPS:-true}" = "true" ] && [ -f "$DEST/package.json" ] \
   && grep -q '"prepare:worktree"' "$DEST/package.json" 2>/dev/null; then
  if (cd "$DEST" && orch_timeout 300 npm run prepare:worktree --silent >/dev/null 2>&1); then
    WT_PREPARED=true
    echo "   deps: repo-native 'npm run prepare:worktree'"
  else
    echo "   deps: repo-native prepare:worktree failed — falling back to symlink warm" >&2
  fi
fi

# WARM DEPS: the agent's build-to-green loop dominates wall-clock, and a fresh worktree would
# `npm install` from scratch every time (minutes). Symlink the main checkout's node_modules (and
# reuse path-safe build caches) so `npm run build`/tests start instantly. Symlink = zero copy, zero disk.
# Disable with ORCH_WARM_DEPS=false. (npm/pnpm resolve a symlinked node_modules fine for builds.)
if [ "${ORCH_WARM_DEPS:-true}" = "true" ] && [ "$WT_PREPARED" = "false" ]; then
  # Never share .nuxt: generated tsconfig/type files contain absolute checkout
  # paths and make QA in one worktree type-check stale sources from another.
  for depdir in node_modules .next/cache node_modules/.cache; do
    src="$REPO_ROOT/$depdir"; dst="$DEST/$depdir"
    if [ -e "$src" ] && [ ! -e "$dst" ]; then
      mkdir -p "$(dirname "$dst")"
      ln -s "$src" "$dst" 2>/dev/null || true
    fi
  done
fi

# VERIFY DEPS RESOLVE: a worktree that reaches the agent without a resolvable node_modules
# turns every lint/test into a false negative that re-queues the task forever. Fail loudly
# here instead — a provisioning fault must not be laundered into a code verdict.
if [ -f "$DEST/package.json" ] && [ ! -e "$DEST/node_modules" ]; then
  if [ -e "$REPO_ROOT/node_modules" ]; then
    echo "worktree has package.json but no resolvable node_modules: $DEST" >&2
    exit 75
  fi
  echo "   deps: no node_modules in $REPO_ROOT either — skipping dep warm" >&2
fi

# NUXT TYPES: generated files are worktree-specific because they embed absolute
# paths. Regenerate the type stubs once, best-effort, so tsc-based acceptance
# checks use this checkout and can actually go green. Cheap (~seconds).
if [ "${ORCH_NUXT_PREPARE:-true}" = "true" ] && [ "$WT_PREPARED" = "false" ] \
   && [ ! -e "$DEST/.nuxt" ] && [ -f "$DEST/package.json" ] \
   && grep -q '"nuxt"' "$DEST/package.json" 2>/dev/null; then
  (cd "$DEST" && orch_timeout 180 npx nuxi prepare >/dev/null 2>&1) || true
fi

echo "✅ worktree ready: $DEST  (branch $BRANCH, based on $BASE)"
echo "   run an agent there with: scripts/orchestrate.sh"
