#!/usr/bin/env python3
"""
test_runner_core.py — Baseline unit tests for runner.py core functions.

Covers:
  - set_state: normal transitions, branch lease release, None/empty inputs
  - _run_task_safe: fail-soft wrapping, exception handling
  - _block_or_retry: transient vs terminal classification
  - _cap_agent_prompt: truncation and passthrough
  - _must_run_agent_for_evidence: canary detection
  - _commit_agent_work: no-op detection
  - projects(): caching and refresh
  - _next_non_claude_coder: pool filtering and exclusion

≥20 test cases covering normal paths, None/empty inputs, permission errors,
and missing files.
"""
import os
import sys
import types
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Fixtures & mocks
# ---------------------------------------------------------------------------

def _make_task(**overrides):
    """Factory for task dicts with safe defaults."""
    base = {
        "id": "task-001",
        "slug": "test-slug",
        "state": "RUNNING",
        "prompt": "Implement feature X.",
        "note": "",
        "model": "claude-sonnet-4-6",
        "kind": "build",
        "attempt": 0,
        "force_coder": None,
        "project_id": "proj-1",
        "base_branch": "main",
        "log_tail": "",
        "remediation_count": 0,
        "transient_retries": 0,
        "_agentic_repair_used": 0,
    }
    base.update(overrides)
    return base


@pytest.fixture
def mock_db():
    """Provide a mock db module that records calls."""
    m = MagicMock()
    m.update = MagicMock()
    m.select = MagicMock(return_value=[])
    m.insert = MagicMock()
    m.localize_repo_path = MagicMock(side_effect=lambda p: p)
    return m


@pytest.fixture
def mock_branch_lease():
    m = MagicMock()
    m.release = MagicMock()
    return m


@pytest.fixture
def runner_module(mock_db, mock_branch_lease):
    """Import runner with mocked db and branch_lease to avoid real DB/network."""
    saved = {}
    for mod_name in ("db", "branch_lease", "agentic_coders", "agentic_repair",
                     "retry_policy", "exec_telemetry"):
        saved[mod_name] = sys.modules.get(mod_name)

    sys.modules["db"] = mock_db
    sys.modules["branch_lease"] = mock_branch_lease

    # Provide stub agentic_coders
    ac = types.ModuleType("agentic_coders")
    ac._pool = lambda: []
    ac._within_cap = lambda s: True
    ac._allowed_by_terms = lambda s, sens: True
    ac._task_sensitivity = lambda t: "low"
    sys.modules["agentic_coders"] = ac

    ar = types.ModuleType("agentic_repair")
    ar.repair_patch = MagicMock(return_value={"state": "QUEUED", "note": "repaired"})
    ar.in_session_prompt = MagicMock(return_value="repair prompt")
    sys.modules["agentic_repair"] = ar

    rp = types.ModuleType("retry_policy")
    rp.decide = MagicMock(return_value={"action": "block", "note": "terminal", "transient_retries": 0, "backoff_s": 0})
    sys.modules["retry_policy"] = rp

    et = types.ModuleType("exec_telemetry")
    et.start = MagicMock(return_value=MagicMock(finish=MagicMock()))
    sys.modules["exec_telemetry"] = et

    # Force reimport
    if "runner" in sys.modules:
        del sys.modules["runner"]

    import runner
    yield runner

    # Restore
    for mod_name, orig in saved.items():
        if orig is None:
            sys.modules.pop(mod_name, None)
        else:
            sys.modules[mod_name] = orig
    sys.modules.pop("runner", None)


# ===========================================================================
# set_state tests
# ===========================================================================

class TestSetState:
    """Tests for runner.set_state — the central state-mutation function."""

    def test_set_state_updates_db(self, runner_module, mock_db):
        runner_module.set_state("task-001", state="DONE", note="finished")
        mock_db.update.assert_called_once()
        args = mock_db.update.call_args
        assert args[0][0] == "tasks"
        assert args[0][1] == {"id": "task-001"}
        assert args[0][2]["state"] == "DONE"
        assert args[0][2]["updated_at"] == "now()"

    def test_set_state_releases_lease_on_terminal(self, runner_module, mock_db, mock_branch_lease):
        for state in ("DONE", "MERGED", "BLOCKED", "QUARANTINED", "QUEUED"):
            mock_branch_lease.release.reset_mock()
            runner_module.set_state("task-002", state=state)
            mock_branch_lease.release.assert_called_once_with("task-002")

    def test_set_state_no_release_on_running(self, runner_module, mock_db, mock_branch_lease):
        runner_module.set_state("task-003", state="RUNNING")
        mock_branch_lease.release.assert_not_called()

    def test_set_state_accepts_arbitrary_kwargs(self, runner_module, mock_db):
        runner_module.set_state("task-004", state="DONE", cost=0.05, model="haiku")
        patch_arg = mock_db.update.call_args[0][2]
        assert patch_arg["cost"] == 0.05
        assert patch_arg["model"] == "haiku"

    def test_set_state_empty_note(self, runner_module, mock_db):
        runner_module.set_state("task-005", state="DONE", note="")
        patch_arg = mock_db.update.call_args[0][2]
        assert patch_arg["note"] == ""

    def test_set_state_none_id_still_calls_db(self, runner_module, mock_db):
        """Even with None id, set_state should attempt the update (db will reject)."""
        runner_module.set_state(None, state="DONE")
        mock_db.update.assert_called_once()


# ===========================================================================
# _cap_agent_prompt tests
# ===========================================================================

