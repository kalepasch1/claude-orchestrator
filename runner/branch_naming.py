"""Branch naming conventions for the orchestrator.

Centralises branch-name generation so that runner, planner, and tests
all agree on the canonical format.
"""


def get_expected_feature_branch_name(project_id: str, task_id: str) -> str:
    """Return a feature branch name in the format ``feature/{projectId}-{taskId}``.

    >>> get_expected_feature_branch_name("project123", "task456")
    'feature/project123-task456'
    """
    return f"feature/{project_id}-{task_id}"


def get_agent_branch_name(slug: str) -> str:
    """Return the standard agent branch name for a task slug.

    >>> get_agent_branch_name("my-task-slug")
    'agent/my-task-slug'
    """
    return f"agent/{slug}"
