#!/usr/bin/env python3
"""
Test result_classifier.py - verify error_max_turns detection.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'runner'))

import result_classifier


def test_is_error_max_turns_with_exact_metadata():
    """Test that exact error_max_turns metadata is detected."""
    metadata = {
        "type": "result",
        "subtype": "error_max_turns",
        "duration_ms": 7148,
        "duration_api_ms": 7841,
        "is_error": True,
        "num_turns": 2,
        "stop_reason": "tool_use",
        "session_id": "c818384f-c65a-43c2-9ffb-c1b2f5b683dd",
        "total_cost_usd": 0.0348943,
    }
    assert result_classifier.is_error_max_turns(metadata) is True


def test_is_error_max_turns_with_missing_stop_reason():
    """Test that missing stop_reason prevents false positives."""
    metadata = {
        "type": "result",
        "subtype": "error_max_turns",
        "is_error": True,
    }
    assert result_classifier.is_error_max_turns(metadata) is False


def test_is_error_max_turns_with_wrong_subtype():
    """Test that wrong subtype is not detected as error_max_turns."""
    metadata = {
        "type": "result",
        "subtype": "error_other",
        "stop_reason": "tool_use",
    }
    assert result_classifier.is_error_max_turns(metadata) is False


def test_is_error_max_turns_with_normal_result():
    """Test that normal results are not detected as error_max_turns."""
    result = {
        "result": "some code changes",
        "total_cost_usd": 0.1,
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }
    assert result_classifier.is_error_max_turns(result) is False


def test_is_error_max_turns_with_non_dict():
    """Test that non-dict inputs are handled safely."""
    assert result_classifier.is_error_max_turns(None) is False
    assert result_classifier.is_error_max_turns("string") is False
    assert result_classifier.is_error_max_turns([]) is False


def test_classify_error_max_turns():
    """Test classify() recognizes error_max_turns."""
    metadata = {
        "subtype": "error_max_turns",
        "stop_reason": "tool_use",
    }
    result = result_classifier.classify(metadata)
    assert result["type"] == "error_max_turns"
    assert result["is_error"] is True


def test_classify_generic_error():
    """Test classify() recognizes generic errors."""
    error = {
        "is_error": True,
        "message": "some error",
    }
    result = result_classifier.classify(error)
    assert result["type"] == "error"
    assert result["is_error"] is True


def test_classify_task_result():
    """Test classify() recognizes normal task results."""
    result_obj = {
        "result": "code changes",
        "total_cost_usd": 0.1,
    }
    result = result_classifier.classify(result_obj)
    assert result["type"] == "task_result"
    assert result["is_error"] is False


def test_classify_unknown():
    """Test classify() returns unknown for unrecognized objects."""
    unknown = {"foo": "bar"}
    result = result_classifier.classify(unknown)
    assert result["type"] == "unknown"
    assert result["is_error"] is False


if __name__ == "__main__":
    test_is_error_max_turns_with_exact_metadata()
    test_is_error_max_turns_with_missing_stop_reason()
    test_is_error_max_turns_with_wrong_subtype()
    test_is_error_max_turns_with_normal_result()
    test_is_error_max_turns_with_non_dict()
    test_classify_error_max_turns()
    test_classify_generic_error()
    test_classify_task_result()
    test_classify_unknown()
    print("All tests passed!")
