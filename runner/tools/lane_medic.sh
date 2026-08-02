#!/bin/bash
# lane_medic.sh — stopgap watchdog (cowork 2026-08-02). Reaps zombie executor lanes and
# stuck interval daemons so the fleet can never silently fill with dead workers again.
# Durable in-scheduler version is queued (PROMPT-fleet-immune-system); this loop covers
# the gap and is safe to leave running (idempotent, logs every action).
# Launch: nohup bash runner/tools/lane_medic.sh >/dev/null 2>&1 &
LOG="$(cd "$(dirname "$0")/../.." && pwd)/.runtime/logs/lane-medic.log"
MAX_LANE_MIN=100      # headless coder sessions older than this are presumed dead
MAX_DOCKET_MIN=45     # legal_docket interval is 30m; >45m = stuck
MAX_LANES_WARN=25     # if live lanes exceed this, log loudly (leak resurfacing)
while true; do
  ts=$(date '+%F %T')
  # 1) zombie headless coder lanes (claude --output-format) older than MAX_LANE_MIN
  ps -axo pid,etime,command | grep "[c]laude --output-format" | while read -r pid et _; do
    mins=0
    case "$et" in
      *-*) mins=99999 ;;                                   # days old
      *:*:*) mins=$(( $(echo "$et" | cut -d: -f1) * 60 + $(echo "$et" | cut -d: -f2) )) ;;
      *:*) mins=$(echo "$et" | cut -d: -f1) ;;
    esac
    if [ "$mins" -ge "$MAX_LANE_MIN" ]; then
      kill "$pid" 2>/dev/null && echo "$ts reaped zombie lane pid=$pid age=${et}" >> "$LOG"
    fi
  done
  # 2) stuck legal_docket daemons (keep the newest, kill >MAX_DOCKET_MIN)
  ps -axo pid,etime,command | grep "[l]egal_docket.py" | while read -r pid et _; do
    case "$et" in
      *-*|*:*:*) kill "$pid" 2>/dev/null && echo "$ts reaped stuck legal_docket pid=$pid age=${et}" >> "$LOG" ;;
      *:*) m=$(echo "$et" | cut -d: -f1); [ "$m" -ge "$MAX_DOCKET_MIN" ] && kill "$pid" 2>/dev/null \
             && echo "$ts reaped stuck legal_docket pid=$pid age=${et}" >> "$LOG" ;;
    esac
  done
  # 3) leak telemetry
  n=$(ps aux | grep -c "[c]laude --output-format")
  [ "$n" -ge "$MAX_LANES_WARN" ] && echo "$ts WARN lane count high: $n (leak resurfacing?)" >> "$LOG"
  echo "$ts tick lanes=$n" >> "$LOG"
  sleep 600
done
