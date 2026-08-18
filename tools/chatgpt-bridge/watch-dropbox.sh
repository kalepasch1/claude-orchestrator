#!/bin/bash
# watch-dropbox.sh — one sweep of the ChatGPT patch drop-box.
# Run by launchd (com.claudeorchestrator.chatgptbridge) every 30s.
#
# Drop any .patch / .diff / .zip / .tar.gz into ~/Documents/chatgpt-dropbox/
# and it lands on GitHub as a branch + PR. Results appear in _applied/ or _failed/.
set -uo pipefail

DROPBOX="${CHATGPT_DROPBOX:-$HOME/Documents/chatgpt-dropbox}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPLY="$HERE/apply-patch.sh"
LOG="$DROPBOX/_logs/bridge.log"

mkdir -p "$DROPBOX/_applied" "$DROPBOX/_failed" "$DROPBOX/_logs"

# Homebrew paths for launchd's minimal env (gh lives there)
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

say() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }

# ---- self-diagnosis: can this process actually see the drop-box and the repos? --
# launchd is denied ~/Documents unless it runs through an app bundle holding Full
# Disk Access. Without this check the watcher just silently never fires, which is
# the worst failure mode: patches pile up looking accepted and nothing ships.
#
# The heartbeat deliberately lives under ~/Library, NOT in the drop-box: if the
# FDA grant is lost, everything under ~/Documents becomes unreadable, so a
# watchdog could not see a heartbeat kept there — nor could this script even be
# executed to complain. ~/Library is reachable without FDA, so the watchdog can
# always tell "no sweep in N minutes" apart from "all quiet".
HB_DIR="$HOME/Library/Logs/claude-orchestrator"
mkdir -p "$HB_DIR" 2>/dev/null
HEARTBEAT="$HB_DIR/chatgpt-bridge.heartbeat"
PROBE_REPO="$HOME/Documents/beethoven/claude-orchestrator/.git/HEAD"
if ! { : < "$PROBE_REPO"; } 2>/dev/null; then
  say "FATAL no read access to $PROBE_REPO — Full Disk Access missing"
  # Only nag once an hour; this runs every 30s.
  STAMP="$DROPBOX/_logs/.fda-alert"
  LAST=$(cat "$STAMP" 2>/dev/null || echo 0)
  NOW=$(date +%s)
  if [ $((NOW - LAST)) -gt 3600 ]; then
    echo "$NOW" > "$STAMP"
    osascript -e 'display notification "ClaudeRunner.app lost Full Disk Access — patches are NOT being pushed. System Settings -> Privacy & Security -> Full Disk Access." with title "ChatGPT bridge: BROKEN" sound name "Basso"' 2>/dev/null
  fi
  exit 75
fi
date +%s > "$HEARTBEAT" 2>/dev/null

shopt -s nullglob
FOUND=0
for f in "$DROPBOX"/*.patch "$DROPBOX"/*.diff "$DROPBOX"/*.zip "$DROPBOX"/*.tar.gz "$DROPBOX"/*.tgz; do
  [ -f "$f" ] || continue
  FOUND=1
  base="$(basename "$f")"

  # skip files still being written (size changing / <2s old)
  s1=$(stat -f%z "$f" 2>/dev/null || echo 0); sleep 1
  s2=$(stat -f%z "$f" 2>/dev/null || echo 0)
  [ "$s1" != "$s2" ] && { say "SKIP (still writing) $base"; continue; }

  say "PROCESSING $base"
  stamp="$(date '+%Y%m%d-%H%M%S')"
  out="$("$APPLY" "$f" 2>&1)"
  rc=$?
  printf '%s\n' "$out" >> "$LOG"

  if [ $rc -eq 0 ]; then
    mv -f "$f" "$DROPBOX/_applied/${stamp}--${base}"
    printf '%s\n' "$out" > "$DROPBOX/_applied/${stamp}--${base}.result.txt"
    say "OK $base"
    result="$(printf '%s' "$out" | tail -1)"
    osascript -e "display notification \"$result\" with title \"ChatGPT bridge: pushed\"" 2>/dev/null
  else
    mv -f "$f" "$DROPBOX/_failed/${stamp}--${base}"
    printf '%s\n' "$out" > "$DROPBOX/_failed/${stamp}--${base}.error.txt"
    say "FAIL $base"
    err="$(printf '%s' "$out" | grep -m1 '^ERROR:' | cut -c1-180)"
    osascript -e "display notification \"${err:-see _failed/}\" with title \"ChatGPT bridge: FAILED $base\"" 2>/dev/null
  fi
done

exit 0
