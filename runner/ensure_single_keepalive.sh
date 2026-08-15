#!/bin/zsh
# ensure_single_keepalive.sh - the one place that decides "am I allowed to be the supervisor".
#
# WHY THIS EXISTS
# keepalive.sh used to arbitrate with a bare `mkdir "$SUPERVISOR_LOCK"` directory lock. mkdir
# is atomic, but the *pid stamp* written immediately afterwards is not part of that atomic
# step, so there is a real window:
#
#     A: mkdir keepalive.lock            -> wins
#     B: supervisor_lock_live()          -> dir exists, pid file empty  => "stale"
#     B: mv keepalive.lock keepalive.stale; rm -rf; loop; mkdir -> ALSO wins
#     A: echo $$ > keepalive.lock/pid    -> writes into a directory that no longer exists
#
# Both supervisors then proceed and each spawns runner.py. runner.py's own singleton lock
# usually catches the second one, but "usually" is doing a lot of work there — and when the
# loser exits it takes the launchd job head with it, which is the restart/SIGTERM loop
# documented at the top of keepalive.sh.
#
# The fix is a genuinely exclusive advisory lock held by the kernel for the lifetime of the
# process: zsh's `zsystem flock` (zsh/system module, present on stock macOS zsh). The lock is
# released automatically when the shell exits, including on SIGKILL, so it cannot go stale.
# The mkdir path is kept only as a fallback for a zsh built without zsh/system, and is
# hardened with a grace period so the window above closes there too.
#
# ---------------------------------------------------------------------------------------
# DOCUMENTED RESET SEQUENCE (use this when the fleet is wedged and you want one clean runner):
#
#     pkill -f keepalive.sh
#     pkill -f runner.py
#     rm -f .runtime/runner.lock
#     rm -rf .runtime/keepalive.lock*
#     (cd runner && nohup bash keepalive.sh &)
#
# The `keepalive.lock*` glob is deliberate: the lock is a small family of files
# (keepalive.lock/ dir for the fallback path, keepalive.lock.flock, keepalive.lock.pid).
# ---------------------------------------------------------------------------------------
#
# Usable two ways:
#   source ensure_single_keepalive.sh          -> provides ka_* functions
#   ensure_single_keepalive.sh <subcommand>    -> direct invocation, used by the tests
#
# Subcommands:
#   acquire-and-hold [seconds]   acquire, print ACQUIRED, hold for N seconds (default 2), exit 0
#                                 or print BUSY and exit 75 if another supervisor holds it
#   runner-live                  print live|dead based on the runner.lock pid, exit 0|1

: "${CLAUDE_ORCH_HOME:=${HOME}/.claude-orchestrator}"
: "${SUPERVISOR_LOCK:=${CLAUDE_ORCH_HOME}/keepalive.lock}"
: "${LOCK_FILE:=${CLAUDE_ORCH_HOME}/runner.lock}"

# How long a freshly created fallback lock directory is trusted without a pid stamp yet.
: "${ORCH_KEEPALIVE_LOCK_GRACE_SECONDS:=15}"

KEEPALIVE_LOCK_KIND=""

_ka_flock_available() {
  [[ "${ORCH_KEEPALIVE_FORCE_MKDIR_LOCK:-0}" == 1 ]] && return 1
  zmodload zsh/system 2>/dev/null || return 1
  zsystem supports flock 2>/dev/null || return 1
  return 0
}

_ka_mtime() {
  stat -f %m "$1" 2>/dev/null || stat -c %Y "$1" 2>/dev/null
}

# Is a legacy mkdir holder live? Kept separate so a newly upgraded flock-based supervisor
# cannot overlap an already-running pre-upgrade supervisor during rollout.
_ka_legacy_lock_live() {
  [[ -d "$SUPERVISOR_LOCK" ]] || return 1
  local sup_pid
  sup_pid="$(cat "$SUPERVISOR_LOCK/pid" 2>/dev/null | tr -dc '0-9')"
  if [[ -n "$sup_pid" ]]; then
    ps -p "$sup_pid" >/dev/null 2>&1 && return 0
    return 1
  fi
  # No pid stamp yet: a peer may be mid-acquire. Trust it for the grace window rather than
  # racing it for the lock — this is the exact window that let two supervisors both "win".
  local mtime now
  mtime="$(_ka_mtime "$SUPERVISOR_LOCK")"
  now="$(date +%s)"
  [[ -n "$mtime" ]] && (( now - mtime < ORCH_KEEPALIVE_LOCK_GRACE_SECONDS )) && return 0
  return 1
}

