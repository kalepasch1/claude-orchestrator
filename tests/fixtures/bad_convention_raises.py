"""
Bad convention example: Public function raises without proper error handling.

This module violates the fail-soft error handling convention.
CLAUDE.md states: "Return empty string "" or sensible defaults on any error;
never raise on bad input"
"""


def process_input(data):
    """VIOLATION: Public function raises without try/except handler."""
    if not data:
        raise ValueError("Data cannot be empty")
    return transform(data)


def load_file(path):
    """VIOLATION: Public function raises without handling bad paths."""
    with open(path) as f:
        return json.load(f)


def fetch_data():
    """VIOLATION: Function raises on network error without handler."""
    raise RuntimeError("Network error")


def analyze():
    """VIOLATION: Empty except handler (no return statement)."""
    try:
        expensive_operation()
    except Exception:
        pass  # No return - violation


def transform(value):
    """OK: Private function can raise."""
    if value < 0:
        raise ValueError("Negative values not allowed")
    return value * 2
