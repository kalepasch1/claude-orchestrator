#!/bin/bash
# apply-patch.sh — take a patch/bundle produced in a no-network agent session
# (ChatGPT code interpreter, etc.) and land it on GitHub from this Mac.
#
# Usage:
#   apply-patch.sh <file> [--repo NAME] [--branch NAME] [--no-pr] [--push-to-default]
#
# Accepts: *.patch  *.diff  (unified/format-patch)   *.zip  *.tar.gz  (file bundle)
#
# Repo is resolved in this order:
#   1. --repo flag
#   2. "# repo: <name>" header line inside a .patch/.diff
#   3. filename prefix before "--"   e.g.  tomorrow--fix-login.patch
#
# Work happens in an isolated worktree ({repo}-wt/<slug>) — never in the main
# checkout — per the orchestrator worktree convention.
set -uo pipefail

REPO_ROOTS=(
  "$HOME/Documents/beethoven/claude-orchestrator"
  "$HOME/Documents/tomorrow/tomorrow"
  "$HOME/Documents/apparently"
  "$HOME/Documents/smarter"
  "$HOME/Documents/illuminati"
  "$HOME/Documents/vigil"
)

GIT_NAME="kalepasch1"
GIT_EMAIL="kalepasch@gmail.com"

die() { echo "ERROR: $*" >&2; exit 1; }
log() { echo "[chatgpt-bridge] $*"; }

FILE=""; REPO=""; BRANCH=""; MAKE_PR=1; TARGET_DEFAULT=0
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="$2"; shift 2;;
    --branch) BRANCH="$2"; shift 2;;
    --no-pr) MAKE_PR=0; shift;;
    --push-to-default) TARGET_DEFAULT=1; shift;;
    -*) die "unknown flag $1";;
    *) FILE="$1"; shift;;
  esac
done

[ -n "$FILE" ] || die "usage: apply-patch.sh <file> [--repo NAME] [--branch NAME]"
[ -f "$FILE" ] || die "no such file: $FILE"
FILE="$(cd "$(dirname "$FILE")" && pwd)/$(basename "$FILE")"
BASENAME="$(basename "$FILE")"

# ---- resolve repo -----------------------------------------------------------
if [ -z "$REPO" ]; then
  case "$BASENAME" in
    *.patch|*.diff) REPO="$(grep -m1 -E '^#[[:space:]]*repo:' "$FILE" 2>/dev/null | sed -E 's/^#[[:space:]]*repo:[[:space:]]*//' | tr -d '[:space:]')";;
  esac
fi
if [ -z "$REPO" ] && [[ "$BASENAME" == *--* ]]; then
  REPO="${BASENAME%%--*}"
fi
[ -n "$REPO" ] || die "cannot determine repo. Name the file '<repo>--<slug>.patch' or pass --repo."

ROOT=""
for r in "${REPO_ROOTS[@]}"; do
  [ "$(basename "$r")" = "$REPO" ] && ROOT="$r" && break
done
[ -n "$ROOT" ] || die "unknown repo '$REPO'. Known: $(for r in "${REPO_ROOTS[@]}"; do basename "$r"; done | tr '\n' ' ')"
[ -d "$ROOT/.git" ] || die "$ROOT is not a git checkout"

# ---- branch name ------------------------------------------------------------
if [ -z "$BRANCH" ]; then
  SLUG="$(echo "${BASENAME%.*}" | sed -E "s/^${REPO}--//" | sed -E 's/[^a-zA-Z0-9._-]+/-/g' | cut -c1-48)"
  [ -n "$SLUG" ] || SLUG="patch"
  BRANCH="chatgpt/${SLUG}-$(date +%m%d%H%M)"
fi
SAFE_SLUG="$(echo "$BRANCH" | tr '/' '-')"
WT="${ROOT}-wt/${SAFE_SLUG}"

log "repo=$REPO root=$ROOT branch=$BRANCH"

# ---- fresh worktree off the default branch ----------------------------------
DEFAULT_BRANCH="$(git -C "$ROOT" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')"
[ -n "$DEFAULT_BRANCH" ] || DEFAULT_BRANCH="$(git -C "$ROOT" remote show origin 2>/dev/null | awk '/HEAD branch/{print $NF}')"
[ -n "$DEFAULT_BRANCH" ] || DEFAULT_BRANCH="main"
log "default branch: $DEFAULT_BRANCH"

