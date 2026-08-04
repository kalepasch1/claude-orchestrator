#!/usr/bin/env bash
# install-secret-guard.sh — chain the secret pre-commit guard into every repo.
#
# Idempotent. Preserves each repo's existing pre-commit hook by chaining rather than
# replacing it (the orchestrator, apparently, tomorrow, pareto and smarter hooks run
# migration lint / wiring gates / SFC syntax checks that must keep running).
set -uo pipefail

GUARD_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/secret-precommit-guard.sh"
[ -f "$GUARD_SRC" ] || { echo "missing $GUARD_SRC"; exit 1; }

REPOS=(
  "$HOME/Documents/beethoven/claude-orchestrator"
  "$HOME/Documents/apparently"
  "$HOME/Documents/apparently-law"
  "$HOME/Documents/tomorrow/tomorrow"
  "$HOME/Documents/pareto/2080"
  "$HOME/Documents/smarter"
  "$HOME/Documents/illuminati"
  "$HOME/Documents/vigil"
)

MARK="# >>> secret-guard (managed) >>>"

for repo in "${REPOS[@]}"; do
  [ -d "$repo/.git" ] || { printf "  %-34s skip (not a git repo)\n" "$(basename "$repo")"; continue; }
  hooks="$repo/.git/hooks"; mkdir -p "$hooks"
  cp "$GUARD_SRC" "$hooks/secret-precommit-guard.sh"
  chmod +x "$hooks/secret-precommit-guard.sh"
  hook="$hooks/pre-commit"

  if [ ! -f "$hook" ]; then
    printf '#!/usr/bin/env bash\n%s\n"$(dirname "$0")/secret-precommit-guard.sh" || exit 1\n# <<< secret-guard (managed) <<<\n' "$MARK" > "$hook"
    chmod +x "$hook"
    printf "  %-34s installed (new hook)\n" "$(basename "$repo")"
  elif grep -q "$MARK" "$hook"; then
    printf "  %-34s already chained\n" "$(basename "$repo")"
  else
    # Prepend so the cheap secret check runs before slower repo gates.
    tmp="$(mktemp)"
    head -1 "$hook" > "$tmp"                      # keep the shebang first
    printf '%s\n"$(dirname "$0")/secret-precommit-guard.sh" || exit 1\n# <<< secret-guard (managed) <<<\n' "$MARK" >> "$tmp"
    tail -n +2 "$hook" >> "$tmp"
    mv "$tmp" "$hook"; chmod +x "$hook"
    printf "  %-34s chained into existing hook\n" "$(basename "$repo")"
  fi
done
echo "done — bypass for a genuine false positive: ALLOW_SECRET_COMMIT=1 git commit ..."