# Is some OTHER process currently holding the supervisor lock?
ka_supervisor_lock_live() {
  if _ka_flock_available && [[ -e "${SUPERVISOR_LOCK}.flock" ]]; then
    # A held flock cannot be taken; a released one can. Probe with a throwaway fd.
    if ! zsystem flock -t 0 -f _ka_probe_fd "${SUPERVISOR_LOCK}.flock" 2>/dev/null; then
      return 0
    fi
    zsystem flock -u "$_ka_probe_fd" 2>/dev/null
    unset _ka_probe_fd
  fi
  _ka_legacy_lock_live
}

# Try to become the supervisor. 0 = we hold the lock, 1 = someone else does.
ka_acquire_supervisor_lock() {
  mkdir -p "${SUPERVISOR_LOCK:h}" 2>/dev/null
  if _ka_flock_available; then
    if _ka_legacy_lock_live; then
      return 1
    fi
    # Remove only a provably stale legacy lock before switching lock mechanisms.
    if [[ -d "$SUPERVISOR_LOCK" ]]; then
      local stale="${SUPERVISOR_LOCK}.stale.$$"
      mv "$SUPERVISOR_LOCK" "$stale" 2>/dev/null && rm -rf "$stale"
    fi
    : >> "${SUPERVISOR_LOCK}.flock" 2>/dev/null
    if zsystem flock -t 0 -f KEEPALIVE_LOCK_FD "${SUPERVISOR_LOCK}.flock" 2>/dev/null; then
      print -r -- "$$" > "${SUPERVISOR_LOCK}.pid" 2>/dev/null
      KEEPALIVE_LOCK_KIND=flock
      return 0
    fi
    return 1
  fi

  # Fallback: atomic mkdir + immediate pid stamp, with stale takeover only when the holder
  # is provably gone (dead pid, or no pid stamp after the grace window).
  if mkdir "$SUPERVISOR_LOCK" 2>/dev/null; then
    print -r -- "$$" > "$SUPERVISOR_LOCK/pid" 2>/dev/null
    KEEPALIVE_LOCK_KIND=mkdir
    return 0
  fi
  if ka_supervisor_lock_live; then
    return 1
  fi
  local stale="${SUPERVISOR_LOCK}.stale.$$"
  if mv "$SUPERVISOR_LOCK" "$stale" 2>/dev/null; then
    rm -rf "$stale"
    if mkdir "$SUPERVISOR_LOCK" 2>/dev/null; then
      print -r -- "$$" > "$SUPERVISOR_LOCK/pid" 2>/dev/null
      KEEPALIVE_LOCK_KIND=mkdir
      return 0
    fi
  fi
  return 1
}

ka_release_supervisor_lock() {
  if [[ "$KEEPALIVE_LOCK_KIND" == flock ]]; then
    [[ -n "$KEEPALIVE_LOCK_FD" ]] && zsystem flock -u "$KEEPALIVE_LOCK_FD" 2>/dev/null
    rm -f "${SUPERVISOR_LOCK}.pid" 2>/dev/null
  fi
  rm -rf "$SUPERVISOR_LOCK" 2>/dev/null
  KEEPALIVE_LOCK_KIND=""
}

# Does .runtime/runner.lock name a process that is actually alive?
ka_runner_lock_live() {
  [[ -f "$LOCK_FILE" ]] || return 1
  local pid
  pid="$(head -n 1 "$LOCK_FILE" 2>/dev/null | sed 's/[^0-9].*$//')"
  [[ -n "$pid" ]] || return 1
  ps -p "$pid" >/dev/null 2>&1
}

# Direct invocation (tests). keepalive.sh sets KA_SOURCED=1 before sourcing, which is a far
# more reliable signal than trying to infer sourcing from $0 / ZSH_EVAL_CONTEXT.
if [[ -z "${KA_SOURCED:-}" ]]; then
  case "${1:-}" in
    acquire-and-hold)
      if ka_acquire_supervisor_lock; then
        print -r -- "ACQUIRED $$ ${KEEPALIVE_LOCK_KIND}"
        sleep "${2:-2}"
        ka_release_supervisor_lock
        exit 0
      fi
      print -r -- "BUSY $$"
      exit 75
      ;;
    runner-live)
      if ka_runner_lock_live; then print -r -- live; exit 0; fi
      print -r -- dead; exit 1
      ;;
    *)
      print -r -- "usage: ensure_single_keepalive.sh {acquire-and-hold [seconds]|runner-live}" >&2
      exit 2
      ;;
  esac
fi
