#!/bin/bash
# setup-scheduler.sh — installs Claude Orchestrator launchd agents.
# Reads runner/.env at install time, substitutes placeholders, installs to
# ~/Library/LaunchAgents/. Safe to re-run: unloads old versions before reloading.
#
# PREREQUISITE (macOS Ventura/Sonoma): the runner agent needs Full Disk Access.
# One-time, 2 clicks:
#   System Settings → Privacy & Security → Full Disk Access → + → ClaudeRunner.app
#   System Settings → General → Login Items → + → ClaudeRunner.app
# Then re-run this script. The .app is just a thin shell wrapper with the FDA grant.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO/runner/.env"
PLIST_DIR="$REPO/scripts/launchd"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs/claude-orchestrator"
if [[ -n "${ORCH_CLAUDE_RUNNER_APP_DIR:-}" ]]; then
  APP_DIR="$ORCH_CLAUDE_RUNNER_APP_DIR"
elif [[ -w "/Applications" || -d "/Applications/ClaudeRunner.app" ]]; then
  APP_DIR="/Applications/ClaudeRunner.app"
else
  APP_DIR="$HOME/Applications/ClaudeRunner.app"
fi
APP_LAUNCHER="$APP_DIR/Contents/Resources/launcher.sh"
APP_LAUNCHER_TEMPLATE="$PLIST_DIR/ClaudeRunner-launcher.sh"
APP_EXEC="$APP_DIR/Contents/MacOS/ClaudeRunner"
APP_EXEC_COMPAT="$APP_DIR/Contents/MacOS/run"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: $ENV_FILE not found. Copy runner/.env.example to runner/.env and fill in secrets." >&2
  exit 1
fi

# Load env vars from .env. This preserves quoted JSON values such as ORCH_EXTRA_CODERS.
set -a
source "$ENV_FILE"
set +a

echo "==> Creating log directory $LOG_DIR"
mkdir -p "$LOG_DIR"

create_claude_runner_app() {
    echo "==> Creating/updating ClaudeRunner.app wrapper"
    mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources"
    cat > "$APP_DIR/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key><string>ClaudeRunner</string>
  <key>CFBundleIdentifier</key><string>com.claudeorchestrator.runner</string>
  <key>CFBundleName</key><string>ClaudeRunner</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>LSBackgroundOnly</key><true/>
  <key>LSUIElement</key><true/>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST
    cat > "$APP_DIR/Contents/Resources/ClaudeRunner.c" <<'RUNNER'
#include <errno.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

int main(int argc, char **argv) {
    char exe[PATH_MAX];
    uint32_t size = sizeof(exe);
    if (_NSGetExecutablePath(exe, &size) != 0) {
        fprintf(stderr, "ClaudeRunner executable path too long\n");
        return 78;
    }
    char *slash = strrchr(exe, '/');
    if (!slash) {
        fprintf(stderr, "ClaudeRunner cannot resolve Contents/MacOS directory\n");
        return 78;
    }
    *slash = '\0';

    char launcher[PATH_MAX];
    if (snprintf(launcher, sizeof(launcher), "%s/../Resources/launcher.sh", exe) >= (int)sizeof(launcher)) {
        fprintf(stderr, "ClaudeRunner launcher path too long\n");
        return 78;
    }

    char **child_args = calloc((size_t)argc + 4, sizeof(char *));
    if (!child_args) {
        perror("calloc");
        return 70;
    }
    child_args[0] = "/bin/bash";
    child_args[1] = "--noprofile";
    child_args[2] = launcher;
    for (int i = 1; i < argc; i++) {
        child_args[i + 2] = argv[i];
    }
    child_args[argc + 2] = NULL;

    pid_t pid = fork();
    if (pid < 0) {
        perror("fork");
        free(child_args);
        return 71;
    }
    if (pid == 0) {
        execv("/bin/bash", child_args);
        perror("execv");
        _exit(127);
    }

    int status = 0;
    while (waitpid(pid, &status, 0) < 0) {
        if (errno != EINTR) {
            perror("waitpid");
            free(child_args);
            return 71;
        }
    }
    free(child_args);
    if (WIFEXITED(status)) {
        return WEXITSTATUS(status);
    }
    if (WIFSIGNALED(status)) {
        return 128 + WTERMSIG(status);
    }
    return 70;
}
RUNNER
    if command -v cc >/dev/null 2>&1 && cc "$APP_DIR/Contents/Resources/ClaudeRunner.c" -o "$APP_EXEC" >/dev/null 2>&1; then
        chmod +x "$APP_EXEC"
    else
        cat > "$APP_EXEC" <<'RUNNER'
#!/bin/bash
HERE="$(cd "$(dirname "$0")" && pwd)"
exec /bin/bash --noprofile "$HERE/../Resources/launcher.sh" "$@"
RUNNER
        chmod +x "$APP_EXEC"
    fi
    cat > "$APP_EXEC_COMPAT" <<'RUNNER'
#!/bin/bash
HERE="$(cd "$(dirname "$0")" && pwd)"
exec "$HERE/ClaudeRunner" "$@"
RUNNER
    chmod +x "$APP_EXEC_COMPAT"
}

