#!/bin/sh
# protected-branch-guard.sh — pre-commit guard installed into each fleet repo.
# Blocks the exact debt classes that made staging/main test suites red (2026-07-14):
#   1. Compiled tsc artifacts (.js committed next to its .ts source) — a stale CJS
#      artifact broke beethoven's ESM test suite and Nitro routed stale handlers.
#   2. Unresolved merge-conflict markers.
#   3. Synthetic '@auto' committer identities (Vercel blocks those deploys).
# Runs in <1s (staged files only). Bypass for emergencies: ORCH_GUARD_BYPASS=1 git commit ...
[ "$ORCH_GUARD_BYPASS" = "1" ] && exit 0

branch=$(git symbolic-ref --short HEAD 2>/dev/null)
case "$branch" in
  main|master|dev|orchestrator/dev|production) protected=1 ;;
  *) protected=0 ;;
esac

staged=$(git diff --cached --name-only --diff-filter=AM)
[ -z "$staged" ] && exit 0

fail=0

# 1. Compiled artifacts: .js staged while sibling .ts exists, file starts with "use strict"
for f in $staged; do
  case "$f" in
    *.js)
      ts="${f%.js}.ts"
      if [ -f "$ts" ] && git show ":$f" 2>/dev/null | head -2 | grep -q '"use strict"'; then
        echo "GUARD: $f looks like a compiled tsc artifact (sibling $ts exists). Do not commit build output." >&2
        fail=1
      fi
      ;;
  esac
done

# 2. Conflict markers in staged content (source files only)
for f in $staged; do
  case "$f" in
    *.ts|*.js|*.vue|*.py|*.json|*.sh|*.mjs|*.tsx|*.jsx)
      if git show ":$f" 2>/dev/null | grep -qE '^(<{7}|>{7}|={7})( |$)'; then
        echo "GUARD: $f contains unresolved merge-conflict markers." >&2
        fail=1
      fi
      ;;
  esac
done

# 3. Synthetic bot identity (blocks Vercel deploys) — warn on any branch, fix identity
ae=$(git config user.email)
case "$ae" in
  *@auto*)
    echo "GUARD: git user.email '$ae' is a synthetic identity; GitHub/Vercel will block deploys. Set a real account email." >&2
    fail=1
    ;;
esac

if [ "$fail" = "1" ]; then
  if [ "$protected" = "1" ]; then
    echo "GUARD: commit to protected branch '$branch' rejected. Fix the issues above, or bypass with ORCH_GUARD_BYPASS=1 for emergencies." >&2
    exit 1
  else
    echo "GUARD: warnings above (allowed on non-protected branch '$branch', will be REJECTED by the merge train / on protected branches)." >&2
  fi
fi
exit 0
