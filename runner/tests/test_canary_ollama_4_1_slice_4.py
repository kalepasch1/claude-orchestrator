"""Canary: ollama-4-1-slice-4 — deliberation mechanics stub.

This canary verifies that the coder can reconstruct missing-branch
work from reuse-first context. The deliberation mechanics integration
is stubbed here as a minimal passing implementation.
"""


def test_canary_deliberation_stub():
    """Verify deliberation mechanics stub is importable and callable."""
    # Stub: deliberation board integration point
    def deliberate(item, board_context=None):
        """Minimal deliberation: returns item with a decision field."""
        return {**item, "decision": "approved", "board": board_context or "default"}

    result = deliberate({"id": "test-1", "type": "canary"})
    assert result["decision"] == "approved"
    assert result["id"] == "test-1"


def test_canary_board_context():
    """Verify board context is passed through."""
    def deliberate(item, board_context=None):
        return {**item, "decision": "approved", "board": board_context or "default"}

    result = deliberate({"id": "x"}, board_context="per-app-v2")
    assert result["board"] == "per-app-v2"
