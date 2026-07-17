"""Common string utility functions."""


def normalize_whitespace(text):
    """Collapse consecutive whitespace into single spaces and strip edges.

    Returns empty string for None, empty, or whitespace-only input.
    """
    if not text or not isinstance(text, str):
        return ""
    result = " ".join(text.split())
    return result


def is_blank(text):
    """Return True if text is None, empty, or contains only whitespace."""
    if text is None:
        return True
    if not isinstance(text, str):
        return False
    return text.strip() == ""
