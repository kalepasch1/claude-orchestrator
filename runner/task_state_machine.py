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
VALID_TRANSITIONS = {
    "QUEUED":      {"RUNNING", "BLOCKED", "SHELVED", "DECOMPOSED"},
    "RUNNING":     {"DONE", "QUEUED", "BLOCKED", "TESTFAIL", "BUILDFAIL"},
    "DONE":        {"MERGED", "QUEUED", "BLOCKED"},
    "MERGED":      set(),  # terminal
    "BLOCKED":     {"QUEUED", "SHELVED"},
    "TESTFAIL":    {"QUEUED", "BLOCKED", "SHELVED"},
    "BUILDFAIL":   {"QUEUED", "BLOCKED", "SHELVED"},
    "SHELVED":     {"QUEUED"},
    "DECOMPOSED":  {"QUEUED"},
    "QUARANTINED": {"QUEUED", "SHELVED"},
}

# Max retries before auto-blocking
MAX_AUTO_RETRIES = int(os.environ.get("ORCH_MAX_AUTO_RETRIES", "3"))


def is_valid_transition(from_state, to_state):
    """Check if a state transition is valid."""
    allowed = VALID_TRANSITIONS.get(from_state, set())
    return to_state in allowed


def transition(task_id, to_state, note_suffix=None, force=False):
    """Perform a validated state transition on a task.

    Args:
        task_id: task ID
        to_state: target state
        note_suffix: optional text to append to the task note
        force: if True, skip validation (for emergency overrides)

    Returns (success: bool, message: str)
    """
    tasks = db.select("tasks", {
        "select": "id,slug,state,note",
        "id": f"eq.{task_id}",
        "limit": "1",
    }) or []

    if not tasks:
        return False, f"task {task_id} not found"

    task = tasks[0]
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
    tasks = db.select("tasks", {
        "select": "id,slug,state,note",
        "id": f"eq.{task_id}",
        "limit": "1",
    }) or []

    if not tasks:
        return "task not found"

    task = tasks[0]
    note = str(task.get("note") or "")

    # Count existing retry attempts from note
    retry_count = note.count("auto-requeue")

    if retry_count >= MAX_AUTO_RETRIES:
        transition(task_id, "BLOCKED",
                   note_suffix=f"auto-blocked after {retry_count} retries: {error_msg[:100]}")
        return f"blocked (retries exhausted: {retry_count})"

    # Transient error patterns
    transient_patterns = ["timeout", "connection", "503", "502", "rate limit",
                          "temporary", "transient", "EAGAIN", "ECONNRESET"]
    is_transient = any(p in error_msg.lower() for p in transient_patterns)

    if is_transient:
        transition(task_id, "QUEUED",
                   note_suffix=f"auto-requeue ({retry_count + 1}/{MAX_AUTO_RETRIES}): {error_msg[:100]}")
        return f"requeued (attempt {retry_count + 1}/{MAX_AUTO_RETRIES})"

    # Non-transient: block immediately
    transition(task_id, "BLOCKED", note_suffix=f"non-transient failure: {error_msg[:100]}")
    return "blocked (non-transient)"


def get_transition_history(task_id):
    """Parse state transition history from a task's note field."""
    tasks = db.select("tasks", {
        "select": "id,slug,state,note",
        "id": f"eq.{task_id}",
        "limit": "1",
    }) or []

    if not tasks:
        return []

    note = str(tasks[0].get("note") or "")
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
