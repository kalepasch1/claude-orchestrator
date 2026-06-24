#!/bin/bash
# setup-scheduler.sh — installs Claude Orchestrator launchd agents.
# Safe to re-run: unloads old versions before reloading.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PLIST_DIR="$REPO/scripts/launchd"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs/claude-orchestrator"

echo "==> Creating log directory $LOG_DIR"
mkdir -p "$LOG_DIR"

echo "==> Stopping any manually-started runner processes"
pkill -f "runner.py" 2>/dev/null && echo "    killed existing runner" || echo "    no runner to kill"
sleep 2

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
    cp "$src" "$dst"

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
