#!/usr/bin/env bash
# release_train_sync.sh — keep the dev→prod release train fast-forwardable, in both
# directions.
#
# THE INVARIANT
#
#   prod is always a fast-forward of staging.
#
# Everything the train does depends on it. `promote` is `merge --ff-only`, so the moment
# prod gains a commit staging does not have, promotion becomes impossible — and before
# 2026-08-18 it became impossible SILENTLY: the workflow logged a ::warning:: and
# `exit 0`, so every run afterwards reported success while shipping nothing. That is how
# claude-orchestrator's master ended up 14 commits ahead of orchestrator/dev with dev 0
# ahead, and how apparently's train sat wedged for a day.
#
# Making the failure loud (the first half of the fix) tells you the train is broken. It
# does not stop the train from breaking. Direct pushes to prod are not a mistake anyone
# is going to stop making: GitHub's own "Merge pull request" button targets the
# repository's DEFAULT branch, so every agent or human who opens a PR without an explicit
# --base lands on prod and wedges the train again. Two more landed while the first wedge
# was being cleared.
#
# So `reabsorb` is the other half: whenever prod moves, fold it straight back into
# staging. The invariant repairs itself instead of needing an operator.
#
# WHY THIS TERMINATES (it looks like a loop and is not)
#
#   push staging -> promote  -> prod becomes == staging -> reabsorb finds nothing -> stop
#   push prod    -> reabsorb -> staging contains prod   -> promote is already up to date
#                                                       -> pushes nothing -> stop
#
# Each direction only pushes when it has something to add, and after one pass neither
# does. A no-op pushes no ref, so it fires no workflow.
#
# WHAT IT WILL NOT DO
#
# Reabsorb never force-pushes and never rewrites staging. If prod and staging have truly
# diverged and the merge conflicts, it aborts and fails: a conflicted release train needs
# a human, and a script that resolves conflicts unattended is how work disappears.
#
# Usage:
#   scripts/release_train_sync.sh promote     # staging -> prod, fast-forward only
#   scripts/release_train_sync.sh reabsorb    # prod    -> staging, ff or merge
#
# Env:
#   ORCH_STAGING_BRANCH   default orchestrator/dev
#   ORCH_PROD_BRANCH      default master
#   ORCH_TRAIN_REMOTE     default origin
#   ORCH_TRAIN_DRY_RUN    set to 1 to report without pushing
set -euo pipefail

STAGING="${ORCH_STAGING_BRANCH:-orchestrator/dev}"
PROD="${ORCH_PROD_BRANCH:-master}"
REMOTE="${ORCH_TRAIN_REMOTE:-origin}"
DRY_RUN="${ORCH_TRAIN_DRY_RUN:-0}"

# ::error:: is a GitHub Actions annotation; outside Actions it is just a readable prefix.
err() { echo "::error::$*" >&2; }
say() { echo "$*"; }

push() {
  if [ "$DRY_RUN" = "1" ]; then
    say "dry-run: would push $*"
    return 0
  fi
  git push "$REMOTE" "$@"
}

fetch_both() {
  # Per-branch and non-fatal: `git fetch origin a b` dies with a bare
  # "couldn't find remote ref" if EITHER is missing, which tells the operator nothing
  # about the release train. Let require_both_branches produce the actionable message.
  git fetch --quiet "$REMOTE" "$PROD" || true
  git fetch --quiet "$REMOTE" "$STAGING" || true
}

# Resolve a remote-tracking sha, or empty if the branch does not exist upstream.
sha_of() {
  git rev-parse --verify --quiet "refs/remotes/$REMOTE/$1" || true
}

require_both_branches() {
  local missing=""
  [ -n "$(sha_of "$PROD")" ]    || missing="$missing $REMOTE/$PROD"
  [ -n "$(sha_of "$STAGING")" ] || missing="$missing $REMOTE/$STAGING"
  if [ -n "$missing" ]; then
    err "release train branch missing:$missing"
    return 1
  fi
}

