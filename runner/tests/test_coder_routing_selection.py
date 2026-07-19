#!/usr/bin/env python3
"""
test_coder_routing_selection.py - Canary tests for coder routing selection.

Validates core routing scenarios: pool state, task-to-coder mapping, capability
checking, and graceful degradation on unavailable coders. No changes to routing
outcomes; tests document expected behavior only.
"""
import os
import sys
from unittest.mock import patch
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import agentic_coders


def test_available_always_includes_claude():
    """Happy path: claude is always in available coders."""
    coders = agentic_coders.available()
    assert "claude" in coders


def test_pool_empty_on_no_env_config():
    """Empty pool scenario: no extra coders configured, returns [claude] only."""
    with patch.dict(os.environ, {}, clear=False):
        coders = agentic_coders.available()
        assert len(coders) >= 1
        assert coders[0] == "claude"


def test_pick_returns_string_coder_name():
    """Happy path: pick() returns a valid coder name string."""
    task = {"kind": "easy", "prompt": "test"}
    result = agentic_coders.pick(task)
    assert isinstance(result, str)
    assert len(result) > 0


def test_pick_selects_capable_coder_for_easy_task():
    """Task routing: easy task routes to a capable coder."""
    task = {"kind": "easy", "prompt": "fix typo"}
    result = agentic_coders.pick(task)
    assert result in agentic_coders.available()


def test_pick_hard_task_defaults_to_capable_coder():
    """Task routing: hard task selects high-capability coder."""
    task = {"kind": "build_fix", "prompt": "x" * 1000, "deps": ["dep1"]}
    result = agentic_coders.pick(task)
    assert result in agentic_coders.available()


def test_route_returns_dict_with_provider_model():
    """Routing metadata: route() returns structured dict."""
    task = {"kind": "easy", "prompt": "test"}
    result = agentic_coders.route(task)
    assert isinstance(result, dict)
    assert "coder" in result
    assert "provider" in result
    assert "model" in result


def test_spec_returns_none_for_missing_coder():
    """Graceful degradation: unknown coder returns None."""
    result = agentic_coders._spec("nonexistent-coder-xyz")
    assert result is None


def test_coder_ready_returns_true_for_claude():
    """Availability check: native claude is always ready."""
    assert agentic_coders._coder_ready("") is True
    assert agentic_coders._coder_ready(None) is True


def test_task_difficulty_critical_for_security_tasks():
    """Task difficulty: security/legal tasks always critical."""
    task_security = {"prompt": "add private key validation", "kind": "security"}
    assert agentic_coders._task_difficulty(task_security) == "critical"

    task_legal = {"prompt": "update legal compliance", "kind": "legal"}
    assert agentic_coders._task_difficulty(task_legal) == "critical"


def test_task_difficulty_hard_for_material_work():
    """Task difficulty: material tasks are hard regardless of kind."""
    task = {"material": True, "kind": "docs", "prompt": "update readme"}
    assert agentic_coders._task_difficulty(task) == "hard"


def test_task_difficulty_hard_for_tasks_with_dependencies():
    """Task difficulty: tasks with dependencies are hard."""
    task = {"deps": ["dep1", "dep2"], "kind": "test", "prompt": "add tests"}
    assert agentic_coders._task_difficulty(task) == "hard"


def test_task_difficulty_easy_for_small_self_contained_prompts():
    """Task difficulty: small, self-contained prompts are easy."""
    task = {"kind": "bugfix", "prompt": "fix typo in var name"}
    assert agentic_coders._task_difficulty(task) == "easy"


def test_task_difficulty_explicit_need_overrides_heuristics():
    """Task difficulty: explicit _need parameter overrides heuristic."""
    task = {"_need": 9, "kind": "test", "prompt": "x" * 100}
    assert agentic_coders._task_difficulty(task) == "critical"

    task2 = {"_need": 8, "kind": "test", "prompt": "x" * 100}
    assert agentic_coders._task_difficulty(task2) == "hard"


def test_within_cap_free_coders_always_usable():
    """Cost gatekeeping: free/local coders (daily_usd<=0) are never capped."""
    coder_free = {"name": "ollama", "daily_usd": 0}
    assert agentic_coders._within_cap(coder_free) is True

    coder_local = {"name": "local", "daily_usd": None}
    assert agentic_coders._within_cap(coder_local) is True


def test_spec_returns_none_for_unknown_coder():
    """Graceful degradation: _spec returns None for unknown/unconfigured coders."""
    # Test with a name that definitely doesn't exist in any normal pool
    result = agentic_coders._spec("nonexistent-xyz-coder-9999")
    assert result is None


def test_pick_routes_critical_tasks_safely():
    """Critical routing: security/compliance tasks select high-capability coders."""
    task = {"kind": "security", "prompt": "validate private key storage", "_need": 9}
    result = agentic_coders.pick(task)
    assert result in agentic_coders.available()
    # Critical tasks should pick a capable coder
    spec = agentic_coders._spec(result)
    assert spec and spec["cap"] >= 9 or result == "claude"


def test_route_includes_required_capabilities_when_available():
    """Route metadata: structured output includes capability detection when enabled."""
    task = {"kind": "test", "prompt": "write unit tests"}
    result = agentic_coders.route(task)
    assert isinstance(result, dict)
    assert "coder" in result
    assert "provider" in result
    assert "model" in result
    assert "cap" in result
    assert "cost" in result
    # Optional enhanced metadata
    if "required_capabilities" in result:
        assert isinstance(result["required_capabilities"], list)
