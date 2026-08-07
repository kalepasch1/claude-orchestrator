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
MAINTENANCE_LOCK="${ORCH_MAINTENANCE_LOCK:-$CLAUDE_ORCH_HOME/maintenance.lock}"
# A durable incident-maintenance fence. Scheduled tasks may invoke keepalive
# while recovery is underway; they must not be able to resurrect a writer tree.
if [[ -e "$MAINTENANCE_LOCK" ]]; then
  echo "[keepalive] maintenance lock present at $MAINTENANCE_LOCK; runner start blocked" >&2
  exit 75
fi
export ORCH_BATCH_DEV_RELEASE="${ORCH_BATCH_DEV_RELEASE:-true}"
export ORCH_CODE_MERGE_TARGET="${ORCH_CODE_MERGE_TARGET:-dev}"
export ORCH_STAGING_BRANCH="${ORCH_STAGING_BRANCH:-orchestrator/dev}"
export ORCH_PUSH_ON_DEV_MERGE="${ORCH_PUSH_ON_DEV_MERGE:-true}"
export ORCH_PUSH_ON_MERGE="${ORCH_PUSH_ON_MERGE:-false}"
export ORCH_PUSH_ON_RELEASE="${ORCH_PUSH_ON_RELEASE:-true}"
export RELEASE_MIN_BATCH="${RELEASE_MIN_BATCH:-10}"
export RELEASE_INTERVAL_HOURS="${RELEASE_INTERVAL_HOURS:-6}"
mkdir -p "$ORCH_LOG_DIR"
RUNNER_LOG="$ORCH_LOG_DIR/runner.log"
LOCK_FILE="$CLAUDE_ORCH_HOME/runner.lock"
SUPERVISOR_LOCK="$CLAUDE_ORCH_HOME/keepalive.lock"
SUPERVISOR_LOG_THROTTLE="${CLAUDE_ORCH_HOME}/keepalive.duplicate.last"
STAY_RESIDENT="${ORCH_KEEPALIVE_STAY_RESIDENT:-false}"
POLL_SECONDS="${ORCH_KEEPALIVE_DUPLICATE_POLL_SECONDS:-60}"

# SINGLE-SUPERVISOR IDEMPOTENCY (2026-08-06). Lock arbitration lives in one sourced helper so
# there is exactly one implementation of "am I allowed to be the supervisor", and so it can be
# tested without booting a real runner. It prefers a kernel-held exclusive flock
# (`zsystem flock` on .runtime/keepalive.lock.flock) which cannot go stale, and falls back to
# the previous mkdir directory lock — now with a grace window — if zsh/system is unavailable.
#
# DOCUMENTED RESET SEQUENCE (wedged fleet -> exactly one clean runner):
#
#     pkill -f keepalive.sh
#     pkill -f runner.py
#     rm -f .runtime/runner.lock
#     rm -rf .runtime/keepalive.lock*
#     (cd runner && nohup bash keepalive.sh &)
#
# The trailing glob matters: the supervisor lock is a family of paths
# (keepalive.lock/, keepalive.lock.flock, keepalive.lock.pid).
export SUPERVISOR_LOCK LOCK_FILE CLAUDE_ORCH_HOME
KA_SOURCED=1
if [[ -r "$RUNNER_DIR/ensure_single_keepalive.sh" ]]; then
  source "$RUNNER_DIR/ensure_single_keepalive.sh"
fi