# True when $1 is an ancestor of $2 (so $2 can fast-forward from $1).
is_ancestor() {
  git merge-base --is-ancestor "$1" "$2"
}

cmd_promote() {
  fetch_both
  require_both_branches
  local prod_sha staging_sha
  prod_sha="$(sha_of "$PROD")"
  staging_sha="$(sha_of "$STAGING")"

  if [ "$prod_sha" = "$staging_sha" ]; then
    say "$PROD is already at $STAGING ($(git rev-parse --short "$prod_sha")) — nothing to promote"
    return 0
  fi

  if ! is_ancestor "$prod_sha" "$staging_sha"; then
    err "Cannot fast-forward $PROD from $STAGING — the release train is wedged."
    err "$PROD is AHEAD of $STAGING. That happens when something is pushed directly to"
    err "$PROD. Until $PROD is merged back into $STAGING, every promote does nothing."
    err "Run: scripts/release_train_sync.sh reabsorb"
    err "Commits on $PROD but not on $STAGING:"
    git --no-pager log --oneline "$staging_sha".."$prod_sha" | head -20 >&2
    return 1
  fi

  say "promoting $STAGING -> $PROD ($(git rev-parse --short "$prod_sha") .. $(git rev-parse --short "$staging_sha"))"
  git --no-pager log --oneline "$prod_sha".."$staging_sha" | head -20
  push "$staging_sha:refs/heads/$PROD"
  say "promoted"
}

cmd_reabsorb() {
  fetch_both
  require_both_branches
  local prod_sha staging_sha
  prod_sha="$(sha_of "$PROD")"
  staging_sha="$(sha_of "$STAGING")"

  if is_ancestor "$prod_sha" "$staging_sha"; then
    say "$STAGING already contains $PROD — nothing to re-absorb"
    return 0
  fi

  say "$PROD has commits $STAGING does not:"
  git --no-pager log --oneline "$staging_sha".."$prod_sha" | head -20

  if is_ancestor "$staging_sha" "$prod_sha"; then
    # Staging is strictly behind. A fast-forward keeps history linear, which is what the
    # train's ff-only promote wants; a merge commit here would be noise.
    say "fast-forwarding $STAGING to $PROD"
    push "$prod_sha:refs/heads/$STAGING"
    say "re-absorbed (fast-forward)"
    return 0
  fi

  # Genuinely diverged: staging has unreleased work AND prod has direct pushes.
  say "$STAGING and $PROD have diverged — merging $PROD into $STAGING"
  local work
  work="$(mktemp -d)"
  # A detached worktree, never the caller's checkout: this runs in CI next to other jobs
  # and must not leave a branch checked out or an index half-written if it fails.
  git worktree add --quiet --detach "$work" "$staging_sha"
  local rc=0
  git -C "$work" merge --no-ff --no-edit \
      -m "Merge $PROD into $STAGING — re-absorb direct-to-$PROD pushes

The release train promotes $STAGING -> $PROD with 'merge --ff-only', so anything
landed directly on $PROD makes every later promote a no-op. Re-absorbing restores
the fast-forward invariant without reverting shipped work." \
      "$prod_sha" || rc=$?
  if [ "$rc" -ne 0 ]; then
    git -C "$work" merge --abort || true
    git worktree remove --force "$work" || true
    err "Merging $PROD into $STAGING conflicts. The release train needs a human."
    err "Resolve on a branch off $STAGING, merge $PROD into it, and push to $STAGING."
    return 1
  fi
  local merged
  merged="$(git -C "$work" rev-parse HEAD)"
  git worktree remove --force "$work" || true
  push "$merged:refs/heads/$STAGING"
  say "re-absorbed (merge $(git rev-parse --short "$merged"))"
}

main() {
  case "${1:-}" in
    promote)  cmd_promote ;;
    reabsorb) cmd_reabsorb ;;
    *)
      err "usage: $0 {promote|reabsorb}"
      return 2
      ;;
  esac
}

main "$@"
