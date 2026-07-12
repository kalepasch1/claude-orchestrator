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


def deduplicate_slug(slug: str, existing_slugs) -> str:
    """Return a unique slug by appending a numeric suffix if *slug* collides.

    Parameters
    ----------
    slug : str
        Candidate slug (e.g. ``"improve-foo-bar"``).
    existing_slugs : set | list
        Collection of slugs that are already in use.

    Returns
    -------
    str
        ``slug`` if no collision, otherwise ``slug + "-2"`` / ``"-3"`` / …

    >>> deduplicate_slug("abc", {"abc", "abc-2"})
    'abc-3'
    >>> deduplicate_slug("abc", set())
    'abc'
    """
    if not slug:
        return slug
    existing = set(existing_slugs) if existing_slugs else set()
    if slug not in existing:
        return slug
    n = 2
    while f"{slug}-{n}" in existing:
        n += 1
    return f"{slug}-{n}"


def validate_slug(slug: str) -> tuple:
    """Validate a task slug against naming conventions.

    Returns (is_valid: bool, reason: str).

    >>> validate_slug("improve-foo-bar")
    (True, '')
    >>> validate_slug("")
    (False, 'slug is empty')
    """
    if not slug:
        return False, "slug is empty"
    if len(slug) > 120:
        return False, "slug exceeds 120 chars"
    import re
    if not re.match(r'^[a-z0-9][a-z0-9\-]*[a-z0-9]$', slug) and len(slug) > 1:
        return False, "slug must be lowercase alphanumeric with hyphens"
    return True, ""
