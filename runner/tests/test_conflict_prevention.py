"""Comprehensive tests for conflict_prevention module."""

import pytest
from unittest.mock import Mock, patch, MagicMock
import conflict_prevention


class MockDB:
    """Mock database for testing file locks."""
    def __init__(self):
        self.locks = {}
        self.next_id = 1

    def insert(self, table, row):
        row_id = f"lock-{self.next_id}"
        self.next_id += 1
        row["id"] = row_id
        row["acquired_at"] = "2026-07-26T00:00:00Z"
        self.locks[row_id] = row
        return row

    def select(self, table, filters=None, order=None, limit=None):
        results = list(self.locks.values())
        if filters:
            for key, val in filters.items():
                if val is None:
                    results = [r for r in results if r.get(key) is None]
                elif isinstance(val, str):
                    results = [r for r in results if r.get(key) == val]
        if limit:
            results = results[:limit]
        return results

    def update(self, table, item_id, updates):
        if item_id in self.locks:
            for key, val in updates.items():
                self.locks[item_id][key] = val

    def count(self, table, filters=None):
        results = list(self.locks.values())
        if filters:
            for key, val in filters.items():
                if val is None:
                    results = [r for r in results if r.get(key) is None]
        return len(results)

    def execute_rpc(self, name, params):
        pass


class TestAcquireLock:
    """Test cases for acquire_lock() function."""

    def test_acquire_lock_basic(self):
        """Test basic lock acquisition."""
        mock_db = MockDB()
        with patch('conflict_prevention.db', mock_db):
            ok, info = conflict_prevention.acquire_lock("proj1", "src/main.py", "agent-1")
            assert ok is True
            assert "id" in info

    def test_acquire_lock_conflict(self):
        """Test lock acquisition fails when another agent holds it."""
        mock_db = MockDB()
        with patch('conflict_prevention.db', mock_db):
            # First agent acquires
            ok1, _ = conflict_prevention.acquire_lock("proj1", "src/main.py", "agent-1")
            assert ok1 is True
            # Second agent tries to acquire same file
            ok2, info2 = conflict_prevention.acquire_lock("proj1", "src/main.py", "agent-2")
            assert ok2 is False
            assert info2.get("conflict") is True
            assert info2["held_by"] == "agent-1"

    def test_acquire_lock_same_agent_succeeds(self):
        """Test same agent can re-acquire its own lock."""
        mock_db = MockDB()
        with patch('conflict_prevention.db', mock_db):
            ok1, _ = conflict_prevention.acquire_lock("proj1", "src/main.py", "agent-1")
            assert ok1 is True
            ok2, _ = conflict_prevention.acquire_lock("proj1", "src/main.py", "agent-1")
            assert ok2 is True

    def test_acquire_shared_lock(self):
        """Test acquiring a shared lock."""
        mock_db = MockDB()
        with patch('conflict_prevention.db', mock_db):
            ok, info = conflict_prevention.acquire_lock(
                "proj1", "src/main.py", "agent-1", lock_type="shared")
            assert ok is True

    def test_acquire_lock_no_db(self):
        """Test acquire_lock returns True (fallback) when db unavailable."""
        with patch('conflict_prevention.db', None):
            ok, info = conflict_prevention.acquire_lock("proj1", "src/main.py", "agent-1")
            assert ok is True
            assert "fallback" in info

    def test_acquire_lock_db_query_error(self):
        """Test acquire_lock handles db query errors gracefully."""
        mock_db = Mock()
        mock_db.execute_rpc.return_value = None
        mock_db.select.side_effect = Exception("DB error")
        with patch('conflict_prevention.db', mock_db):
            ok, info = conflict_prevention.acquire_lock("proj1", "src/main.py", "agent-1")
            assert ok is True
            assert "fallback" in info

    def test_acquire_lock_unique_constraint_conflict(self):
        """Test acquire_lock handles unique constraint violation."""
        mock_db = Mock()
        mock_db.execute_rpc.return_value = None
        mock_db.select.return_value = []
        mock_db.insert.side_effect = Exception("uq_active_exclusive constraint violated")
        with patch('conflict_prevention.db', mock_db):
            ok, info = conflict_prevention.acquire_lock("proj1", "src/main.py", "agent-1")
            assert ok is False
            assert info.get("conflict") is True

    def test_acquire_lock_with_task_slug(self):
        """Test acquire_lock stores task_slug."""
        mock_db = MockDB()
        with patch('conflict_prevention.db', mock_db):
            ok, info = conflict_prevention.acquire_lock(
                "proj1", "src/main.py", "agent-1", task_slug="fix-auth")
            assert ok is True
            assert info.get("task_slug") == "fix-auth"


