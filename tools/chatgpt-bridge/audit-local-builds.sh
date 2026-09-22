#!/bin/bash
# Run the expensive fleet-local evidence sweep outside the 30-second patch path.
# local_build_audit.py owns the single-writer lock and its own 30-minute rate limit.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUDIT="$HERE/local_build_audit.py"
DROPBOX="${CHATGPT_DROPBOX:-$HOME/Documents/chatgpt-dropbox}"
LOG="$DROPBOX/_logs/bridge.log"

mkdir -p "$DROPBOX/_logs"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

audit_out="$(PYTHONDONTWRITEBYTECODE=1 python3 "$AUDIT" 2>&1)"
audit_rc=$?
if [ "$audit_rc" -eq 0 ]; then
  printf '%s LOCAL-BUILD-AUDIT %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$audit_out" >> "$LOG"
else
  printf '%s LOCAL-BUILD-AUDIT-FAILED %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$audit_out" >> "$LOG"
fi
exit "$audit_rc"