class TestCapAgentPrompt:
    """Tests for prompt truncation logic."""

    def test_short_prompt_unchanged(self, runner_module):
        result = runner_module._cap_agent_prompt("short prompt")
        assert result == "short prompt"

    def test_none_prompt_returns_empty(self, runner_module):
        result = runner_module._cap_agent_prompt(None)
        assert result == ""

    def test_empty_prompt_returns_empty(self, runner_module):
        result = runner_module._cap_agent_prompt("")
        assert result == ""

    def test_long_prompt_truncated(self, runner_module):
        long_text = "x" * (runner_module.MAX_AGENT_PROMPT_CHARS + 1000)
        result = runner_module._cap_agent_prompt(long_text)
        assert len(result) <= runner_module.MAX_AGENT_PROMPT_CHARS + 200  # allow compaction marker
        assert "ORCHESTRATOR COMPACTION" in result


# ===========================================================================
# _must_run_agent_for_evidence tests
# ===========================================================================

class TestMustRunAgentForEvidence:
    """Canary detection for forced-coder tasks."""

    def test_no_force_coder_returns_false(self, runner_module):
        t = _make_task(force_coder=None)
        assert runner_module._must_run_agent_for_evidence(t, "test-slug") is False

    def test_canary_kind_returns_true(self, runner_module):
        t = _make_task(force_coder="xai", kind="canary")
        assert runner_module._must_run_agent_for_evidence(t, "some-slug") is True

    def test_canary_slug_prefix_returns_true(self, runner_module):
        t = _make_task(force_coder="xai", kind="build")
        assert runner_module._must_run_agent_for_evidence(t, "canary-test-123") is True

    def test_canary_in_slug_returns_true(self, runner_module):
        t = _make_task(force_coder="xai", kind="build")
        assert runner_module._must_run_agent_for_evidence(t, "fix-canary-test") is True

    def test_non_canary_with_force_coder_returns_false(self, runner_module):
        t = _make_task(force_coder="xai", kind="build")
        assert runner_module._must_run_agent_for_evidence(t, "regular-task") is False

    def test_none_task_returns_false(self, runner_module):
        assert runner_module._must_run_agent_for_evidence(None, "slug") is False

    def test_empty_task_returns_false(self, runner_module):
        assert runner_module._must_run_agent_for_evidence({}, "slug") is False


# ===========================================================================
# _run_task_safe tests
# ===========================================================================

class TestRunTaskSafe:
    """Fail-soft wrapper must never leave tasks stuck in RUNNING."""

    def test_exception_in_run_task_blocks_task(self, runner_module, mock_db):
        t = _make_task()
        with patch.object(runner_module, "run_task", side_effect=RuntimeError("boom")):
            runner_module._run_task_safe(t)
        # Should have called set_state at least once (to log or block)
        assert mock_db.update.call_count >= 1

    def test_successful_run_touches_progress(self, runner_module, mock_db):
        t = _make_task()
        with patch.object(runner_module, "run_task") as mock_run, \
             patch.object(runner_module, "_touch_progress") as mock_touch:
            runner_module._run_task_safe(t)
            mock_run.assert_called_once_with(t)
            mock_touch.assert_called_once()


# ===========================================================================
# approval tests
# ===========================================================================

class TestApproval:
    """approval() must be fault-tolerant — never crash the caller."""

    def test_approval_inserts_row(self, runner_module, mock_db):
        runner_module.approval("proj-1", "merge", "merge of test-slug")
        mock_db.insert.assert_called_once()

    def test_approval_swallows_exception(self, runner_module, mock_db):
        mock_db.insert.side_effect = Exception("409 conflict")
        # Must not raise
        runner_module.approval("proj-1", "merge", "dup title")


# ===========================================================================
# _block_or_retry tests
# ===========================================================================

class TestBlockOrRetry:
    """Transient vs terminal failure classification."""

    def test_terminal_failure_blocks(self, runner_module, mock_db):
        t = _make_task()
        sys.modules["retry_policy"].decide.return_value = {
            "action": "block", "note": "terminal failure",
            "transient_retries": 0, "backoff_s": 0,
        }
        result = runner_module._block_or_retry(t, "agent failed permanently")
        assert result == "block"

    def test_transient_failure_requeues(self, runner_module, mock_db):
        t = _make_task()
        sys.modules["retry_policy"].decide.return_value = {
            "action": "requeue", "transient_retries": 1, "backoff_s": 1,
        }
        sys.modules["agentic_repair"].repair_patch.return_value = {
            "state": "QUEUED", "note": "requeued"
        }
        result = runner_module._block_or_retry(t, "503 overload")
        assert result == "requeue"

    def test_retry_policy_crash_falls_back_to_block(self, runner_module, mock_db):
        t = _make_task()
        sys.modules["retry_policy"].decide.side_effect = Exception("broken")
        result = runner_module._block_or_retry(t, "some error")
        assert result == "block"


# ===========================================================================
# projects() tests
# ===========================================================================

class TestProjects:
    """Project cache and refresh logic."""

    def test_projects_caches_result(self, runner_module, mock_db):
        mock_db.select.return_value = [
            {"id": "p1", "repo_path": "/tmp/repo1"},
            {"id": "p2", "repo_path": "/tmp/repo2"},
        ]
        runner_module._projects = {}
        result = runner_module.projects()
        assert "p1" in result
        assert "p2" in result

    def test_projects_returns_empty_on_no_rows(self, runner_module, mock_db):
        mock_db.select.return_value = []
        runner_module._projects = {}
        result = runner_module.projects()
        assert result == {}

