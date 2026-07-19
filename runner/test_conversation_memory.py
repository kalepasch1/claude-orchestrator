"""Tests for runner/conversation_memory.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["ORCH_CONVERSATION_MEMORY_ENABLED"] = "true"
os.environ["ORCH_DB_URL"] = ""
os.environ["ORCH_SUPABASE_URL"] = ""
os.environ["ORCH_SUPABASE_KEY"] = ""

import conversation_memory


def test_compress_transcript_returns_string():
    """compress_transcript should return a non-empty string with attempt info."""
    output = "Created new file src/main.py\nError: ModuleNotFoundError something broke"
    result = conversation_memory.compress_transcript("task-1", 1, output, "opus", False)
    assert isinstance(result, str), f"Expected str, got {type(result)}"
    assert "Attempt 1" in result
    assert "FAILED" in result


def test_store_and_recall_roundtrip():
    """store() then recall() should return the stored memory entries."""
    tid = "test-roundtrip-123"
    conversation_memory.clear(tid)  # ensure clean state

    conversation_memory.store(tid, 1, "Modified auth.py to fix login bug", "sonnet", False)
    conversation_memory.store(tid, 2, "Fixed tests in test_auth.py", "sonnet", True)

    entries = conversation_memory.recall(tid)
    assert entries is not None, "recall should return entries after store"
    assert len(entries) == 2, f"Expected 2 entries, got {len(entries)}"
    assert entries[0]["attempt"] == 1
    assert entries[1]["attempt"] == 2
    assert entries[1]["success"] is True


def test_inject_memory_adds_content():
    """inject_memory should append prior attempt history to the prompt."""
    tid = "test-inject-456"
    conversation_memory.clear(tid)
    conversation_memory.store(tid, 1, "Edited src/utils.py\nError: ImportError bad import", "opus", False)

    original_prompt = "Fix the bug in auth.py"
    result = conversation_memory.inject_memory(original_prompt, tid)
    assert isinstance(result, str)
    assert original_prompt in result, "Original prompt should be preserved"
    assert "Prior Attempt History" in result, "Should contain memory header"
    assert "different strategy" in result.lower() or "Do NOT repeat" in result


def test_clear_removes_memory():
    """clear() should remove all stored memory for a task."""
    tid = "test-clear-789"
    conversation_memory.store(tid, 1, "Some output", "sonnet", True)
    assert conversation_memory.recall(tid) is not None

    conversation_memory.clear(tid)
    assert conversation_memory.recall(tid) is None


def test_inject_memory_noop_without_history():
    """inject_memory should return prompt unchanged if no history exists."""
    tid = "test-no-history-000"
    conversation_memory.clear(tid)
    prompt = "Do something new"
    result = conversation_memory.inject_memory(prompt, tid)
    assert result == prompt, "Prompt should be unchanged without history"
