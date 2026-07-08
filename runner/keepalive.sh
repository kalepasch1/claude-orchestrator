#!/bin/zsh
# Dead-simple runner supervisor: uses YOUR interactive shell + python, restarts on any exit,
# survives terminal close (run via launchd/nohup), logs every restart + crash so root causes are visible.
RUNNER_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$RUNNER_DIR/.." && pwd)"
cd "$RUNNER_DIR" || exit 1

if [[ -r "$RUNNER_DIR/.env" ]]; then
  set -a
  source "$RUNNER_DIR/.env"
  set +a
fi

export PYTHONUNBUFFERED=1
export ENABLE_PROACTIVE_LOOPS="${ENABLE_PROACTIVE_LOOPS:-true}"
case "${ORCH_CANONICAL_RUNTIME_HOME:-true}" in
  1|true|TRUE|yes|YES|on|ON)
    export CLAUDE_ORCH_HOME="$REPO_DIR/.runtime"
    ;;
  *)
    export CLAUDE_ORCH_HOME="${CLAUDE_ORCH_HOME:-$REPO_DIR/.runtime}"
    ;;
esac
export ORCH_LOG_DIR="${ORCH_LOG_DIR:-$CLAUDE_ORCH_HOME/logs}"
export ORCH_PUSH_ON_MERGE="${ORCH_PUSH_ON_MERGE:-true}"
export ORCH_PUSH_ON_RELEASE="${ORCH_PUSH_ON_RELEASE:-true}"
mkdir -p "$ORCH_LOG_DIR"
RUNNER_LOG="$ORCH_LOG_DIR/runner.log"
LOCK_FILE="$CLAUDE_ORCH_HOME/runner.lock"
SUPERVISOR_LOCK="$CLAUDE_ORCH_HOME/keepalive.lock"
SUPERVISOR_LOG_THROTTLE="${CLAUDE_ORCH_HOME}/keepalive.duplicate.last"
STAY_RESIDENT="${ORCH_KEEPALIVE_STAY_RESIDENT:-false}"
POLL_SECONDS="${ORCH_KEEPALIVE_DUPLICATE_POLL_SECONDS:-60}"
is_live_runner() {
  if [[ ! -f "$LOCK_FILE" ]]; then
    return 1
  fi
  pid="$(head -n 1 "$LOCK_FILE" 2>/dev/null | sed 's/[^0-9].*$//')"
  if [[ -z "$pid" ]]; then
    return 1
  fi
  ps -p "$pid" >/dev/null 2>&1
}

stay_resident() {
  case "${STAY_RESIDENT:l}" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

log_duplicate_exit() {
  now="$(date +%s)"
  last="$(cat "$SUPERVISOR_LOG_THROTTLE" 2>/dev/null | tr -dc '0-9')"
  if [[ -z "$last" ]] || (( now - last >= 300 )); then
    echo "$now" > "$SUPERVISOR_LOG_THROTTLE"
    echo "[keepalive] duplicate supervisor exit at $(date)" >> "$RUNNER_LOG"
  fi
}

supervisor_lock_live() {
  if [[ ! -d "$SUPERVISOR_LOCK" ]]; then
    return 1
  fi
  sup_pid="$(cat "$SUPERVISOR_LOCK/pid" 2>/dev/null | tr -dc '0-9')"
  [[ -n "$sup_pid" ]] && ps -p "$sup_pid" >/dev/null 2>&1
}

wait_for_runner_release() {
  reason="$1"
  echo "[keepalive] ${reason}; staying resident and polling every ${POLL_SECONDS}s at $(date)" >> "$RUNNER_LOG"
  while is_live_runner; do
    sleep "$POLL_SECONDS"
  done
}

if is_live_runner; then
  if supervisor_lock_live; then
    echo "[keepalive] runner already live via lock $(cat "$LOCK_FILE" 2>/dev/null); duplicate supervisor exiting at $(date)" >> "$RUNNER_LOG"
    exit 0
  elif stay_resident; then
    wait_for_runner_release "runner already live via lock $(cat "$LOCK_FILE" 2>/dev/null)"
  else
    echo "[keepalive] runner already live via lock $(cat "$LOCK_FILE" 2>/dev/null); supervisor exiting at $(date)" >> "$RUNNER_LOG"
    exit 0
  fi
fi

while ! mkdir "$SUPERVISOR_LOCK" 2>/dev/null; do
  if supervisor_lock_live; then
    log_duplicate_exit
    exit 0
  fi
  stale="${SUPERVISOR_LOCK}.stale.$$"
  if mv "$SUPERVISOR_LOCK" "$stale" 2>/dev/null; then
    rm -rf "$stale"
    continue
  fi
  log_duplicate_exit
  exit 0
done

if ! echo "$$" > "$SUPERVISOR_LOCK/pid" 2>/dev/null; then
  log_duplicate_exit
  exit 0
fi
trap 'rm -rf "$SUPERVISOR_LOCK"' EXIT INT TERM

while true; do
  if is_live_runner; then
    if stay_resident; then
      wait_for_runner_release "runner already live via lock $(cat "$LOCK_FILE" 2>/dev/null)"
      continue
    else
      echo "[keepalive] runner already live via lock $(cat "$LOCK_FILE" 2>/dev/null); supervisor exiting at $(date)" >> "$RUNNER_LOG"
      exit 0
    fi
  fi
  echo "[keepalive] starting runner at $(date)" >> "$RUNNER_LOG"
  tmp_log="$(mktemp "${ORCH_LOG_DIR}/runner-start.XXXXXX")"
  python3 runner.py > "$tmp_log" 2>&1
  code=$?
  cat "$tmp_log" >> "$RUNNER_LOG"
  if grep -q "another runner already holds the lock" "$tmp_log"; then
    rm -f "$tmp_log"
    if stay_resident; then
      wait_for_runner_release "singleton runner already live"
      continue
    else
      echo "[keepalive] singleton runner already live; supervisor exiting at $(date)" >> "$RUNNER_LOG"
      exit 0
    fi
  fi
  rm -f "$tmp_log"
  echo "[keepalive] runner EXITED code=$code at $(date) — restarting in 5s" >> "$RUNNER_LOG"
  sleep 5
done