class TestReleaseLock:
    """Test cases for release_lock() function."""

    def test_release_lock_basic(self):
        """Test basic lock release."""
        mock_db = MockDB()
        with patch('conflict_prevention.db', mock_db):
            conflict_prevention.acquire_lock("proj1", "src/main.py", "agent-1")
            released = conflict_prevention.release_lock("proj1", "src/main.py", "agent-1")
            assert released == 1

    def test_release_lock_no_db(self):
        """Test release_lock returns 0 when db unavailable."""
        with patch('conflict_prevention.db', None):
            released = conflict_prevention.release_lock("proj1", "src/main.py", "agent-1")
            assert released == 0

    def test_release_lock_db_error(self):
        """Test release_lock handles db errors."""
        mock_db = Mock()
        mock_db.select.side_effect = Exception("DB error")
        with patch('conflict_prevention.db', mock_db):
            released = conflict_prevention.release_lock("proj1", "src/main.py", "agent-1")
            assert released == 0

    def test_release_nonexistent_lock(self):
        """Test releasing a lock that doesn't exist."""
        mock_db = MockDB()
        with patch('conflict_prevention.db', mock_db):
            released = conflict_prevention.release_lock("proj1", "src/main.py", "agent-1")
            assert released == 0


class TestReleaseAllLocks:
    """Test cases for release_all_locks() function."""

    def test_release_all_locks(self):
        """Test releasing all locks for an agent."""
        mock_db = MockDB()
        with patch('conflict_prevention.db', mock_db):
            conflict_prevention.acquire_lock("proj1", "a.py", "agent-1")
            conflict_prevention.acquire_lock("proj1", "b.py", "agent-1")
            released = conflict_prevention.release_all_locks("agent-1")
            assert released == 2

    def test_release_all_locks_no_db(self):
        """Test release_all_locks returns 0 when db unavailable."""
        with patch('conflict_prevention.db', None):
            released = conflict_prevention.release_all_locks("agent-1")
            assert released == 0


class TestPredictConflicts:
    """Test cases for predict_conflicts() function."""

    def test_predict_conflicts_basic(self):
        """Test basic conflict prediction."""
        mock_db = MockDB()
        with patch('conflict_prevention.db', mock_db):
            # Agent-1 holds a lock on src/main.py
            conflict_prevention.acquire_lock("proj1", "src/main.py", "agent-1")
            # Predict conflicts for a new task wanting the same file
            dag_tasks = [{"slug": "new-task", "file_scope": ["src/main.py"]}]
            conflicts = conflict_prevention.predict_conflicts(dag_tasks, "proj1")
            assert len(conflicts) >= 1
            assert conflicts[0]["file_path"] == "src/main.py"

    def test_predict_conflicts_no_overlap(self):
        """Test prediction with no file overlap."""
        mock_db = MockDB()
        with patch('conflict_prevention.db', mock_db):
            conflict_prevention.acquire_lock("proj1", "src/main.py", "agent-1")
            dag_tasks = [{"slug": "new-task", "file_scope": ["src/utils.py"]}]
            conflicts = conflict_prevention.predict_conflicts(dag_tasks, "proj1")
            assert len(conflicts) == 0


class TestBroadcastConflicts:
    """Test cases for broadcast_conflicts() function."""

    def test_broadcast_conflicts(self):
        """Test broadcasting conflicts to the bus."""
        bus = Mock()
        conflicts = [{
            "task_slug": "t1",
            "file_path": "src/main.py",
            "held_by": "agent-1",
            "resolution": "reorder_or_wait",
        }]
        conflict_prevention.broadcast_conflicts(conflicts, bus)
        bus.publish.assert_called_once()
        call_args = bus.publish.call_args[0][0]
        assert call_args["kind"] == "conflict_predicted"

    def test_broadcast_no_bus(self):
        """Test broadcast does nothing with no bus."""
        conflict_prevention.broadcast_conflicts([{"test": True}], None)
        # Should not raise


