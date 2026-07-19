"""Tests for runner/prompt_ab_test.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["ORCH_PROMPT_AB_TEST_ENABLED"] = "true"
os.environ["ORCH_AB_MIN_SAMPLES"] = "2"  # Low threshold for test analysis
os.environ["ORCH_DB_URL"] = ""
os.environ["ORCH_SUPABASE_URL"] = ""
os.environ["ORCH_SUPABASE_KEY"] = ""

import prompt_ab_test


def test_assign_variant_returns_a_or_b():
    """assign_variant should return 'A' or 'B'."""
    result = prompt_ab_test.assign_variant("task-abc", "section_order")
    assert result in ("A", "B"), f"Expected 'A' or 'B', got '{result}'"


def test_assign_variant_deterministic():
    """Same task_id + variant_name should always produce the same result."""
    v1 = prompt_ab_test.assign_variant("task-deterministic-42", "instruction_style")
    v2 = prompt_ab_test.assign_variant("task-deterministic-42", "instruction_style")
    v3 = prompt_ab_test.assign_variant("task-deterministic-42", "instruction_style")
    assert v1 == v2 == v3, f"Not deterministic: {v1}, {v2}, {v3}"


def test_apply_variant_returns_string():
    """apply_variant should return a string (the modified prompt)."""
    prompt = "## Task Spec\nFix the bug.\n\n## Constraints\nDo not break tests."
    result = prompt_ab_test.apply_variant(prompt, "task-apply-1")
    assert isinstance(result, str), f"Expected str, got {type(result)}"
    assert len(result) > 0, "Result should not be empty"


def test_record_outcome_and_analyze():
    """record_outcome + analyze should work together without errors."""
    # Record several outcomes to meet min_samples threshold
    for i in range(5):
        tid = f"task-analyze-{i}"
        prompt_ab_test.assign_variant(tid, "section_order")
        prompt_ab_test.record_outcome(tid, success=(i % 2 == 0))

    result = prompt_ab_test.analyze()
    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    assert "experiments" in result, "Missing 'experiments' key"
    assert "winners" in result, "Missing 'winners' key"
    assert isinstance(result["experiments"], list)
