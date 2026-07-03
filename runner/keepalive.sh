#!/bin/zsh
# Dead-simple runner supervisor: uses YOUR interactive shell + python, restarts on any exit,
# survives terminal close (run via nohup), logs every restart + crash so root causes are visible.
cd "$(dirname "$0")" || exit 1
export ENABLE_PROACTIVE_LOOPS=true
export CLAUDE_ORCH_HOME="/Users/kpasch/Documents/beethoven/claude-orchestrator/.runtime"
export ORCH_LOG_DIR="/Users/kpasch/Documents/beethoven/claude-orchestrator/.runtime/logs"
export ORCH_PUSH_ON_MERGE=false
export ORCH_PUSH_ON_RELEASE=true
mkdir -p "$ORCH_LOG_DIR"
RUNNER_LOG="$ORCH_LOG_DIR/runner.log"
while true; do
  echo "[keepalive] starting runner at $(date)" >> "$RUNNER_LOG"
  python3 runner.py >> "$RUNNER_LOG" 2>&1
  code=$?
  echo "[keepalive] runner EXITED code=$code at $(date) — restarting in 5s" >> "$RUNNER_LOG"
  sleep 5
done