is_live_runner() {
  if [[ ! -f "$LOCK_FILE" ]]; then
    return 1
  fi
  pid="$(head -n 1 "$LOCK_FILE" 2>/dev/null | sed 's/[^0-9].*$//')"
  if [[ -z "$pid" ]]; then
    return 1
  fi
  if ! ps -p "$pid" >/dev/null 2>&1; then
    return 1
  fi
  # WEDGEFIX-B-WATCHDOG
  prog="$CLAUDE_ORCH_HOME/runner.progress"
  stall="${ORCH_RUNNER_STALL_SECONDS:-1800}"
  if [[ -f "$prog" ]]; then
    now="$(date +%s)"
    mtime="$(stat -f %m "$prog" 2>/dev/null || stat -c %Y "$prog" 2>/dev/null)"
    if [[ -n "$mtime" ]] && (( now - mtime > stall )); then
      echo "[keepalive] runner $pid wedged: no progress $(( now - mtime ))s (>${stall}s) — restarting $(date)" >> "$RUNNER_LOG"
      kill -9 "$pid" 2>/dev/null
      rm -f "$LOCK_FILE"
      return 1
    fi
  fi
  return 0
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
  # Delegates to the shared helper when present so flock and mkdir modes agree on the answer.
  if (( $+functions[ka_supervisor_lock_live] )); then
    ka_supervisor_lock_live
    return $?
  fi
  if [[ ! -d "$SUPERVISOR_LOCK" ]]; then
    return 1
  fi
  sup_pid="$(cat "$SUPERVISOR_LOCK/pid" 2>/dev/null | tr -dc '0-9')"
  [[ -n "$sup_pid" ]] && ps -p "$sup_pid" >/dev/null 2>&1
}

release_supervisor_lock() {
  if (( $+functions[ka_release_supervisor_lock] )); then
    ka_release_supervisor_lock
  else
    rm -rf "$SUPERVISOR_LOCK"
  fi
}

wait_for_runner_release() {
  reason="$1"
  echo "[keepalive] ${reason}; staying resident and polling every ${POLL_SECONDS}s at $(date)" >> "$RUNNER_LOG"
  while is_live_runner; do
    sleep "$POLL_SECONDS"
  done
}

# RESIDENT-JOB-HEAD (2026-08-03): stay_resident is now checked FIRST. Previously a duplicate
# supervisor exited 0 even when STAY_RESIDENT=true. That exit propagated up through the exec
# chain (keepalive.sh <- launcher.sh <- ClaudeRunner) and ended the launchd job head, so
# KeepAlive=true restarted the job ~30s later and launchd SIGKILLed/SIGTERMed the leftover
# process group — which still held the WORKING runner.py and its in-flight agents. With
# TASK_TIMEOUT=900s and a ~12min restart cycle, most agent runs were killed before finishing.
# Staying resident keeps the job head alive so launchd never restarts, so nothing gets killed.
if is_live_runner; then
  if stay_resident; then
    wait_for_runner_release "runner already live via lock $(cat "$LOCK_FILE" 2>/dev/null)"
  elif supervisor_lock_live; then
    echo "[keepalive] runner already live via lock $(cat "$LOCK_FILE" 2>/dev/null); duplicate supervisor exiting at $(date)" >> "$RUNNER_LOG"
    exit 0
  else
    echo "[keepalive] runner already live via lock $(cat "$LOCK_FILE" 2>/dev/null); supervisor exiting at $(date)" >> "$RUNNER_LOG"
    exit 0
  fi
fi

# RESIDENT-JOB-HEAD (2026-08-03): same reasoning as the is_live_runner block above. Losing the
# race for the supervisor lock must NOT end the launchd job head when STAY_RESIDENT=true —
# exiting here is what produced the "duplicate supervisor exit" + launchd-restart + SIGTERM loop.
# Wait for the winning supervisor to go away instead, then take the lock over.
acquire_supervisor_lock() {
  if (( $+functions[ka_acquire_supervisor_lock] )); then
    ka_acquire_supervisor_lock
    return $?
  fi
  # Helper missing (partial checkout): keep the historical mkdir behaviour rather than
  # running with no arbitration at all.
  if mkdir "$SUPERVISOR_LOCK" 2>/dev/null; then
    echo "$$" > "$SUPERVISOR_LOCK/pid" 2>/dev/null
    return 0
  fi
  if supervisor_lock_live; then
    return 1
  fi
  stale="${SUPERVISOR_LOCK}.stale.$$"
  if mv "$SUPERVISOR_LOCK" "$stale" 2>/dev/null; then
    rm -rf "$stale"
    if mkdir "$SUPERVISOR_LOCK" 2>/dev/null; then
      echo "$$" > "$SUPERVISOR_LOCK/pid" 2>/dev/null
      return 0
    fi
  fi
  return 1
}

