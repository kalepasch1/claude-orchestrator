#!/bin/bash
# ClaudeRunner launcher. The .app bundle is the macOS Full Disk Access holder; launchd should
# start this app wrapper, not scripts under Documents directly.

REPO="${CLAUDE_ORCH_REPO:-__REPO_PATH__}"
if [[ "$REPO" == "__REPO_PATH__" || ! -d "$REPO/runner" ]]; then
    for cand in "$HOME/claude-orchestrator" "$HOME/Documents/beethoven/claude-orchestrator"; do
        if [[ -d "$cand/runner" ]]; then
            REPO="$cand"
            break
        fi
    done
fi

LOG_DIR="${ORCH_LAUNCHD_LOG_DIR:-__LOG_DIR__}"
if [[ "$LOG_DIR" == "__LOG_DIR__" ]]; then
    LOG_DIR="$HOME/Library/Logs/claude-orchestrator"
fi
mkdir -p "$LOG_DIR"
APP_DIR="${CLAUDE_RUNNER_APP_DIR:-__APP_DIR__}"
case "$APP_DIR" in
  __APP_DIR*)
    APP_DIR="$HOME/Applications/ClaudeRunner.app"
    ;;
esac

JOB="${1:-}"

if [[ ! -d "$REPO/runner" ]]; then
    echo "ClaudeRunner cannot find orchestrator repo at $REPO" >&2
    exit 78
fi

if ! { : < "$REPO/runner/.env"; } 2>/dev/null \
    || ! { : < "$REPO/runner/keepalive.sh"; } 2>/dev/null; then
    echo "ClaudeRunner cannot read $REPO/runner/.env or keepalive.sh." >&2
    echo "Grant Full Disk Access to $APP_DIR, then re-run scripts/setup-scheduler.sh." >&2
    sleep "${ORCH_LAUNCHD_PERMISSION_BACKOFF:-600}"
    exit 75
fi

set -a
if ! . "$REPO/runner/.env"; then
    set +a
    echo "ClaudeRunner failed to load $REPO/runner/.env." >&2
    echo "Grant Full Disk Access to $APP_DIR, then re-run scripts/setup-scheduler.sh." >&2
    sleep "${ORCH_LAUNCHD_PERMISSION_BACKOFF:-600}"
    exit 75
fi
set +a

if [[ -z "$JOB" ]]; then
    export ORCH_KEEPALIVE_STAY_RESIDENT="${ORCH_KEEPALIVE_STAY_RESIDENT:-true}"
    export ORCH_KEEPALIVE_DUPLICATE_POLL_SECONDS="${ORCH_KEEPALIVE_DUPLICATE_POLL_SECONDS:-60}"
    exec /bin/zsh "$REPO/runner/keepalive.sh" \
        >> "$LOG_DIR/runner.log" 2>> "$LOG_DIR/runner.err"
elif [[ "$JOB" == *.py ]]; then
    exec /usr/bin/python3 "$REPO/runner/$JOB"
else
    exec /usr/bin/python3 "$REPO/runner/periodic.py" "$JOB"
fi
