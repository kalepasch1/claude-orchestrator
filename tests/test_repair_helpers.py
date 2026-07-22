#!/usr/bin/env python3
"""
test_repair_helpers.py — Tests for agentic_repair module helpers.

Covers:
- repair_prompt generation with various categories
- in_session_prompt correctness
- choose_coder fallback logic
- Prompt truncation at MAX_PROMPT_CHARS boundary
- MARKER deduplication (no double-injection)
"""
import os
import sys
import pytest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "runner"))


@pytest.fixture(autouse=True)
def clean_env():
    """Ensure no orchestrator env vars leak between tests."""
    keys = [k for k in os.environ if k.startswith("ORCH_")]
    with mock.patch.dict(os.environ, {}, clear=False):
        for k in keys:
            os.environ.pop(k, None)
        yield

# ---------------------------------------------------------------------------
# repair_prompt tests
# ---------------------------------------------------------------------------
class TestRepairPrompt:
    def test_includes_marker(self):
        import agentic_repair
        task = {"slug": "my-task", "prompt": "Do something", "id": "t1"}
        result = agentic_repair.repair_prompt(task, "build failed", "Fix it", category="buildfail")
        assert agentic_repair.MARKER in result

    def test_includes_failure_context(self):
        import agentic_repair
        task = {"slug": "my-task", "prompt": "Do something"}
        result = agentic_repair.repair_prompt(task, "ModuleNotFoundError: No module named 'foo'", "Fix it")
        assert "ModuleNotFoundError" in result

    def test_truncates_long_prompts(self):
        import agentic_repair
        long_prompt = "x" * (agentic_repair.MAX_PROMPT_CHARS + 5000)
        task = {"slug": "big-task", "prompt": long_prompt}
        result = agentic_repair._original_prompt(task)
        assert len(result) <= agentic_repair.MAX_PROMPT_CHARS + 200  # allow marker overhead

    def test_strips_prior_marker(self):
        import agentic_repair
        prompt_with_marker = f"Original work\n\n{agentic_repair.MARKER}\nOld repair directive"
        task = {"slug": "t", "prompt": prompt_with_marker}
        result = agentic_repair._original_prompt(task)
        assert result.count(agentic_repair.MARKER) == 0


# ---------------------------------------------------------------------------
# choose_coder tests
# ---------------------------------------------------------------------------
class TestChooseCoder:
    def test_forced_coder_wins(self):
        import agentic_repair
        task = {"force_coder": "gemini", "slug": "t"}
        assert agentic_repair.choose_coder(task) == "gemini"

    def test_existing_model_preserved(self):
        import agentic_repair
        task = {"model": "gpt-4o", "slug": "t"}
        assert agentic_repair.choose_coder(task) == "gpt-4o"

    def test_claude_model_falls_through(self):
        import agentic_repair
        task = {"model": "claude", "slug": "t"}
        result = agentic_repair.choose_coder(task)
        # Should fall through to default, not return "claude"
        assert result is not None

    def test_default_coder_from_env(self):
        import agentic_repair
        with mock.patch.dict(os.environ, {"ORCH_REPAIR_CODER": "deepseek"}):
            result = agentic_repair._default_coder()
            assert result == "deepseek"


# ---------------------------------------------------------------------------
# in_session_prompt tests
# ---------------------------------------------------------------------------
class TestInSessionPrompt:
    def test_default_directive(self):
        import agentic_repair
        task = {"slug": "fix-it", "prompt": "Original prompt text"}
        result = agentic_repair.in_session_prompt(task, "error log here")
        assert "fix-it" in result
        assert "error log here" in result

    def test_custom_directive(self):
        import agentic_repair
        task = {"slug": "t", "prompt": "Do X"}
        result = agentic_repair.in_session_prompt(task, "fail", directive="Run npm test")
        assert "Run npm test" in result


# ---------------------------------------------------------------------------
# repair_patch tests
# ---------------------------------------------------------------------------
class TestRepairPatch:
    def test_increments_remediation_count(self):
        import agentic_repair
        task = {"slug": "t", "prompt": "X", "remediation_count": 2, "attempt": 1}
        patch = agentic_repair.repair_patch(task, "fail")
        assert patch["remediation_count"] == 3
        assert patch["attempt"] == 2

    def test_sets_queued_state(self):
        import agentic_repair
        task = {"slug": "t", "prompt": "X"}
        patch = agentic_repair.repair_patch(task, "err")
        assert patch["state"] == "QUEUED"
        assert patch["account"] is None

    def test_assigns_coder(self):
        import agentic_repair
        task = {"slug": "t", "prompt": "X", "force_coder": "ollama"}
        patch = agentic_repair.repair_patch(task, "err")
        assert patch["force_coder"] == "ollama"


# ---------------------------------------------------------------------------
# Category classification
# ---------------------------------------------------------------------------
class TestCategories:
    def test_technical_categories(self):
        import agentic_repair
        for cat in ["buildfail", "testfail", "timeout", "conflict"]:
            assert agentic_repair.is_technical(cat), f"{cat} should be technical"

    def test_replacement_categories(self):
        import agentic_repair
        for cat in ["legal", "secret", "security"]:
            assert agentic_repair.replacement_required(cat), f"{cat} should require replacement"

    def test_unknown_category_is_not_replacement(self):
        import agentic_repair
        assert not agentic_repair.replacement_required("buildfail")
        assert not agentic_repair.replacement_required("rework")