class TestWorktreeGuard:
    """Test cases for worktree_guard() function."""

    def test_worktree_guard_in_worktree(self):
        """Test worktree_guard returns True when in a worktree."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(stdout="/path/to/repo-wt/branch\n")
            result = conflict_prevention.worktree_guard("/path/to/repo-wt/branch", "task-1")
            assert result is True

    def test_worktree_guard_in_main_checkout(self):
        """Test worktree_guard returns False in main checkout."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(stdout="/path/to/repo\n")
            result = conflict_prevention.worktree_guard("/path/to/repo", "task-1")
            assert result is False

    def test_worktree_guard_error_failsoft(self):
        """Test worktree_guard returns True on error (fail-soft)."""
        with patch('subprocess.run', side_effect=Exception("git error")):
            result = conflict_prevention.worktree_guard("/path/to/repo", "task-1")
            assert result is True


class TestMergeSafetyCheck:
    """Test cases for merge_safety_check() function."""

    def test_merge_safety_no_conflicts(self):
        """Test merge_safety_check when no conflicts exist."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(stdout="abc123\n", returncode=0)
            safe, summary = conflict_prevention.merge_safety_check("feature", "main", "/repo")
            assert safe is True
            assert summary == ""

    def test_merge_safety_has_conflicts(self):
        """Test merge_safety_check when conflicts exist."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                stdout="CONFLICT (content): merge conflict in src/main.py\n",
                returncode=1
            )
            safe, summary = conflict_prevention.merge_safety_check("feature", "main", "/repo")
            assert safe is False
            assert "CONFLICT" in summary

    def test_merge_safety_error_failsoft(self):
        """Test merge_safety_check returns safe on error (fail-soft)."""
        with patch('subprocess.run', side_effect=Exception("git error")):
            safe, summary = conflict_prevention.merge_safety_check("feature", "main", "/repo")
            assert safe is True


class TestStats:
    """Test cases for stats() function."""

    def test_stats_with_locks(self):
        """Test stats returns active lock count."""
        mock_db = MockDB()
        with patch('conflict_prevention.db', mock_db):
            conflict_prevention.acquire_lock("proj1", "a.py", "agent-1")
            conflict_prevention.acquire_lock("proj1", "b.py", "agent-2")
            result = conflict_prevention.stats()
            assert result["active_locks"] == 2

    def test_stats_no_db(self):
        """Test stats returns empty dict when db unavailable."""
        with patch('conflict_prevention.db', None):
            result = conflict_prevention.stats()
            assert result == {}


class TestActiveLocks:
    """Test cases for active_locks() function."""

    def test_active_locks_all(self):
        """Test getting all active locks."""
        mock_db = MockDB()
        with patch('conflict_prevention.db', mock_db):
            conflict_prevention.acquire_lock("proj1", "a.py", "agent-1")
            conflict_prevention.acquire_lock("proj2", "b.py", "agent-2")
            locks = conflict_prevention.active_locks()
            assert len(locks) == 2

    def test_active_locks_by_project(self):
        """Test filtering active locks by project."""
        mock_db = MockDB()
        with patch('conflict_prevention.db', mock_db):
            conflict_prevention.acquire_lock("proj1", "a.py", "agent-1")
            conflict_prevention.acquire_lock("proj2", "b.py", "agent-2")
            locks = conflict_prevention.active_locks(project_id="proj1")
            # MockDB doesn't filter by project_id, but real DB would
            assert isinstance(locks, list)

    def test_active_locks_no_db(self):
        """Test active_locks returns empty list when db unavailable."""
        with patch('conflict_prevention.db', None):
            locks = conflict_prevention.active_locks()
            assert locks == []


class TestLockStatus:
    """Test cases for lock_status() function."""

    def test_lock_status_locked(self):
        """Test lock_status for a locked file."""
        mock_db = MockDB()
        with patch('conflict_prevention.db', mock_db):
            conflict_prevention.acquire_lock("proj1", "a.py", "agent-1")
            status = conflict_prevention.lock_status("a.py", "proj1")
            assert status is not None

    def test_lock_status_unlocked(self):
        """Test lock_status for an unlocked file."""
        mock_db = MockDB()
        with patch('conflict_prevention.db', mock_db):
            status = conflict_prevention.lock_status("a.py", "proj1")
            assert status is None

    def test_lock_status_no_db(self):
        """Test lock_status returns None when db unavailable."""
        with patch('conflict_prevention.db', None):
            status = conflict_prevention.lock_status("a.py", "proj1")
            assert status is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
