#!/bin/zsh
# Dead-simple runner supervisor: uses YOUR interactive shell + python, restarts on any exit,
# survives terminal close (run via nohup), logs every restart + crash so root causes are visible.
cd "$(dirname "$0")" || exit 1
export ENABLE_PROACTIVE_LOOPS=true
export ORCH_PUSH_ON_MERGE=true
while true; do
  echo "[keepalive] starting runner at $(date)" >> runner.log
  python3 runner.py >> runner.log 2>&1
  code=$?
  echo "[keepalive] runner EXITED code=$code at $(date) — restarting in 5s" >> runner.log
  sleep 5
done
