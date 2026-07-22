"""
test_helpers.py - Shared test factories and assertions for orchestrator tests.

Provides reusable builders for task and project dicts with sensible defaults,
plus assertion helpers for common state-transition checks.  Import from any
test module:

    from test_helpers import make_task, make_project, assert_valid_transition
"""

import uuid

# ---------------------------------------------------------------------------
# Valid state transitions (source -> set of allowed targets)
# ---------------------------------------------------------------------------
VALID_TRANSITIONS = {
    "QUEUED": {"RUNNING", "SHELVED", "CANCELLED"},
    "RUNNING": {"DONE", "BLOCKED", "CANCELLED"},
    "BLOCKED": {"QUEUED", "SHELVED", "DECOMPOSED", "CANCELLED"},
    "SHELVED": {"QUEUED", "DECOMPOSED", "CANCELLED"},
    "DECOMPOSED": {"CANCELLED"},
    "DONE": set(),
    "CANCELLED": set(),
}

def make_task(
    *,
    state="QUEUED",
    slug=None,
    kind="feature",
    prompt="Implement the feature.",
    note="",
    model="claude-sonnet-4-6",
    material=False,
    priority=50,
    remediation_count=0,
    deps=None,
    project_id="proj-test-1",
    base_branch="main",
    **overrides,
):
    """Return a task dict with sensible defaults.

    Every call generates a unique id/slug pair so tests never collide.
    Override any field via keyword arguments.

    Args:
        state: Task state (QUEUED, RUNNING, BLOCKED, DONE, etc.).
        slug: URL-safe identifier; auto-generated if omitted.        kind: Task kind (feature, bugfix, chore, test, etc.).
        prompt: The task prompt text.
        note: Optional note (often contains error context).
        model: AI model to use.
        material: Whether the task is material (affects routing).
        priority: Priority 0-100 (clamped).
        remediation_count: How many times remediation has been attempted.
        deps: List of dependency task IDs.
        project_id: Owning project identifier.
        base_branch: Git base branch.
        **overrides: Any additional fields merged into the dict.

    Returns:
        dict with all standard task fields populated.
    """
    uid = uuid.uuid4().hex[:8]
    slug = slug or f"test-task-{uid}"
    priority = max(0, min(100, int(priority)))

    task = {
        "id": f"id-{slug}",
        "slug": slug,
        "state": state,
        "kind": kind,
        "prompt": prompt,
        "note": note,
        "model": model,        "material": material,
        "priority": priority,
        "remediation_count": remediation_count,
        "deps": deps or [],
        "project_id": project_id,
        "base_branch": base_branch,
        "log_tail": "",
        "thermal_score": 0,
    }
    task.update(overrides)
    return task


def make_project(
    *,
    name=None,
    repo="https://github.com/example/repo.git",
    base_branch="main",
    active=True,
    **overrides,
):
    """Return a project dict with sensible defaults.

    Args:
        name: Project display name; auto-generated if omitted.
        repo: Git remote URL.
        base_branch: Default branch name.
        active: Whether the project is active.        **overrides: Any additional fields merged into the dict.

    Returns:
        dict with standard project fields populated.
    """
    uid = uuid.uuid4().hex[:8]
    name = name or f"test-project-{uid}"

    project = {
        "id": f"proj-{uid}",
        "name": name,
        "repo": repo,
        "base_branch": base_branch,
        "active": active,
    }
    project.update(overrides)
    return project


def assert_valid_transition(from_state, to_state):
    """Assert that transitioning from *from_state* to *to_state* is allowed.

    Raises AssertionError with a descriptive message on invalid transitions.
    """
    allowed = VALID_TRANSITIONS.get(from_state)
    assert allowed is not None, f"Unknown source state: {from_state!r}"
    assert to_state in allowed, (
        f"Invalid transition {from_state!r} -> {to_state!r}; "        f"allowed targets: {sorted(allowed)}"
    )


def assert_invalid_transition(from_state, to_state):
    """Assert that transitioning from *from_state* to *to_state* is NOT allowed."""
    allowed = VALID_TRANSITIONS.get(from_state, set())
    assert to_state not in allowed, (
        f"Expected {from_state!r} -> {to_state!r} to be invalid, "
        f"but it is in the allowed set"
    )


def assert_task_field(task, field, expected, msg=None):
    """Assert a task dict field equals the expected value."""
    actual = task.get(field)
    msg = msg or f"task[{field!r}] == {actual!r}, expected {expected!r}"
    assert actual == expected, msg