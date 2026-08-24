"""
task_state_machine.py — automated task state transition with validation and guards.

Centralizes task state transitions with pre/post conditions, preventing invalid state
changes and automating common transitions (e.g., auto-requeue on transient failures,
auto-block on repeated failures).
"""
import os, sys, logging, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

log = logging.getLogger(__name__)

# Valid state transitions: from_state -> set of allowed to_states
#
# QUARANTINED and SUPERSEDED are reachable, not just leavable. The executors quarantine
# a claimed task whose prompt is binary garbage and supersede one whose work turns out
# to already be done — both from RUNNING, and a drop-box task can be quarantined
# straight out of QUEUED. Those targets were missing here, so the state machine
# rejected transitions the fleet performs every night, and callers routed around it
# with force=True (which skips every other guard too).
VALID_TRANSITIONS = {
    "QUEUED":      {"RUNNING", "BLOCKED", "SHELVED", "DECOMPOSED", "QUARANTINED"},
    "RUNNING":     {"DONE", "QUEUED", "BLOCKED", "TESTFAIL", "BUILDFAIL",
                    "QUARANTINED", "SUPERSEDED"},
    "DONE":        {"MERGED", "QUEUED", "BLOCKED"},
    "MERGED":      set(),  # terminal
    "SUPERSEDED":  set(),  # terminal
    "BLOCKED":     {"QUEUED", "SHELVED"},
    "TESTFAIL":    {"QUEUED", "BLOCKED", "SHELVED"},
    "BUILDFAIL":   {"QUEUED", "BLOCKED", "SHELVED"},
    "SHELVED":     {"QUEUED"},
    "DECOMPOSED":  {"QUEUED"},
    "QUARANTINED": {"QUEUED", "SHELVED"},
}

# Max retries before auto-blocking. Kept as a module constant for back-compat with
# callers that read or monkeypatch it; _max_auto_retries() is what the code uses.
DEFAULT_MAX_AUTO_RETRIES = 3


def _max_auto_retries():
    """Retry ceiling, re-read per call so a fleet push lands without a restart.

    Freezing this at import had two failure modes. ORCH_MAX_AUTO_RETRIES=abc raised
    ValueError while importing, wedging every importer of the state machine — in a
    module whose whole job is to keep the runner moving. And a fleet_control push of
    the key changed nothing until every runner restarted, which is exactly what
    fleet-wide config exists to avoid. Never raises.
    """
    raw = os.environ.get("ORCH_MAX_AUTO_RETRIES")
    if raw is None or not str(raw).strip():
        return MAX_AUTO_RETRIES
    try:
        value = int(str(raw).strip())
        if value < 0:
            raise ValueError(f"must be >= 0, got {value}")
        return value
    except Exception as exc:
        log.warning("task_state_machine: ORCH_MAX_AUTO_RETRIES unusable (%s); using %s",
                    exc, MAX_AUTO_RETRIES)
        return MAX_AUTO_RETRIES


def _env_int(name, default):
    """Import-time env read that degrades to ``default`` instead of raising."""
    try:
        raw = os.environ.get(name)
        return default if raw is None or not str(raw).strip() else int(str(raw).strip())
    except Exception:
        return default


MAX_AUTO_RETRIES = _env_int("ORCH_MAX_AUTO_RETRIES", DEFAULT_MAX_AUTO_RETRIES)


def is_valid_transition(from_state, to_state):
    """Check if a state transition is valid. Never raises on odd input."""
    try:
        allowed = VALID_TRANSITIONS.get(from_state, set())
        return to_state in allowed
    except Exception:
        return False


def _fetch_task(task_id):
    """Read one task row. Returns None when absent or when the DB is unreachable."""
    try:
        rows = db.select("tasks", {
            "select": "id,slug,state,note",
            "id": f"eq.{task_id}",
            "limit": "1",
        }) or []
    except Exception as exc:
        log.warning("task_state_machine: task lookup failed for %s: %s", task_id, exc)
        return None
    return rows[0] if rows else None


def transition(task_id, to_state, note_suffix=None, force=False):
    """Perform a validated state transition on a task.

    Args:
        task_id: task ID
        to_state: target state
        note_suffix: optional text to append to the task note
        force: if True, skip validation (for emergency overrides)

    Returns (success: bool, message: str)
    """
    task = _fetch_task(task_id)
    if not task:
        return False, f"task {task_id} not found"

    from_state = task.get("state", "")

    if not force and not is_valid_transition(from_state, to_state):
        msg = f"invalid transition {from_state} -> {to_state} for {task.get('slug')}"
        log.warning("task_state_machine: %s", msg)
        return False, msg

    patch = {"state": to_state}
    if note_suffix:
        existing_note = str(task.get("note") or "")
        patch["note"] = f"{existing_note} | {note_suffix}" if existing_note else note_suffix

    try:
        db.update("tasks", patch, id=task_id)
        log.info("task_state_machine: %s -> %s for %s", from_state, to_state, task.get("slug"))
        return True, f"{from_state} -> {to_state}"
    except Exception as e:
        return False, f"update failed: {e}"


def auto_requeue_on_transient(task_id, error_msg):
    """Requeue a task if the failure is transient, block if retries exhausted.

    Returns (action_taken: str).
    """
    task = _fetch_task(task_id)
    if not task:
        return "task not found"

    note = str(task.get("note") or "")

    # A crashed runner reports no message at all; coercing here keeps the classifier
    # from dying on `None.lower()` at precisely the moment a task needs rescuing.
    error_msg = "" if error_msg is None else str(error_msg)

    # Count existing retry attempts from note
    retry_count = note.count("auto-requeue")
    max_retries = _max_auto_retries()

    if retry_count >= max_retries:
        transition(task_id, "BLOCKED",
                   note_suffix=f"auto-blocked after {retry_count} retries: {error_msg[:100]}")
        return f"blocked (retries exhausted: {retry_count})"

    # Transient error patterns
    transient_patterns = ["timeout", "connection", "503", "502", "rate limit",
                          "temporary", "transient", "eagain", "econnreset"]
    lowered = error_msg.lower()
    is_transient = any(p in lowered for p in transient_patterns)

    if is_transient:
        transition(task_id, "QUEUED",
                   note_suffix=f"auto-requeue ({retry_count + 1}/{max_retries}): {error_msg[:100]}")
        return f"requeued (attempt {retry_count + 1}/{max_retries})"

    # Non-transient: block immediately
    transition(task_id, "BLOCKED", note_suffix=f"non-transient failure: {error_msg[:100]}")
    return "blocked (non-transient)"


def get_transition_history(task_id):
    """Parse state transition history from a task's note field."""
    task = _fetch_task(task_id)
    if not task:
        return []

    note = str(task.get("note") or "")
    transitions = []
    for part in note.split("|"):
        part = part.strip()
        if "->" in part:
            transitions.append(part)
    return transitions


if __name__ == "__main__":
    # Print valid transitions
    import json
    print(json.dumps({k: sorted(v) for k, v in VALID_TRANSITIONS.items()}, indent=2))
