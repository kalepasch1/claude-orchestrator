#!/bin/bash
# watchdog.sh — is the ChatGPT bridge actually alive?
#
# install.sh copies this OUTSIDE ~/Documents (to ~/Library/Application Support/
# chatgpt-bridge/) and runs it from its own launchd agent every 5 minutes.
#
# That placement is the whole point. The bridge itself lives in ~/Documents,
# which macOS TCC hides from launchd unless the caller holds Full Disk Access.
# When that grant is lost the bridge cannot run *or* report — the script is not
# even readable. So the thing that notices must live somewhere always reachable
# and must judge by absence: no heartbeat for N minutes means broken, not idle.
set -uo pipefail

HEARTBEAT="$HOME/Library/Logs/claude-orchestrator/chatgpt-bridge.heartbeat"
STATE="$HOME/Library/Application Support/chatgpt-bridge"
ALERT_STAMP="$STATE/.last-alert"
STALE_SECONDS="${CHATGPT_BRIDGE_STALE_SECONDS:-600}"   # sweep runs every 30s
ALERT_EVERY="${CHATGPT_BRIDGE_ALERT_EVERY:-3600}"
mkdir -p "$STATE" 2>/dev/null

NOW=$(date +%s)
LAST=$(cat "$HEARTBEAT" 2>/dev/null || echo 0)
AGE=$(( NOW - LAST ))

if [ "$LAST" -eq 0 ]; then
  REASON="the bridge has never completed a sweep"
elif [ "$AGE" -gt "$STALE_SECONDS" ]; then
  REASON="no sweep in $(( AGE / 60 )) minutes"
else
  exit 0   # healthy
fi

# Rate-limit so a long outage does not spam.
LAST_ALERT=$(cat "$ALERT_STAMP" 2>/dev/null || echo 0)
[ $(( NOW - LAST_ALERT )) -lt "$ALERT_EVERY" ] && exit 0
echo "$NOW" > "$ALERT_STAMP"

MSG="ChatGPT bridge is not running — $REASON. Patches dropped in the folder are NOT reaching GitHub. Most likely ClaudeRunner.app lost Full Disk Access."
osascript -e "display notification \"$MSG\" with title \"ChatGPT bridge: BROKEN\" sound name \"Basso\"" 2>/dev/null
echo "$(date '+%Y-%m-%d %H:%M:%S') ALERT $REASON" >> "$STATE/watchdog.log"
exit 1
