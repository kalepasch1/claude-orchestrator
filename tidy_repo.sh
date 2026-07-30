#!/usr/bin/env bash
# tidy_repo.sh — archive fleet-generated documentation sprawl; keep the repo root legible.
# bash 3.2 compatible (macOS default) — no mapfile, no associative arrays.
#
# SAFE BY DESIGN: nothing is deleted. Files MOVE to docs/archive/<date>/ and stay in git history.
# Curated docs (README/CLAUDE/AGENTS/SECURITY/SETUP/CHATGPT/runbook/PROMPT-*) are never touched.
#
# Usage:  ./tidy_repo.sh            # dry run
#         ./tidy_repo.sh --apply    # move + stage
set -uo pipefail
cd "$(dirname "$0")"
APPLY="${1:-}"
ARCHIVE="docs/archive/$(date +%Y-%m-%d)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

KEEP_RE='^(README|CLAUDE|AGENTS|SECURITY|SETUP|CHATGPT|LICENSE|CONTRIBUTING)\.md$|^MASTER-IMPLEMENTATION-RUNBOOK|^(HOLD-)?PROMPT-'

ls -1 *.md *.txt 2>/dev/null | grep -vE "$KEEP_RE" > "$TMP/candidates" || true
TOTAL=$(ls -1 *.md *.txt 2>/dev/null | wc -l | tr -d ' ')
NCAND=$(wc -l < "$TMP/candidates" | tr -d ' ')

echo "== root-level docs =="
echo "  total root .md/.txt: $TOTAL"
echo "  candidates to archive: $NCAND"
head -12 "$TMP/candidates" | sed 's/^/    /'
[ "$NCAND" -gt 12 ] && echo "    … and $((NCAND - 12)) more"

# duplicate ADRs: same slug (filename minus 'ADR-YYYY-MM-DD-'), different dates
: > "$TMP/dupes"; : > "$TMP/seen"
for f in $(ls -1 docs/decisions/ADR-*.md 2>/dev/null | sort); do
  base=$(basename "$f")
  slug=$(echo "$base" | sed -E 's/^ADR-[0-9]{4}-[0-9]{2}-[0-9]{2}-//')
  if grep -qxF "$slug" "$TMP/seen" 2>/dev/null; then
    echo "$f" >> "$TMP/dupes"
  else
    echo "$slug" >> "$TMP/seen"
  fi
done
NADR=$(ls -1 docs/decisions/*.md 2>/dev/null | wc -l | tr -d ' ')
NUNIQ=$(wc -l < "$TMP/seen" | tr -d ' ')
NDUP=$(wc -l < "$TMP/dupes" | tr -d ' ')
echo
echo "== duplicate ADRs =="
echo "  ADR files: $NADR   unique decisions: $NUNIQ   duplicates: $NDUP"

if [ "$APPLY" != "--apply" ]; then
  echo; echo "DRY RUN — nothing moved. Re-run with --apply (files MOVE, never delete)."
  exit 0
fi

mkdir -p "$ARCHIVE/root-docs" "$ARCHIVE/duplicate-adrs"
moved=0
while IFS= read -r f; do
  [ -n "$f" ] || continue
  git mv -f "$f" "$ARCHIVE/root-docs/" 2>/dev/null || mv -f "$f" "$ARCHIVE/root-docs/" 2>/dev/null || continue
  moved=$((moved+1))
done < "$TMP/candidates"
while IFS= read -r f; do
  [ -n "$f" ] || continue
  git mv -f "$f" "$ARCHIVE/duplicate-adrs/" 2>/dev/null || mv -f "$f" "$ARCHIVE/duplicate-adrs/" 2>/dev/null || continue
  moved=$((moved+1))
done < "$TMP/dupes"

cat > "$ARCHIVE/README.md" <<'EOF'
# Archive

Fleet-generated documentation moved out of the repo root for legibility.
Nothing deleted — every file is here and in git history.

- `root-docs/` — status/remediation/security notes auto-emitted during fleet runs
- `duplicate-adrs/` — repeat ADRs for decisions that already had one. Root cause fixed
  2026-07-30 in `runner/cx_auto_adr.py`: idempotency keyed on date+slug instead of slug alone,
  so every still-recent decision re-emitted a new ADR daily (49 files for 17 decisions).
EOF

echo "archived $moved file(s) -> $ARCHIVE"
echo "root .md/.txt now: $(ls -1 *.md *.txt 2>/dev/null | wc -l | tr -d ' ')"
