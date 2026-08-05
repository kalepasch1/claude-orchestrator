#!/usr/bin/env bash
# Stash recovery — SAFE, serial, reversible. Generated 2026-07-30 after read-only triage of 315 stashes.
#
# Triage result (verified read-only):
#   119 empty            -> nothing to recover (drop candidates)
#    37 already-landed   -> content already in HEAD (drop candidates)
#    12 RECOVERABLE      -> real content, applies cleanly to HEAD  <-- THIS SCRIPT RECOVERS THESE
#   120 conflicted       -> needs human/agent judgment (76 touch runner/) -> flagged, NOT touched
#
# This script ONLY handles the 12 cleanly-recoverable stashes. It never pops, never drops,
# never touches the conflicted set. Each becomes its own commit on ONE recovery branch so you
# can review, cherry-pick, or discard wholesale.
set -euo pipefail
cd "$(dirname "$0")"

REPO="$(pwd)"
BR="recovery/stashes-$(date +%Y%m%d-%H%M%S)"
LEDGER="recovery-ledger-$(date +%Y%m%d-%H%M%S).md"

# Stash indices are NOT stable: stash@{N} shifts every time any stash is pushed or dropped, so a
# recorded index silently points at a different stash later. Resolve the recoverable set fresh, by
# COMMIT SHA, via the read-only triage in runner/stash_triage.py.
RECOVERABLE=()
while IFS= read -r sha; do
  [ -n "$sha" ] && RECOVERABLE+=("$sha")
done < <(python3 runner/stash_triage.py "$REPO" --recoverable 2>/dev/null || true)

if [ ${#RECOVERABLE[@]} -eq 0 ]; then
  echo "==> nothing cleanly recoverable right now (triage found 0). Nothing was touched."; exit 0
fi
echo "==> ${#RECOVERABLE[@]} cleanly-recoverable stashes resolved by SHA"

echo "==> current branch: $(git rev-parse --abbrev-ref HEAD)   HEAD: $(git rev-parse --short HEAD)"
if [ -n "$(git status --porcelain)" ]; then
  echo "!! working tree is dirty — commit or handle it first (this script refuses to run dirty)"; exit 1
fi

# Never leave the main checkout on a non-base branch: sentinel.py stashes+resets anything it finds
# there (CLAUDE.md worktree convention). Do the recovery in an isolated worktree instead.
WT="$(dirname "$REPO")/$(basename "$REPO")-wt/$BR"
git worktree prune
git worktree add --force "$WT" -B "$BR" HEAD
cd "$WT"
echo "# Stash Recovery Ledger — $(date -u)" > "$LEDGER"
echo -e "\nBranch: \`$BR\`\nBase: \`$(git rev-parse --short HEAD)\`\n" >> "$LEDGER"
echo "| stash | files | result |" >> "$LEDGER"
echo "|---|---|---|" >> "$LEDGER"

ok=0; skip=0
for S in "${RECOVERABLE[@]}"; do
  FILES=$(git stash show --name-only "$S" 2>/dev/null | tr '\n' ' ' || true)
  if git stash show -p "$S" 2>/dev/null | git apply --check - 2>/dev/null; then
    git stash show -p "$S" | git apply -
    git add -A
    git -c user.name=kalepasch1 -c user.email=kalepasch@gmail.com \
        commit -q -m "recover($S): $FILES" || true
    echo "| \`$S\` | $FILES | RECOVERED |" >> "$LEDGER"
    echo "  [ok]   $S  ->  $FILES"; ok=$((ok+1))
  else
    echo "| \`$S\` | $FILES | skipped (no longer applies) |" >> "$LEDGER"
    echo "  [skip] $S (no longer applies cleanly)"; skip=$((skip+1))
  fi
done

echo -e "\n**Recovered: $ok · Skipped: $skip**\n" >> "$LEDGER"
cat >> "$LEDGER" <<'EOF'
## Not touched by this script (require judgment)
- **120 conflicted stashes** (76 touch `runner/`) — these are the ones that may hold genuinely
  lost improvements that cannot be auto-applied because the files moved on. The queued
  `PROMPT-beethoven-core-integrity-audit.md` (§5) triages these one at a time against current HEAD,
  choosing the best version where duplicates exist.
- **119 empty + 37 already-landed** — safe to drop once you're satisfied; keeping them costs nothing
  but noise. Suggested: `git stash drop` them only AFTER the conflicted set is resolved.

Work the conflicted set one at a time with the read-only triage:
`python3 runner/stash_triage.py . --next` (priority: stashes touching `runner/`).
EOF

git add "$LEDGER"; git -c user.name=kalepasch1 -c user.email=kalepasch@gmail.com commit -q -m "docs: stash recovery ledger"
echo
echo "==> DONE. Recovered $ok / skipped $skip on branch: $BR"
echo "==> Worktree: $WT   (main checkout was never left on a non-base branch)"
echo "==> Review:  git log --oneline $BR   |   ledger: $WT/$LEDGER"
echo "==> Merge when satisfied, from the main checkout:  git merge --no-ff $BR"
echo "==> Next conflicted stash to triage:  python3 runner/stash_triage.py . --next"
echo "==> Nothing was popped or dropped — every stash is still intact."
