#!/bin/bash
# setup-scheduler.sh — installs Claude Orchestrator launchd agents.
# Reads runner/.env at install time, substitutes placeholders, installs to
# ~/Library/LaunchAgents/. Safe to re-run: unloads old versions before reloading.
#
# PREREQUISITE (macOS Ventura/Sonoma): launchd agents need Full Disk Access to
# reach ~/Documents/. Grant it once in:
#   System Settings → Privacy & Security → Full Disk Access → + → add Terminal.app
# Then re-run this script.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO/runner/.env"
PLIST_DIR="$REPO/scripts/launchd"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs/claude-orchestrator"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: $ENV_FILE not found. Copy runner/.env.example to runner/.env and fill in secrets." >&2
  exit 1
fi

# Load env vars from .env (strip quotes, skip comments/blanks)
eval "$(grep -E '^[A-Z_]+=.+' "$ENV_FILE" | sed 's/^/export /')"

echo "==> Creating log directory $LOG_DIR"
mkdir -p "$LOG_DIR"

echo "==> Stopping any manually-started runner processes"
pkill -f "runner.py" 2>/dev/null && echo "    killed existing runner" || echo "    no runner to kill"
sleep 1

PLISTS=(
    com.claudeorchestrator.runner
    com.claudeorchestrator.self-review
    com.claudeorchestrator.anomaly
    com.claudeorchestrator.research-window
    com.claudeorchestrator.overnight-deploy
)

for label in "${PLISTS[@]}"; do
    src="$PLIST_DIR/${label}.plist"
    dst="$LAUNCH_AGENTS/${label}.plist"

    echo "==> Installing $label"

    # Substitute placeholders with real values from .env
    sed \
        -e "s|REPO_PATH|$REPO|g" \
        -e "s|LOG_DIR|$LOG_DIR|g" \
        -e "s|SUPABASE_URL_PLACEHOLDER|${SUPABASE_URL:-}|g" \
        -e "s|SUPABASE_SERVICE_KEY_PLACEHOLDER|${SUPABASE_SERVICE_KEY:-}|g" \
        -e "s|MAX_PARALLEL_PLACEHOLDER|${MAX_PARALLEL:-2}|g" \
        -e "s|POLL_SECONDS_PLACEHOLDER|${POLL_SECONDS:-5}|g" \
        -e "s|TEST_CMD_PLACEHOLDER|${TEST_CMD:-npm test}|g" \
        "$src" > "$dst"

    # Unload silently if already loaded
    launchctl unload "$dst" 2>/dev/null || true
    launchctl load "$dst"
    echo "    loaded"
done

echo ""
echo "All agents installed. Verify with:"
echo "  launchctl list | grep claudeorchestrator"
echo ""
echo "Logs: $LOG_DIR/"
echo "  runner.log / runner.err"
echo "  self-review.log | anomaly.log | research-window.log | overnight-deploy.log"
echo ""
echo "NOTE: If runner.err shows 'Operation not permitted', you need Full Disk Access:"
echo "  System Settings → Privacy & Security → Full Disk Access → + → Terminal.app"
echo "  Then re-run this script."
