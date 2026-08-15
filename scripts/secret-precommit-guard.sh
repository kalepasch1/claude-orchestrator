#!/usr/bin/env bash
# secret-precommit-guard.sh — refuse to commit credential material or a real .env.
#
# WHY (incident 2026-08-02): runner/.env, carrying 11 live credentials, was committed
# on 2026-07-14. It was never pushed and the object has since been purged, but nothing
# stopped it at the time and nothing would have stopped it the next time. Separately,
# four credentials sat in the fleet_config table for an unknown period.
#
# Installed as a pre-commit STAGE, chained from each repo's existing hook so it never
# replaces repo-specific checks (migration lint, wiring gate, SFC syntax, etc.).
#
# Blocks:
#   * any staged .env / .env.local / .env.*.local / .env.bak* (templates are fine)
#   * any staged content whose value shape matches a known credential format
#
# Escape hatch for a genuine false positive:  ALLOW_SECRET_COMMIT=1 git commit ...
set -uo pipefail

if [ "${ALLOW_SECRET_COMMIT:-0}" = "1" ]; then
  echo "[secret-guard] bypassed via ALLOW_SECRET_COMMIT=1"
  exit 0
fi

staged=$(git diff --cached --name-only --diff-filter=ACM 2>/dev/null || true)
[ -z "$staged" ] && exit 0

fail=0

# --- 1. env files -----------------------------------------------------------
while IFS= read -r f; do
  case "$(basename "$f")" in
    .env|.env.local|.env.production|.env.production.local|.env.development.local|.env.bak*|.env.*.local)
      echo "[secret-guard] REFUSING to commit '$f' — env files hold credentials and belong"
      echo "               only on the host. Add it to .gitignore."
      fail=1
      ;;
  esac
done <<< "$staged"

# --- 2. credential-shaped values in staged content --------------------------
# Patterns mirror runner/fleet_config_guard.py so both doors agree.
PATTERN='(vcp_[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{30,}|sk_(live|test)_[A-Za-z0-9]{20,}|whsec_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{20,}|AIza[A-Za-z0-9_-]{30,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|postgres(ql)?://[^[:space:]:]+:[^[:space:]@]+@)'

while IFS= read -r f; do
  [ -f "$f" ] || continue
  # Skip this guard's own source and the shared classifier — they DEFINE the patterns.
  case "$f" in
    *secret-precommit-guard.sh|*fleet_config_guard.py|*config_security.py|*test_fleet_config_guard.py) continue ;;
    *.lock|*.min.js|*.map) continue ;;
  esac
  if git show ":$f" 2>/dev/null | grep -qE "$PATTERN"; then
    # Report the FORMAT, never the material.
    fmt=$(git show ":$f" 2>/dev/null | grep -oE "$PATTERN" | head -1 | cut -c1-6)
    echo "[secret-guard] REFUSING '$f' — staged content matches a credential format (${fmt}…)."
    echo "               Move it to the host env and read it with process.env / os.environ."
    fail=1
  fi
done <<< "$staged"

if [ "$fail" = "1" ]; then
  echo "[secret-guard] commit blocked. If this is genuinely a false positive:"
  echo "               ALLOW_SECRET_COMMIT=1 git commit ..."
  exit 1
fi
exit 0