git -C "$ROOT" fetch origin "$DEFAULT_BRANCH" --quiet || die "fetch failed (network?)"

rm -rf "$WT" 2>/dev/null
git -C "$ROOT" worktree prune --quiet 2>/dev/null
mkdir -p "$(dirname "$WT")"
git -C "$ROOT" worktree add -b "$BRANCH" "$WT" "origin/$DEFAULT_BRANCH" --quiet \
  || die "could not create worktree $WT"

cleanup_fail() {
  git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1
  git -C "$ROOT" branch -D "$BRANCH" >/dev/null 2>&1
}

git -C "$WT" config user.name "$GIT_NAME"
git -C "$WT" config user.email "$GIT_EMAIL"

# ---- apply ------------------------------------------------------------------
case "$BASENAME" in
  *.patch|*.diff)
    if grep -qE '^From [0-9a-f]{7,40} ' "$FILE"; then
      git -C "$WT" am --3way --keep-cr "$FILE" \
        || { git -C "$WT" am --abort >/dev/null 2>&1; cleanup_fail; die "git am failed — patch does not apply cleanly"; }
      PRE_COMMITTED=1
    else
      git -C "$WT" apply --3way --whitespace=nowarn "$FILE" \
        || { cleanup_fail; die "git apply failed — patch does not apply cleanly to origin/$DEFAULT_BRANCH"; }
      PRE_COMMITTED=0
    fi
    ;;
  *.zip)
    command -v unzip >/dev/null || { cleanup_fail; die "unzip not found"; }
    unzip -o -q "$FILE" -d "$WT" || { cleanup_fail; die "unzip failed"; }
    PRE_COMMITTED=0
    ;;
  *.tar.gz|*.tgz)
    tar -xzf "$FILE" -C "$WT" || { cleanup_fail; die "tar failed"; }
    PRE_COMMITTED=0
    ;;
  *) cleanup_fail; die "unsupported file type: $BASENAME (want .patch .diff .zip .tar.gz)";;
esac

# ---- commit -----------------------------------------------------------------
if [ "$PRE_COMMITTED" -eq 0 ]; then
  git -C "$WT" add -A
  if git -C "$WT" diff --cached --quiet; then
    cleanup_fail; die "patch applied but produced no changes"
  fi
  MSG="$(grep -m1 -E '^#[[:space:]]*message:' "$FILE" 2>/dev/null | sed -E 's/^#[[:space:]]*message:[[:space:]]*//')"
  [ -n "$MSG" ] || MSG="chore: apply ${BASENAME%.*} (via chatgpt-bridge)"
  git -C "$WT" commit -q -m "$MSG" || { cleanup_fail; die "commit failed"; }
fi

CHANGED=$(git -C "$WT" diff --name-only "origin/$DEFAULT_BRANCH"...HEAD | wc -l | tr -d ' ')
log "committed — $CHANGED file(s) changed"

# ---- verify author (Vercel blocks non-owner authors) ------------------------
AUTH="$(git -C "$WT" log -1 --pretty='%an <%ae>')"
if [ "$AUTH" != "$GIT_NAME <$GIT_EMAIL>" ]; then
  log "rewriting commit author ($AUTH -> $GIT_NAME <$GIT_EMAIL>)"
  git -C "$WT" commit --amend --no-edit --reset-author -q
fi

# ---- push -------------------------------------------------------------------
if [ "$TARGET_DEFAULT" -eq 1 ]; then
  git -C "$WT" push origin "HEAD:$DEFAULT_BRANCH" || { cleanup_fail; die "push to $DEFAULT_BRANCH failed"; }
  log "pushed directly to $DEFAULT_BRANCH"
  RESULT="pushed to $DEFAULT_BRANCH"
else
  git -C "$WT" push -u origin "$BRANCH" --quiet || { cleanup_fail; die "push failed"; }
  log "pushed branch $BRANCH"
  RESULT="branch $BRANCH"
  if [ "$MAKE_PR" -eq 1 ] && command -v gh >/dev/null; then
    PR_URL="$(cd "$WT" && gh pr create --fill --base "$DEFAULT_BRANCH" --head "$BRANCH" 2>&1 | grep -Eo 'https://github.com/[^ ]+' | head -1)"
    [ -n "$PR_URL" ] && { log "PR: $PR_URL"; RESULT="$PR_URL"; }
  fi
fi

git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1
git -C "$ROOT" worktree prune --quiet 2>/dev/null

echo "OK: $REPO — $RESULT"
