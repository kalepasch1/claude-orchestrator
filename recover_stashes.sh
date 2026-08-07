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
# ---------------------------------------------------------------------------
# STALENESS HAZARD — read before running this again.
#
# The RECOVERABLE list below is POSITIONAL. `stash@{N}` indexes the stash reflog, so dropping
# or creating ANY stash renumbers every entry after it. These twelve indices were vetted
# against Mac 1's stash list on 2026-07-30; run this against a list that has shifted since and
# it will recover a DIFFERENT set of stashes, silently, because the wrong ones still apply
# cleanly. On a machine with a different stash list (this repo currently has none) it either
# no-ops or applies arbitrary work.
#
# Re-derive the buckets before trusting these indices:
#
#     python3 runner/stash_triage.py --repo .
#
# That is read-only — it never pops, drops, or applies — and it reports the recoverable set by
# COMMIT SHA, which is stable across renumbering. Replace RECOVERABLE with those SHAs (this
# script's `git stash show` calls accept a SHA wherever they accept stash@{N}).
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")"

BR="recovery/stashes-$(date +%Y%m%d-%H%M%S)"
LEDGER="recovery-ledger-$(date +%Y%m%d-%H%M%S).md"
RECOVERABLE=(stash@{2} stash@{37} stash@{39} stash@{64} stash@{65} stash@{69} stash@{70} stash@{97} stash@{161} stash@{220} stash@{221} stash@{259})

echo "==> current branch: $(git rev-parse --abbrev-ref HEAD)   HEAD: $(git rev-parse --short HEAD)"
if [ "$(git stash list | wc -l | tr -d ' ')" -eq 0 ]; then
  echo "!! no stashes in this repo — the vetted indices refer to Mac 1's list, not this one."
  echo "   Run: python3 runner/stash_triage.py --repo .   (read-only) before proceeding."
  exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
  echo "!! working tree is dirty — commit or handle it first (this script refuses to run dirty)"; exit 1
fi

git checkout -b "$BR"
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
EOF

git add "$LEDGER"; git -c user.name=kalepasch1 -c user.email=kalepasch@gmail.com commit -q -m "docs: stash recovery ledger"
echo
echo "==> DONE. Recovered $ok / skipped $skip on branch: $BR"
echo "==> Review:  git log --oneline $BR   |   ledger: $LEDGER"
echo "==> Merge when satisfied:  git checkout master && git merge --no-ff $BR"
echo "==> Nothing was popped or dropped — every stash is still intact."
