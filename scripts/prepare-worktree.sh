#!/usr/bin/env bash
# Make an agent worktree runnable without a per-worktree `npm install`.
#
# THE PROBLEM
# -----------
# Per CLAUDE.md all agent work happens in isolated worktrees under `{repo}-wt/{slug}`.
# A fresh worktree contains only TRACKED files, and `node_modules/` is gitignored —
# so every node workspace in the tree (web/, runner/, mcp/, packages/*) comes up
# empty. `scripts/install-language-deps.sh --verify` correctly reports six
# unsatisfied manifests and exits 1, and any task that touches node fails on
# "Cannot find module" before it writes a line of code. The main checkout has all
# six installed; the worktree is one `ln -s` away from working.
#
# The obvious repair — run `npm install` in each worktree — is the wrong one: six
# workspaces, minutes of wall clock and hundreds of MB per worktree, for a branch
# that exists for one task and is deleted after the push. Multiply by the number of
# concurrent agents and it is the most expensive no-op in the fleet.
#
# THE REPAIR
# ----------
# Link each workspace's `node_modules` to the already-installed directory in the
# main checkout. Both paths are gitignored, so nothing here can be committed by
# accident, and the link costs milliseconds.
#
# Usage:
#   bash scripts/prepare-worktree.sh            # link what is missing
#   bash scripts/prepare-worktree.sh --check    # report only, exit 1 if unlinked
#   bash scripts/prepare-worktree.sh --force    # replace existing links/dirs
#
# Idempotent, fail-soft, and a NO-OP in the main checkout (there is nothing to link
# to, and clobbering the real directories would break every other worktree).
set -uo pipefail

MODE="link"
case "${1:-}" in
  --check) MODE="check" ;;
  --force) MODE="force" ;;
  "")      ;;
  *) echo "usage: $0 [--check|--force]"; exit 2 ;;
esac

note() { printf '==> %s\n' "$*"; }
warn() { printf '!!  %s\n' "$*" >&2; }

REPO="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "${REPO:-}" ]; then
  warn "not inside a git repository; nothing to prepare"
  exit 0
fi
cd "$REPO" || exit 0

# `git rev-parse --git-common-dir` points at the MAIN checkout's .git for a
# worktree, and at this repo's own .git otherwise — which is exactly the test for
# "am I a worktree", without parsing paths or assuming the -wt naming convention.
COMMON_GIT="$(git rev-parse --git-common-dir 2>/dev/null)"
case "$COMMON_GIT" in
  /*) ;;
  *)  COMMON_GIT="$REPO/$COMMON_GIT" ;;
esac
MAIN="$(cd "$(dirname "$COMMON_GIT")" && pwd 2>/dev/null)"

if [ -z "${MAIN:-}" ] || [ "$MAIN" = "$REPO" ]; then
  note "main checkout ($REPO) — nothing to link"
  exit 0
fi

note "worktree: $REPO"
note "main:     $MAIN"
note "mode:     $MODE"
echo

# Workspaces are discovered, not hardcoded: a new packages/* workspace should be
# linked the day it lands, not the day someone remembers to edit this list.
#
# Discovery is `git ls-files`, deliberately, NOT `find`. This repo has several
# unrelated checkouts sitting inside it (beethoven/, growth-os/, hisanta/,
# pareto/, cowork-skills/ ...), each with its own package.json tree, and a `find`
# walks straight into all of them — the first version of this script found several
# hundred "workspaces" that belong to other repositories. Only files this repo
# actually tracks are ours to link.
WORKSPACES=()
while IFS= read -r manifest; do
  [ -n "$manifest" ] || continue
  case "$manifest" in
    */node_modules/*|node_modules/*) continue ;;
  esac
  WORKSPACES+=( "$(dirname "$manifest")" )
done < <(cd "$MAIN" && git ls-files -- 'package.json' '*/package.json' 2>/dev/null | sort -u)

# `.nuxt`-style generated dirs have no equivalent here, so node_modules is the
# whole job. Kept as a list so adding one later is a one-line change.
LINK_NAMES=( node_modules )

linked=0; already=0; skipped=0; missing=0; nosrc=0

for ws in "${WORKSPACES[@]}"; do
  for name in "${LINK_NAMES[@]}"; do
    src="$MAIN/${ws#./}"
    src="${src%/}/$name"
    dst="$REPO/${ws#./}"
    dst="${dst%/}/$name"
    label="${ws#./}/$name"
    label="${label#/}"

    if [ ! -d "$src" ]; then
      # Nothing installed upstream either. Usually benign — the root manifest
      # declares no dependencies, so npm never creates a node_modules for it —
      # and where it is not, `make install-all-deps` in the main checkout is the
      # fix, not this script. Counted separately so it cannot fail --check: a
      # worktree is not "unprepared" because of a workspace with nothing to link.
      nosrc=$((nosrc + 1))
      continue
    fi

    if [ -L "$dst" ]; then
      if [ "$MODE" = "force" ]; then
        rm -f "$dst"
      else
        already=$((already + 1))
        continue
      fi
    elif [ -e "$dst" ]; then
      # A real directory here means someone already ran npm install in the
      # worktree. Leave it alone unless explicitly forced — deleting a populated
      # node_modules is not something a helper script should do by default.
      skipped=$((skipped + 1))
      continue
    fi

    if [ "$MODE" = "check" ]; then
      missing=$((missing + 1))
      warn "not linked: $label"
      continue
    fi

    if mkdir -p "$(dirname "$dst")" && ln -s "$src" "$dst" 2>/dev/null; then
      linked=$((linked + 1))
      note "linked $label"
    else
      warn "could not link $label"
      missing=$((missing + 1))
    fi
  done
done

echo
note "summary: linked=$linked already=$already existing-dir=$skipped unresolved=$missing nothing-to-link=$nosrc"

if [ "$MODE" = "check" ] && [ "$missing" -gt 0 ]; then
  warn "worktree is not prepared — run: bash scripts/prepare-worktree.sh"
  exit 1
fi

# Fail-soft by design: a worktree that could not be fully linked is still usable
# for the Python-only majority of tasks, and the warnings above say exactly what
# is missing. Only --check gates.
exit 0