create_claude_runner_app

if [[ -f "$APP_LAUNCHER_TEMPLATE" && -d "$APP_DIR" ]]; then
    echo "==> Updating ClaudeRunner.app launcher"
    sed \
        -e "s|__REPO_PATH__|$REPO|g" \
        -e "s|__LOG_DIR__|$LOG_DIR|g" \
        -e "s|__APP_DIR__|$APP_DIR|g" \
        "$APP_LAUNCHER_TEMPLATE" > "$APP_LAUNCHER"
    chmod +x "$APP_LAUNCHER"
    codesign --force --deep --sign - "$APP_DIR" >/dev/null 2>&1 || true
fi

if [[ "${ORCH_SETUP_RESTART_RUNNER:-false}" =~ ^(1|true|yes|on)$ ]]; then
    echo "==> Stopping manually-started runner processes"
    pkill -f "runner.py" 2>/dev/null && echo "    killed existing runner" || echo "    no runner to kill"
    sleep 1
else
    echo "==> Preserving active runner processes (set ORCH_SETUP_RESTART_RUNNER=true to restart)"
fi

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
    com.claudeorchestrator.agentmarket
    com.claudeorchestrator.commonbrain
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
        -e "s|__APP_DIR__|$APP_DIR|g" \
        -e "s|HOME_DIR|$HOME|g" \
        -e "s|LOG_DIR|$LOG_DIR|g" \
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
echo "  agentmarket.log  – role-aware cross-app agent market (every 15 min)"
echo "  commonbrain.log  – reusable common brain deployments (every 30 min)"
echo "  self-review.log  anomaly.log  research-window.log  overnight-deploy.log"
echo ""
echo "NOTE: chaos drills only run when CHAOS_ENABLED=true in the plist env."
echo "      Canary deploy requires METRICS_URL to be set in runner/.env."
echo "      Batch API requires ANTHROPIC_API_KEY to be set in runner/.env."
echo ""
echo "NOTE: If runner.err shows 'Operation not permitted', you need Full Disk Access:"
echo "  System Settings → Privacy & Security → Full Disk Access → + → $APP_DIR"
echo "  Then re-run this script."

echo ""
echo "Fleet doctor:"
if [[ "${ORCH_SETUP_SKIP_FLEET_DOCTOR:-false}" =~ ^(1|true|yes|on)$ ]]; then
    echo "  skipped (ORCH_SETUP_SKIP_FLEET_DOCTOR=true)"
else
    ORCH_SUPABASE_TIMEOUT="${ORCH_SETUP_DOCTOR_TIMEOUT:-8}" python3 "$REPO/runner/fleet_doctor.py" --brief || true
fi
