#!/bin/sh
# Refuse a tracked .js file that sits next to a .ts/.tsx source of the same name.
#
# WHY THIS EXISTS
#   Node and Nuxt module resolution prefer .js over .ts for a bare specifier, so a
#   committed CJS build artifact SHADOWS the source it was compiled from. The source
#   keeps being edited and the artifact keeps being imported, silently, with no error.
#
#   web/types/log.ts declares only types, so its tsc emit is the two-line stub
#
#       "use strict";
#       exports.__esModule = true;
#
#   and every `import type { LogLine } from '~/types/log'` that resolved to the .js
#   got nothing. web/utils/cookie-compat.js had likewise drifted from its .ts
#   (1654 vs 1433 bytes) while remaining the file actually loaded.
#
#   Commit fbd49cff8 ("remove 10 stray CJS-compiled .js duplicates shadowing their
#   .ts sources") swept ten of these; two survived and 85317112d carried them
#   forward. Nothing objected, because .gitignore cannot object to an
#   ALREADY-TRACKED path — which is the whole reason this runs on the staged set.
#
#   The cost was not only the shadowing. The integration build deletes these
#   artifacts on every run, so all 40 worktrees under
#   .runtime/integration-worktrees sat permanently dirty on the same two paths, the
#   evidence scanner harvested that dirt as recoverable work, and the fleet minted
#   an endless run of chatgpt-local-reconcile-beethoven-* tasks rediscovering it.
#
# WHAT IS ALLOWED
#   Hand-written JS with no .ts sibling is fine and stays fine —
#   web/server/utils/agentLedger.js and web/tailwind.config.js both pass.
#   Staged DELETIONS always pass, so cleaning these up is never blocked.
#
# USAGE
#   scripts/check-compiled-js-duplicates.sh            # staged files (hook mode)
#   scripts/check-compiled-js-duplicates.sh --all      # every tracked file
#
# Escape hatch: SKIP_JS_DUPLICATE_GATE=1
# Fail-soft: if git cannot be queried, the check passes and says so.
set -eu

if [ "${SKIP_JS_DUPLICATE_GATE:-0}" = "1" ]; then
  exit 0
fi

mode="${1:---staged}"

if [ "$mode" = "--all" ]; then
  files=$(git ls-files '*.js' 2>/dev/null) || {
    echo "[js-duplicate-gate] cannot list tracked files — passing (fail-soft)" >&2
    exit 0
  }
else
  # --diff-filter=d excludes deletions: removing an offender must never be blocked.
  files=$(git diff --cached --name-only --diff-filter=d 2>/dev/null | grep -E '\.js$' || true)
fi

[ -n "$files" ] || exit 0

offenders=""
for f in $files; do
  base=${f%.js}
  for ext in ts tsx; do
    if [ -f "$base.$ext" ] || git cat-file -e "HEAD:$base.$ext" 2>/dev/null; then
      offenders="$offenders$f -> $base.$ext
"
      break
    fi
  done
done

if [ -n "$offenders" ]; then
  echo "[js-duplicate-gate] X compiled .js shadowing a .ts source:" >&2
  printf '%s' "$offenders" | sed 's/^/    /' >&2
  cat >&2 <<'MSG'

Node resolves the .js first, so the .ts stops being the file that runs. Delete the
artifact and keep the source:

    git rm --cached <file> && rm <file>

If the .js is genuinely hand-written and the .ts is unrelated, rename one of them.
Break-glass: SKIP_JS_DUPLICATE_GATE=1
MSG
  exit 1
fi

exit 0
