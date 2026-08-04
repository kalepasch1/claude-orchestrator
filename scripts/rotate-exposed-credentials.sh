#!/usr/bin/env bash
# rotate-exposed-credentials.sh — finish the 2026-08-02 credential rotation.
#
# Context: four credentials were found stored in plaintext in the fleet_config table
# (GITHUB_PAT, VERCEL_TOKEN, OPENAI_API_KEY, GEMINI_API_KEY), plus a fifth status row
# whose value matched a token shape. All five rows are purged and a db-layer guard now
# refuses to store credentials there. Separately, runner/.env carrying 11 credentials
# had been committed on 2026-07-14 (never pushed); that object is purged from the repo.
#
# The VALUES are still live at each provider, so they must be rotated. This script does
# every mechanical step; you paste each new token ONCE, into this terminal, hidden.
# Nothing is echoed, nothing is logged, nothing leaves this machine except the calls to
# Vercel/GitHub you explicitly approve.
#
# Run:  bash scripts/rotate-exposed-credentials.sh
set -uo pipefail

ENV_FILE="${ORCH_ENV_FILE:-$HOME/Documents/beethoven/claude-orchestrator/runner/.env}"
BOLD=$'\033[1m'; DIM=$'\033[2m'; RESET=$'\033[0m'; RED=$'\033[31m'; GRN=$'\033[32m'

say()  { printf "%s\n" "$*"; }
head2(){ printf "\n%s%s%s\n" "$BOLD" "$*" "$RESET"; }
ok()   { printf "  %s✓%s %s\n" "$GRN" "$RESET" "$*"; }
bad()  { printf "  %s✗%s %s\n" "$RED" "$RESET" "$*"; }

[ -f "$ENV_FILE" ] || { bad "no env file at $ENV_FILE"; exit 1; }
cp -p "$ENV_FILE" "$ENV_FILE.prerotate.$(date +%Y%m%d%H%M%S)"
chmod 600 "$ENV_FILE".prerotate.* 2>/dev/null || true

# Replace KEY=value in place, atomically, without ever printing the value.
set_env() {
  local key="$1" val="$2" tmp
  tmp="$(mktemp)"; chmod 600 "$tmp"
  if grep -q "^${key}=" "$ENV_FILE"; then
    awk -v k="$key" -v v="$val" 'BEGIN{FS=OFS="="} $1==k {print k "=" v; next} {print}' "$ENV_FILE" > "$tmp"
  else
    cat "$ENV_FILE" > "$tmp"; printf '%s=%s\n' "$key" "$val" >> "$tmp"
  fi
  mv "$tmp" "$ENV_FILE"; chmod 600 "$ENV_FILE"
  ok "$key written to $(basename "$ENV_FILE") (600, value never displayed)"
}

prompt_secret() {   # prompt_secret VAR_NAME "provider url"
  local key="$1" url="$2" val=""
  head2 "$key"
  say "  Revoke the old one and create a new one: ${DIM}${url}${RESET}"
  printf "  Paste the NEW %s (input hidden, or press Enter to skip): " "$key"
  read -rs val; echo
  if [ -z "$val" ]; then say "  ${DIM}skipped${RESET}"; return 1; fi
  set_env "$key" "$val"
  printf '%s' "$val" > /dev/null   # never echoed, never stored elsewhere
  return 0
}

head2 "1. GITHUB_PAT — revoke only, no replacement needed"
say "  This machine pushes via the osxkeychain credential helper, and GITHUB_PAT is"
say "  not present in your .env — nothing reads it. So it only needs REVOKING:"
say "    ${DIM}https://github.com/settings/tokens${RESET}"
say "  (If you later need one for CI, add it as a repo secret, not to .env.)"
printf "  Press Enter once revoked (or 's' to skip): "; read -r _ack

prompt_secret "VERCEL_TOKEN"   "https://vercel.com/account/tokens"
ROT_VERCEL=$?
prompt_secret "OPENAI_API_KEY" "https://platform.openai.com/api-keys"
prompt_secret "GEMINI_API_KEY" "https://aistudio.google.com/apikey"

head2 "Verifying the new Vercel token"
if [ "${ROT_VERCEL:-1}" = "0" ]; then
  # shellcheck disable=SC1090
  VT="$(grep '^VERCEL_TOKEN=' "$ENV_FILE" | cut -d= -f2- | tr -d '"'"'"'')"
  code=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $VT" \
          https://api.vercel.com/v2/user 2>/dev/null)
  unset VT
  case "$code" in
    200) ok "new VERCEL_TOKEN authenticates" ;;
    403|401) bad "new VERCEL_TOKEN rejected (HTTP $code) — re-check it" ;;
    *) say "  ${DIM}could not verify (HTTP $code) — check connectivity${RESET}" ;;
  esac
else
  say "  ${DIM}skipped${RESET}"
fi

head2 "Removing stale .env backups that still hold OLD credentials"
say "  These were 600-hardened but are full copies of every secret:"
ls -1 "$(dirname "$ENV_FILE")"/.env.bak.* 2>/dev/null | sed 's/^/    /'
printf "  Delete them now that rotation is done? [y/N]: "; read -r yn
if [ "$yn" = "y" ] || [ "$yn" = "Y" ]; then
  rm -f "$(dirname "$ENV_FILE")"/.env.bak.* && ok "stale backups deleted"
else
  say "  ${DIM}kept — delete manually once you're confident${RESET}"
fi

head2 "Confirming fleet_config is still clean"
python3 - <<'PY' 2>/dev/null || say "  (run from the repo root to check)"
import sys, os
sys.path.insert(0, os.path.expanduser("~/Documents/beethoven/claude-orchestrator/runner"))
import db, fleet_config_guard as g
rows = db.select('fleet_config', {'select': 'key,value'})
hits = g.scan_rows(rows)
print(f"  fleet_config rows: {len(rows)}   credentials: {len(hits)}")
if hits:
    print("  STILL EXPOSED:", [h['key'] for h in hits])
PY

head2 "Done"
say "  A pre-rotation copy of your env is at ${DIM}${ENV_FILE}.prerotate.*${RESET} (600)."
say "  Delete it once the fleet is confirmed healthy."
say "  Restart the fleet so runners pick up the new values:"
say "    ${DIM}touch ~/Documents/beethoven/claude-orchestrator/runner/.restart_requested${RESET}"
