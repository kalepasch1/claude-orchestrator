#!/usr/bin/env bash
# check-plist-secret-hygiene.sh — no launchd job may carry a credential in its plist.
#
# WHY THIS EXISTS. Several com.claudeorchestrator.*.plist files once embedded
# SUPABASE_SERVICE_KEY in plaintext EnvironmentVariables blocks. Those copies were
# redundant as well as unsafe: launcher.sh already sources runner/.env under the Full Disk
# Access grant, so every job inherits its environment from one place. A plist is
# world-readable, is copied into ~/Library/LaunchAgents, and survives a repo clean — so a
# key in one outlives every rotation you think you performed.
#
# WHAT IT CHECKS, AND WHY IT IS NARROWER THAN IT LOOKS. Two things must not trip it:
#   * XML COMMENTS. runner/launchd/com.orchestrator.runner.plist says
#     "add VERCEL_TOKEN / SUPABASE_ACCESS_TOKEN / provider keys here or rely on
#     runner/.env" — that is documentation pointing at the SAFE path, and flagging it
#     would train people to delete the guidance instead of the secret. Comments are
#     stripped before scanning.
#   * NON-SECRET TUNABLES. ORCH_SUPABASE_TIMEOUT is a number. The pattern matches
#     credential-shaped KEY NAMES and JWT-shaped VALUES, never the bare word SUPABASE.
#
# The original proof for this was
#   ! grep -rl 'service_role' ~/Library/LaunchAgents/com.claudeorchestrator.*.plist
# which misses two whole classes: a non-service_role credential, and any job whose label
# does not start with com.claudeorchestrator (com.orchestrator.runner.plist is one).
# This checks both prefixes and the committed templates as well as the installed jobs.
#
# Exit 0 = clean. Exit 1 = a credential is embedded somewhere it must never be.
#
#   scripts/check-plist-secret-hygiene.sh              # templates + installed jobs
#   scripts/check-plist-secret-hygiene.sh --repo-only  # templates only (CI, no ~/Library)
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ONLY="${1:-}"

KEY_PATTERN='SUPABASE_SERVICE_KEY|SUPABASE_ANON_KEY|SUPABASE_KEY|SERVICE_ROLE|[A-Z0-9]_SECRET|[A-Z0-9]_TOKEN|[A-Z0-9]_PASSWORD|ANTHROPIC_API_KEY|OPENAI_API_KEY|GITHUB_PAT'
VALUE_PATTERN='eyJhbGciOi|"role"[[:space:]]*:[[:space:]]*"service_role"'

fail=0

# Strip XML comments so documentation pointing at runner/.env is never flagged.
_strip_comments() { perl -0pe 's/<!--.*?-->//gs' "$1" 2>/dev/null || cat "$1"; }

_scan_file() {
  local label="$1" f="$2" body hits
  [ -f "$f" ] || return 0
  body="$(_strip_comments "$f")"
  # A credential-shaped KEY element, or a JWT-shaped value anywhere.
  hits="$(printf '%s' "$body" | grep -Eo "<key>[^<]*($KEY_PATTERN)[^<]*</key>" | sort -u)"
  if [ -z "$hits" ] && printf '%s' "$body" | grep -Eq "$VALUE_PATTERN"; then
    hits="(credential-shaped value)"
  fi
  if [ -n "$hits" ]; then
    echo "FAIL [$label] $f embeds a credential-shaped key/value"
    # KEY NAMES ONLY — a guard that echoes the value has leaked it a second time.
    printf '%s\n' "$hits" | sed 's/^/       /'
    fail=1
  fi
}

# 1. Committed templates.
if [ -d "$REPO/runner/launchd" ]; then
  for f in "$REPO"/runner/launchd/*.plist; do
    _scan_file "template" "$f"
  done
fi

# 2. Generators — only a problem when they WRITE a credential key into plist XML.
for gen in "$REPO/scripts/setup-scheduler.sh" "$REPO/scripts/bootstrap-runner.sh"; do
  [ -f "$gen" ] || continue
  if grep -Eq "<key>[^<]*($KEY_PATTERN)" "$gen"; then
    echo "FAIL [generator] $gen writes a credential into a plist"
    fail=1
  fi
done

# 3. Installed jobs on this machine — both label prefixes.
if [ "$REPO_ONLY" != "--repo-only" ]; then
  for f in "$HOME"/Library/LaunchAgents/com.claudeorchestrator.*.plist \
           "$HOME"/Library/LaunchAgents/com.orchestrator.*.plist; do
    _scan_file "installed" "$f"
  done
fi

if [ "$fail" -eq 0 ]; then
  echo "plist secret hygiene: clean (jobs inherit env via launcher.sh -> runner/.env)"
fi
exit "$fail"
