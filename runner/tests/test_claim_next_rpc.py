"""Tests for claim_next RPC path, fallback, and flag-off behavior."""
import os
import sys
import types
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Ensure ORCH_CLAIM_RPC is unset by default."""
    monkeypatch.delenv("ORCH_CLAIM_RPC", raising=False)


def _make_task_row():
    return {
        "id": "abc-123",
        "slug": "test-task-1",
        "project_id": "proj-1",
        "state": "RUNNING",
        "account": "test-runner",
        "kind": "bugfix",
        "deps": None,
        "confidence": 0.9,
        "created_at": "2026-07-18T00:00:00Z",
    }


class TestClaimViaRpc:
    """Unit tests for _claim_via_rpc."""

    def test_flag_off_returns_none(self, monkeypatch):
        """When ORCH_CLAIM_RPC is not set (default false), returns None immediately."""
        import db
        result = db._claim_via_rpc("test-runner")
        assert result is None

    def test_flag_on_calls_rpc(self, monkeypatch):
        """When ORCH_CLAIM_RPC=true, calls rpc('claim_next', ...) and returns result."""
        monkeypatch.setenv("ORCH_CLAIM_RPC", "true")
        import db
        task = _make_task_row()
        with patch.object(db, "rpc", return_value=[task]) as mock_rpc, \
             patch.object(db, "select", return_value=[{"id": "proj-1", "repo_path": "/tmp/fake"}]), \
             patch.object(db, "repo_runnable_here", return_value=True):
            result = db._claim_via_rpc("test-runner")
            assert result == task
            mock_rpc.assert_called_once()
            call_args = mock_rpc.call_args
            assert call_args[0][0] == "claim_next"
            assert call_args[0][1]["p_runner_id"] == "test-runner"

    def test_flag_on_rpc_empty_returns_none(self, monkeypatch):
        """When RPC returns empty list, returns None."""
        monkeypatch.setenv("ORCH_CLAIM_RPC", "true")
        import db
        with patch.object(db, "rpc", return_value=[]), \
             patch.object(db, "select", return_value=[]), \
             patch.object(db, "repo_runnable_here", return_value=True):
            result = db._claim_via_rpc("test-runner")
            assert result is None

    def test_rpc_error_falls_back(self, monkeypatch):
        """When RPC raises, returns None (caller falls back to scan path)."""
        monkeypatch.setenv("ORCH_CLAIM_RPC", "true")
        import db
        with patch.object(db, "rpc", side_effect=Exception("connection refused")), \
             patch.object(db, "select", return_value=[]):
            result = db._claim_via_rpc("test-runner")
            assert result is None

    def test_host_affinity_passes_runnable_projects(self, monkeypatch):
        """Runnable project IDs are passed to the RPC for host affinity."""
        monkeypatch.setenv("ORCH_CLAIM_RPC", "true")
        import db
        task = _make_task_row()
        with patch.object(db, "rpc", return_value=[task]) as mock_rpc, \
             patch.object(db, "select", return_value=[
                 {"id": "proj-1", "repo_path": "/tmp/exists"},
                 {"id": "proj-2", "repo_path": "/tmp/missing"},
             ]), \
             patch.object(db, "repo_runnable_here", side_effect=lambda p: p == "/tmp/exists"):
            result = db._claim_via_rpc("test-runner")
            assert result == task
            call_args = mock_rpc.call_args[0][1]
            assert call_args["p_runnable_projects"] == ["proj-1"]


class TestClaimTaskFlagOff:
    """Verify that claim_task with flag off uses the unchanged scan path."""

    def test_flag_off_uses_scan_path(self, monkeypatch):
        """With ORCH_CLAIM_RPC unset, _claim_via_rpc returns None and scan path runs."""
        import db
        with patch.object(db, "_claim_via_rpc", return_value=None) as mock_rpc:
            # The scan path will also return None (no tasks), but we verify
            # the RPC path was checked and returned None.
            with patch.object(db, "select", return_value=[]):
                result = db.claim_task("test-runner")
                mock_rpc.assert_called_once_with("test-runner")
                assert result is None