while ! acquire_supervisor_lock; do
  # Lost the race. STAY_RESIDENT=true must NOT exit here (see RESIDENT-JOB-HEAD above):
  # poll until the winner releases, then take over.
  log_duplicate_exit
  if stay_resident; then
    sleep "$POLL_SECONDS"
    continue
  fi
  exit 0
done
# SUPERVISOR CONSOLIDATION (2026-08-03): this used to be
#   trap 'rm -rf "$SUPERVISOR_LOCK"' EXIT INT TERM
# A TERM/INT trap that does not itself exit makes the script SURVIVE the signal. When launchd
# cycles the job it SIGTERMs the whole process group; the outgoing keepalive lived through it and
# kept holding $SUPERVISOR_LOCK while still owning a working runner.py. The incoming launchd
# keepalive then saw "runner already live via lock" + a live supervisor lock, exited 0, which
# exited ClaudeRunner.app, which made launchd (KeepAlive=true) restart the job 30s later and
# SIGTERM the previous group all over again — 139 launchd runs, 4,276 duplicate-supervisor
# events, and runner.py dying mid-task with code=143. Exiting on the signal makes the outgoing
# supervisor release the lock so the incoming one can take ownership instead of bouncing.
SIGTERM_FORENSICS="${ORCH_LOG_DIR}/sigterm_forensics.log"
# Snapshot enough state to name the sender on the NEXT SIGTERM: launchd suppresses job-level
# entries in the unified log, so the process table + launchd job counters at signal time are the
# decisive evidence. If launchd is cycling the job, `runs` will have incremented and the app pid
# will differ from our own parent; if a peer process is signalling us, it will still be on the
# table (medic/sentinel/mesh all run for seconds at a time).
term_forensics() {
  {
    echo "=== SIGTERM at $(date -u +%FT%TZ) ==="
    echo "keepalive_pid=$$ ppid=$(ps -o ppid= -p $$ 2>/dev/null | tr -d ' ')"
    echo "--- parent chain ---"
    ps -o pid,ppid,lstart,command -p "$(ps -o ppid= -p $$ 2>/dev/null | tr -d ' ')" 2>/dev/null
    echo "--- launchd job ---"
    launchctl print "gui/$(id -u)/com.claudeorchestrator.runner" 2>/dev/null \
      | grep -E 'runs =|^	pid =|last terminating signal|state ='
    echo "--- supervisor-ish processes ---"
    ps -axo pid,ppid,lstart,command 2>/dev/null \
      | grep -E 'ClaudeRunner|keepalive\.sh|runner\.py|sentinel|resource_medic|resilience_mesh|stall' \
      | grep -v grep
    echo
  } >> "$SIGTERM_FORENSICS" 2>/dev/null
}
trap 'release_supervisor_lock' EXIT
trap 'echo "[keepalive] received SIGTERM/SIGINT — releasing supervisor lock and exiting at $(date)" >> "$RUNNER_LOG"; term_forensics; release_supervisor_lock; exit 143' INT TERM

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
  # Stamp the commit this runner is booting on. Without it self_deploy.running_commit()
  # returns "" and check_new_code()["stale"] is ALWAYS False, so self-deploy can never
  # fire and merged code never takes effect until a human restarts the fleet — the exact
  # "sentinel: stale-code-unknown, no .runner_boot_commit" warning seen since 2026-07-16.
  # Written here because this is the single choke point every runner boot passes through.
  _boot_commit="$(git -C "$(dirname "$PWD")" rev-parse HEAD 2>/dev/null || git rev-parse HEAD 2>/dev/null || true)"
  if [ -n "$_boot_commit" ]; then
    printf '%s\n' "$_boot_commit" > "$(dirname "$PWD")/.runner_boot_commit" 2>/dev/null || \
      printf '%s\n' "$_boot_commit" > .runner_boot_commit 2>/dev/null || true
    export ORCH_BOOT_COMMIT="$_boot_commit"
  fi
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
