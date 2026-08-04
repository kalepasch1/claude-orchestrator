#!/usr/bin/env bash
# sync-rotated-secrets-to-ci.sh — push freshly-rotated .env values into GitHub Actions secrets.
#
# WHY: rotating a credential locally only finishes half the job. After the 2026-08-02
# rotation, four GitHub repo secrets still held the June values:
#     claude-orchestrator : OPENAI_API_KEY, VERCEL_TOKEN
#     apparently         : VERCEL_TOKEN
#     tomorrow           : VERCEL_TOKEN
# Once the old tokens are revoked those secrets are dead and every workflow that uses
# them fails; until they are revoked, they are still-live copies of exposed material.
#
# Values move file -> gh CLI over a pipe. Nothing is echoed, nothing is written to a
# temp file, nothing appears in shell history or process args (gh reads stdin).
set -uo pipefail

ENV_FILE="${ORCH_ENV_FILE:-$HOME/Documents/beethoven/claude-orchestrator/runner/.env}"
[ -f "$ENV_FILE" ] || { echo "no env file at $ENV_FILE"; exit 1; }
command -v gh >/dev/null || { echo "gh CLI not found"; exit 1; }

# repo:SECRET pairs to keep in sync
TARGETS=(
  "kalepasch1/claude-orchestrator:VERCEL_TOKEN"
  "kalepasch1/claude-orchestrator:OPENAI_API_KEY"
  "kalepasch1/apparently:VERCEL_TOKEN"
  "kalepasch1/tomorrow:VERCEL_TOKEN"
)

read_env() {  # read_env KEY -> value on stdout, nothing on failure
  grep -m1 "^$1=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"
}

fail=0
for t in "${TARGETS[@]}"; do
  repo="${t%%:*}"; key="${t##*:}"
  if [ -z "$(read_env "$key")" ]; then
    printf "  %-34s %-16s SKIP (not set in .env)\n" "$repo" "$key"
    continue
  fi
  # pipe: the value never becomes an argument, a temp file, or shell history
  if read_env "$key" | gh secret set "$key" -R "$repo" >/dev/null 2>&1; then
    printf "  %-34s %-16s updated\n" "$repo" "$key"
  else
    printf "  %-34s %-16s FAILED (check gh auth / repo access)\n" "$repo" "$key"
    fail=1
  fi
done

echo
echo "verification (timestamps should be from the last minute):"
for t in "${TARGETS[@]}"; do
  repo="${t%%:*}"; key="${t##*:}"
  gh secret list -R "$repo" 2>/dev/null | awk -v k="$key" -v r="$repo" '$1==k {printf "  %-34s %-16s %s\n", r, k, $2}'
done
exit $fail
