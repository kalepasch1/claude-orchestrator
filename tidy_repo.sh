#!/usr/bin/env bash
# tidy_repo.sh — archive fleet-generated documentation sprawl; keep the repo root legible.
#
# WHY: 98 root-level .md/.txt files and 49 ADRs for 17 unique decisions had accumulated —
# fleet-generated status/remediation/security notes that were never cleaned up. Noise at this
# volume hides real signal (it is the same "accumulating unnoticed" pattern as the 315 stashes
# and the 194 silent train crashes).
#
# SAFE BY DESIGN: nothing is deleted. Files are MOVED to docs/archive/<date>/ and committed,
# so every byte stays in git history and on disk. Curated docs (see KEEP) are never touched.
#
# Usage:  ./tidy_repo.sh            # dry run — shows what would move
#         ./tidy_repo.sh --apply    # actually move + stage
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
APPLY="${1:-}"
ARCHIVE="docs/archive/$(date +%Y-%m-%d)"

# Curated docs that must stay at root, ever.
KEEP_RE='^(README|CLAUDE|AGENTS|SECURITY|SETUP|CHATGPT|LICENSE|CONTRIBUTING)\.md$|^MASTER-IMPLEMENTATION-RUNBOOK|^(HOLD-)?PROMPT-'

echo "== root-level docs =="
mapfile -t CANDIDATES < <(ls -1 *.md *.txt 2>/dev/null | grep -vE "$KEEP_RE" || true)
echo "  total root .md/.txt: $(ls -1 *.md *.txt 2>/dev/null | wc -l | tr -d ' ')"
echo "  candidates to archive: ${#CANDIDATES[@]}"
printf '    %s\n' "${CANDIDATES[@]:0:12}"
[ "${#CANDIDATES[@]}" -gt 12 ] && echo "    … and $(( ${#CANDIDATES[@]} - 12 )) more"

echo
echo "== duplicate ADRs (same decision, different dates) =="
DUPES=()
declare -A seen
for f in $(ls -1 docs/decisions/ADR-*.md 2>/dev/null | sort); do
  base="$(basename "$f")"; slug="${base#ADR-}"; slug="${slug:11}"   # strip 'ADR-YYYY-MM-DD-'
  if [ -n "${seen[$slug]:-}" ]; then DUPES+=("$f"); else seen[$slug]="$f"; fi
done
echo "  ADR files: $(ls -1 docs/decisions/*.md 2>/dev/null | wc -l | tr -d ' ')  unique decisions: ${#seen[@]}  duplicates: ${#DUPES[@]}"

if [ "$APPLY" != "--apply" ]; then
  echo
  echo "DRY RUN — nothing moved. Re-run with --apply to archive (files are MOVED, never deleted)."
  exit 0
fi

mkdir -p "$ARCHIVE/root-docs" "$ARCHIVE/duplicate-adrs"
moved=0
for f in "${CANDIDATES[@]}"; do git mv -f "$f" "$ARCHIVE/root-docs/" 2>/dev/null || mv -f "$f" "$ARCHIVE/root-docs/"; moved=$((moved+1)); done
for f in "${DUPES[@]}"; do git mv -f "$f" "$ARCHIVE/duplicate-adrs/" 2>/dev/null || mv -f "$f" "$ARCHIVE/duplicate-adrs/"; moved=$((moved+1)); done

cat > "$ARCHIVE/README.md" <<EOF
# Archive $(date +%Y-%m-%d)

Fleet-generated documentation moved out of the repo root for legibility.
Nothing deleted — every file is here and in git history.

- \`root-docs/\` — status/remediation/security notes auto-emitted during fleet runs
- \`duplicate-adrs/\` — repeat ADRs for decisions that already had one (root cause fixed
  2026-07-30 in \`runner/cx_auto_adr.py\`: idempotency keyed on date+slug instead of slug,
  so every decision re-emitted daily)

Retention: keep indefinitely; they are small and occasionally useful forensically.
EOF

echo "archived $moved file(s) -> $ARCHIVE"
echo "root .md/.txt now: $(ls -1 *.md *.txt 2>/dev/null | wc -l | tr -d ' ')"
echo "run: ./opgit save \"chore: archive fleet-generated doc sprawl + fix ADR dedupe root cause\""
