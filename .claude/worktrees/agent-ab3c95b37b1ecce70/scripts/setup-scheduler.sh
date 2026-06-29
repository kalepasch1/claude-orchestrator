#!/bin/bash
# setup-scheduler.sh — installs Claude Orchestrator launchd agents.
# Reads runner/.env at install time, substitutes placeholders, installs to
# ~/Library/LaunchAgents/. Safe to re-run: unloads old versions before reloading.
#
# PREREQUISITE (macOS Ventura/Sonoma): the runner agent needs Full Disk Access.
# One-time, 2 clicks:
#   System Settings → Privacy & Security → Full Disk Access → + → ~/Applications/ClaudeRunner.app
#   System Settings → General → Login Items → + → ~/Applications/ClaudeRunner.app
# Then re-run this script. The .app is just a thin shell wrapper with the FDA grant.
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

# ── Always-on agents ──────────────────────────────────────────────────────────
# These run continuously (KeepAlive) or on fixed intervals.
ALWAYS_ON_PLISTS=(
    com.claudeorchestrator.runner
    com.claudeorchestrator.self-review
    com.claudeorchestrator.anomaly
    com.claudeorchestrator.research-window
    com.claudeorchestrator.overnight-deploy
    com.claudeorchestrator.txn
)

# ── Scheduled periodic jobs ───────────────────────────────────────────────────
# These run at specific calendar times.
PERIODIC_PLISTS=(
    com.claudeorchestrator.spec
    com.claudeorchestrator.scout
    com.claudeorchestrator.chaos
    com.claudeorchestrator.deploy
    com.claudeorchestrator.roi
    com.claudeorchestrator.batch
    com.claudeorchestrator.maturity
    com.claudeorchestrator.radar
    com.claudeorchestrator.demand
)

ALL_PLISTS=("${ALWAYS_ON_PLISTS[@]}" "${PERIODIC_PLISTS[@]}")

for label in "${ALL_PLISTS[@]}"; do
    src="$PLIST_DIR/${label}.plist"
    dst="$LAUNCH_AGENTS/${label}.plist"

    if [[ ! -f "$src" ]]; then
        echo "    SKIP $label (no plist template found)"
        continue
    fi

    echo "==> Installing $label"

    # Substitute all placeholders with real values from .env
    sed \
        -e "s|REPO_PATH|$REPO|g" \
        -e "s|HOME_DIR|$HOME|g" \
        -e "s|LOG_DIR|$LOG_DIR|g" \
        -e "s|SUPABASE_URL_PLACEHOLDER|${SUPABASE_URL:-}|g" \
        -e "s|SUPABASE_SERVICE_KEY_PLACEHOLDER|${SUPABASE_SERVICE_KEY:-}|g" \
        -e "s|MAX_PARALLEL_PLACEHOLDER|${MAX_PARALLEL:-2}|g" \
        -e "s|POLL_SECONDS_PLACEHOLDER|${POLL_SECONDS:-5}|g" \
        -e "s|TEST_CMD_PLACEHOLDER|${TEST_CMD:-npm test}|g" \
        -e "s|METRICS_URL_PLACEHOLDER|${METRICS_URL:-}|g" \
        -e "s|ANTHROPIC_API_KEY_PLACEHOLDER|${ANTHROPIC_API_KEY:-}|g" \
        -e "s|CLAUDE_BIN_PLACEHOLDER|${CLAUDE_BIN:-claude}|g" \
        -e "s|REQUESTS_FILE_PLACEHOLDER|${REQUESTS_FILE:-}|g" \
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
echo "  runner.log       – main interactive runner"
echo "  txn.log          – transaction coordinator (every 5 min)"
echo "  spec.log         – spec drift check (Sun 02:00)"
echo "  scout.log        – opportunity scout (Sun 03:00)"
echo "  chaos.log        – chaos drills (Sat 02:00, staging only)"
echo "  deploy.log       – canary deploy window (nightly 02:30)"
echo "  roi.log          – ROI scoring (daily 00:15)"
echo "  batch.log        – Batch API off-peak pass (23:30 + 08:00 poll)"
echo "  maturity.log     – capability maturity recompute (daily 02:30)"
echo "  radar.log        – capability radar cross-app proposals (Mon 03:00)"
echo "  demand.log       – demand signal mining (Mon 04:00)"
echo "  self-review.log  anomaly.log  research-window.log  overnight-deploy.log"
echo ""
echo "NOTE: chaos drills only run when CHAOS_ENABLED=true in the plist env."
echo "      Canary deploy requires METRICS_URL to be set in runner/.env."
echo "      Batch API requires ANTHROPIC_API_KEY to be set in runner/.env."
echo ""
echo "NOTE: If runner.err shows 'Operation not permitted', you need Full Disk Access:"
echo "  System Settings → Privacy & Security → Full Disk Access → + → Terminal.app"
echo "  Then re-run this script."
