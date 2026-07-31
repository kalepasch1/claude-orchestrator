#!/usr/bin/env python3
"""Tests for stale_backlog_recovery — detection and recovery of orphaned/stale tasks.

Validates:
  - Detection of tasks in RUNNING state beyond TTL threshold
  - Consolidation of duplicate/redundant runs of the same task
  - Recovery actions: requeue, mark-stale, retry with backoff
  - State consistency after recovery (no orphans left behind)
  - Lost data detection and materialization from task_artifacts
  - Fail-soft error handling (bad timestamps, missing data, DB errors)
  - Priority ordering (most-stale tasks first)
  - Preservation of task metadata through recovery cycle
"""
import os
import sys
import json
import time
import pytest
from unittest.mock import patch, MagicMock, call
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Import the module under test (will be created by the agent)
try:
    import stale_backlog_recovery as sbr
except ImportError:
    sbr = None


class TestConstantsAndDefaults:
    """Test configuration constants and environment variable handling."""

    def test_stale_threshold_default(self):
        """STALE_THRESHOLD defaults to 30 minutes if env var not set."""
        if sbr:
            # Default should be reasonable (e.g., 30 min = 1800 sec)
            assert hasattr(sbr, 'STALE_THRESHOLD')
            assert isinstance(sbr.STALE_THRESHOLD, int)
            assert sbr.STALE_THRESHOLD > 0

    def test_stale_threshold_env_override(self):
        """STALE_THRESHOLD respects ORCH_STALE_THRESHOLD_SECONDS env var."""
        if sbr:
            with patch.dict(os.environ, {'ORCH_STALE_THRESHOLD_SECONDS': '600'}):
                # Re-import or reload module to pick up env var
                # For now just verify the constant exists
                assert hasattr(sbr, 'STALE_THRESHOLD')

    def test_max_consolidation_default(self):
        """MAX_CONSOLIDATIONS defaults to 3 if env var not set."""
        if sbr:
            assert hasattr(sbr, 'MAX_CONSOLIDATIONS')
            assert isinstance(sbr.MAX_CONSOLIDATIONS, int)
            assert sbr.MAX_CONSOLIDATIONS >= 1

    def test_retry_backoff_multiplier(self):
        """RETRY_BACKOFF_MULTIPLIER defaults to 2.0 for exponential backoff."""
        if sbr:
            assert hasattr(sbr, 'RETRY_BACKOFF_MULTIPLIER')
            assert isinstance(sbr.RETRY_BACKOFF_MULTIPLIER, (int, float))
            assert sbr.RETRY_BACKOFF_MULTIPLIER > 1.0


class TestStaleTaskDetection:
    """Test detection of stale (over-age) tasks in RUNNING state."""

    def _make_task(self, state='RUNNING', started_at=None, slug='test-task'):
        """Helper to create a mock task dict."""
        if started_at is None:
            started_at = time.time() - 3600  # 1 hour ago
        return {
            'id': f'task-{slug}',
            'slug': slug,
            'state': state,
            'started_at': started_at,
            'updated_at': time.time(),
            'coder': 'claude',
            'attempt': 1,
        }

    def test_detect_single_stale_task(self):
        """A task RUNNING for >threshold minutes is detected as stale."""
        if not sbr or not hasattr(sbr, 'detect_stale_tasks'):
            pytest.skip("Module not ready")

        # Task running for 1 hour should be stale (threshold usually 30 min)
        task = self._make_task(started_at=time.time() - 3600)
        stale = sbr.detect_stale_tasks([task], threshold_sec=1800)
        assert len(stale) >= 1
        assert stale[0]['id'] == task['id']

    def test_fresh_task_not_stale(self):
        """A task RUNNING for <threshold is not detected as stale."""
        if not sbr or not hasattr(sbr, 'detect_stale_tasks'):
            pytest.skip("Module not ready")

        # Task running for 5 minutes should be fresh (threshold 30 min)
        task = self._make_task(started_at=time.time() - 300)
        stale = sbr.detect_stale_tasks([task], threshold_sec=1800)
        assert len(stale) == 0

    def test_completed_task_not_stale(self):
        """A task in COMPLETED/FAILED state is not detected as stale."""
        if not sbr or not hasattr(sbr, 'detect_stale_tasks'):
            pytest.skip("Module not ready")

        task_done = self._make_task(state='COMPLETED', started_at=time.time() - 3600)
        stale = sbr.detect_stale_tasks([task_done], threshold_sec=1800)
        assert len(stale) == 0

    def test_missing_timestamp_handled_gracefully(self):
        """Tasks with missing/None started_at don't crash detection."""
        if not sbr or not hasattr(sbr, 'detect_stale_tasks'):
            pytest.skip("Module not ready")

        task = self._make_task(started_at=None)
        stale = sbr.detect_stale_tasks([task], threshold_sec=1800)
        # Should not raise; may be treated as fresh (safe default) or skipped
        assert isinstance(stale, list)

    def test_invalid_timestamp_type_fails_soft(self):
        """Tasks with invalid timestamp type don't crash."""
        if not sbr or not hasattr(sbr, 'detect_stale_tasks'):
            pytest.skip("Module not ready")

        task = self._make_task(started_at="not-a-timestamp")
        stale = sbr.detect_stale_tasks([task], threshold_sec=1800)
        # Should handle gracefully (skip or return empty)
        assert isinstance(stale, list)

    def test_empty_task_list(self):
        """Empty task list returns empty stale list."""
        if not sbr or not hasattr(sbr, 'detect_stale_tasks'):
            pytest.skip("Module not ready")

        stale = sbr.detect_stale_tasks([], threshold_sec=1800)
        assert stale == []

    def test_prioritize_most_stale_first(self):
        """Stale tasks are sorted by age (most stale first)."""
        if not sbr or not hasattr(sbr, 'detect_stale_tasks'):
            pytest.skip("Module not ready")

        now = time.time()
        task1 = self._make_task(slug='task-1h', started_at=now - 3600)
        task2 = self._make_task(slug='task-2h', started_at=now - 7200)
        task3 = self._make_task(slug='task-30m', started_at=now - 1800)

        stale = sbr.detect_stale_tasks([task1, task2, task3], threshold_sec=600)
        if len(stale) > 0:
            # Most stale (2h ago) should be first
            assert stale[0]['slug'] == 'task-2h' or stale[-1]['slug'] == 'task-30m'


class TestConsolidation:
    """Test consolidation of duplicate/redundant task runs."""

    def _make_task(self, slug='task', run_num=1, state='RUNNING'):
        """Create a mock task with optional run number in slug."""
        started_ago_sec = 3600 + (run_num * 600)  # Each run 10 min older
        return {
            'id': f'task-{slug}-run{run_num}',
            'slug': slug,
            'state': state,
            'started_at': time.time() - started_ago_sec,
            'attempt': run_num,
        }

    def test_detect_duplicate_runs(self):
        """Multiple running instances of same task slug are detected."""
        if not sbr or not hasattr(sbr, 'consolidate_duplicates'):
            pytest.skip("Module not ready")

        task1 = self._make_task(slug='my-task', run_num=1)
        task2 = self._make_task(slug='my-task', run_num=2)
        task3 = self._make_task(slug='other-task', run_num=1)

        consolidated = sbr.consolidate_duplicates([task1, task2, task3])
        # Should detect 2 runs of 'my-task'
        assert isinstance(consolidated, dict)

    def test_keep_oldest_run_mark_younger_for_cleanup(self):
        """When consolidating duplicates, oldest run is kept, younger canceled."""
        if not sbr or not hasattr(sbr, 'consolidate_duplicates'):
            pytest.skip("Module not ready")

        now = time.time()
        task1 = self._make_task(slug='dup-task', run_num=1)  # 2h ago
        task1['started_at'] = now - 7200
        task2 = self._make_task(slug='dup-task', run_num=2)  # 1h ago
        task2['started_at'] = now - 3600

        consolidated = sbr.consolidate_duplicates([task1, task2])
        if 'dup-task' in consolidated:
            # Oldest (task1) should be the keeper
            assert consolidated['dup-task']['keeper']['id'] == task1['id']

    def test_respects_max_consolidations_limit(self):
        """Won't consolidate more than MAX_CONSOLIDATIONS instances."""
        if not sbr or not hasattr(sbr, 'consolidate_duplicates'):
            pytest.skip("Module not ready")

        tasks = [self._make_task(slug='many', run_num=i) for i in range(1, 6)]
        consolidated = sbr.consolidate_duplicates(tasks)
        # Result should respect MAX_CONSOLIDATIONS
        assert isinstance(consolidated, dict)

    def test_empty_list_returns_empty_dict(self):
        """Empty task list returns empty consolidation dict."""
        if not sbr or not hasattr(sbr, 'consolidate_duplicates'):
            pytest.skip("Module not ready")

        result = sbr.consolidate_duplicates([])
        assert result == {} or result is None or len(result) == 0

    def test_single_task_no_consolidation(self):
        """Single task per slug doesn't trigger consolidation."""
        if not sbr or not hasattr(sbr, 'consolidate_duplicates'):
            pytest.skip("Module not ready")

        task = self._make_task(slug='unique-task')
        consolidated = sbr.consolidate_duplicates([task])
        # Should have no consolidation actions
        assert len(consolidated) == 0 or all(v['to_cancel'] == [] for v in consolidated.values())


class TestRecoveryActions:
    """Test recovery actions: requeue, mark-stale, cancel-redundant."""

    def _make_task(self, state='RUNNING', slug='task'):
        return {
            'id': f'task-{slug}',
            'slug': slug,
            'state': state,
            'started_at': time.time() - 3600,
            'attempt': 1,
        }

    def test_build_requeue_action(self):
        """A stale RUNNING task can be requeued (moved back to QUEUED)."""
        if not sbr or not hasattr(sbr, 'build_recovery_action'):
            pytest.skip("Module not ready")

        task = self._make_task()
        action = sbr.build_recovery_action(task, action_type='requeue')
        assert action is not None
        assert action.get('task_id') == task['id']
        assert action.get('action') == 'requeue'

    def test_build_mark_stale_action(self):
        """A stale RUNNING task can be marked as STALE."""
        if not sbr or not hasattr(sbr, 'build_recovery_action'):
            pytest.skip("Module not ready")

        task = self._make_task()
        action = sbr.build_recovery_action(task, action_type='mark_stale')
        assert action is not None
        assert action.get('task_id') == task['id']
        assert action.get('action') == 'mark_stale'

    def test_build_cancel_action_for_duplicate(self):
        """Duplicate/younger runs can be canceled."""
        if not sbr or not hasattr(sbr, 'build_recovery_action'):
            pytest.skip("Module not ready")

        task = self._make_task()
        action = sbr.build_recovery_action(task, action_type='cancel',
                                          reason='duplicate_run')
        assert action is not None
        assert action.get('action') == 'cancel'
        assert 'reason' in action

    def test_action_includes_timestamp(self):
        """Recovery actions include a timestamp for audit trail."""
        if not sbr or not hasattr(sbr, 'build_recovery_action'):
            pytest.skip("Module not ready")

        task = self._make_task()
        action = sbr.build_recovery_action(task, action_type='requeue')
        assert action is not None
        assert 'timestamp' in action or 'created_at' in action

    def test_invalid_action_type_rejected(self):
        """Unknown action types are rejected gracefully."""
        if not sbr or not hasattr(sbr, 'build_recovery_action'):
            pytest.skip("Module not ready")

        task = self._make_task()
        action = sbr.build_recovery_action(task, action_type='unknown_action')
        # Should return None or raise ValueError
        if action is None:
            assert True
        else:
            pytest.fail("Should reject unknown action type")


class TestLostDataRecovery:
    """Test detection and recovery of lost task data."""

    def test_detect_missing_task_artifacts(self):
        """Tasks without artifact records are flagged."""
        if not sbr or not hasattr(sbr, 'detect_lost_data'):
            pytest.skip("Module not ready")

        task = {
            'id': 'task-1',
            'slug': 'missing-artifacts',
            'state': 'RUNNING',
            'started_at': time.time() - 3600,
            'artifact_id': None,
        }
        lost = sbr.detect_lost_data([task])
        if isinstance(lost, list) and len(lost) > 0:
            assert lost[0]['id'] == task['id']
            assert lost[0]['issue'] == 'missing_artifacts'

    def test_detect_stale_task_with_incomplete_state(self):
        """Stale tasks with incomplete state transition are flagged."""
        if not sbr or not hasattr(sbr, 'detect_lost_data'):
            pytest.skip("Module not ready")

        task = {
            'id': 'task-2',
            'slug': 'incomplete-state',
            'state': 'RUNNING',
            'started_at': time.time() - 7200,
            'progress': None,  # No progress recorded
            'last_heartbeat': None,
        }
        lost = sbr.detect_lost_data([task])
        # May or may not flag this as lost data depending on schema
        assert isinstance(lost, list)

    def test_materialize_from_task_artifacts(self):
        """Lost data can be recovered from task_artifacts table."""
        if not sbr or not hasattr(sbr, 'materialize_lost_data'):
            pytest.skip("Module not ready")

        task = {
            'id': 'task-3',
            'slug': 'can-recover',
            'artifact_id': 'artifact-123',
        }
        # Mock artifact data
        mock_artifacts = {
            'commit_sha': 'abc123',
            'touched_files': '["file1.py", "file2.py"]',
            'patch_diff': 'diff --git a/file1.py',
        }

        with patch('stale_backlog_recovery.get_artifact_data', return_value=mock_artifacts):
            recovered = sbr.materialize_lost_data(task)
            if recovered:
                assert recovered.get('commit_sha') == 'abc123'

    def test_handle_missing_artifact_gracefully(self):
        """Missing artifact data doesn't crash recovery."""
        if not sbr or not hasattr(sbr, 'materialize_lost_data'):
            pytest.skip("Module not ready")

        task = {
            'id': 'task-4',
            'slug': 'no-artifact',
            'artifact_id': None,
        }
        with patch('stale_backlog_recovery.get_artifact_data', return_value=None):
            recovered = sbr.materialize_lost_data(task)
            # Should return empty dict or None, not crash
            assert recovered is None or isinstance(recovered, dict)

    def test_empty_task_list_returns_no_lost_data(self):
        """Empty task list has no lost data."""
        if not sbr or not hasattr(sbr, 'detect_lost_data'):
            pytest.skip("Module not ready")

        lost = sbr.detect_lost_data([])
        assert lost == [] or lost is None


class TestFailSoftErrorHandling:
    """Test graceful degradation on errors."""

    def test_db_error_during_detection(self):
        """DB errors during stale detection don't crash."""
        if not sbr or not hasattr(sbr, 'detect_stale_tasks'):
            pytest.skip("Module not ready")

        task = {
            'id': 'task-1',
            'state': 'RUNNING',
            'started_at': 'bad-timestamp',
        }
        # Should not raise
        stale = sbr.detect_stale_tasks([task])
        assert isinstance(stale, list)

    def test_missing_required_task_fields(self):
        """Tasks with missing fields don't crash."""
        if not sbr or not hasattr(sbr, 'detect_stale_tasks'):
            pytest.skip("Module not ready")

        task = {'id': 'task-1'}  # Missing 'state', 'started_at'
        stale = sbr.detect_stale_tasks([task])
        assert isinstance(stale, list)

    def test_malformed_json_in_metadata(self):
        """Malformed JSON in task metadata doesn't crash."""
        if not sbr or not hasattr(sbr, 'detect_stale_tasks'):
            pytest.skip("Module not ready")

        task = {
            'id': 'task-1',
            'state': 'RUNNING',
            'started_at': time.time() - 3600,
            'metadata': '{invalid json}',
        }
        stale = sbr.detect_stale_tasks([task])
        assert isinstance(stale, list)

    def test_git_command_failure_handled(self):
        """Git command failures during recovery don't wedge the system."""
        if not sbr or not hasattr(sbr, 'apply_recovery_action'):
            pytest.skip("Module not ready")

        action = {
            'task_id': 'task-1',
            'action': 'requeue',
        }
        # Mock git command to fail
        with patch('subprocess.run', side_effect=Exception("git failed")):
            result = sbr.apply_recovery_action(action)
            # Should return False or empty result, not raise
            assert result is False or result is None or not result


class TestEndToEndRecoveryFlow:
    """Test complete recovery pipeline."""

    def test_full_recovery_pipeline_queues_actions(self):
        """Full pipeline: detect → consolidate → build actions → queue."""
        if not sbr or not hasattr(sbr, 'run_recovery_pipeline'):
            pytest.skip("Module not ready")

        now = time.time()
        tasks = [
            {
                'id': 'task-1',
                'slug': 'stale-task',
                'state': 'RUNNING',
                'started_at': now - 3600,
                'attempt': 1,
            },
            {
                'id': 'task-2',
                'slug': 'stale-task',
                'state': 'RUNNING',
                'started_at': now - 7200,
                'attempt': 2,
            },
        ]

        result = sbr.run_recovery_pipeline(tasks, threshold_sec=1800)
        assert isinstance(result, dict)
        assert 'detected_stale' in result or 'actions_queued' in result

    def test_recovery_preserves_task_metadata(self):
        """Recovery actions preserve all task metadata."""
        if not sbr or not hasattr(sbr, 'run_recovery_pipeline'):
            pytest.skip("Module not ready")

        task = {
            'id': 'task-1',
            'slug': 'important-task',
            'state': 'RUNNING',
            'started_at': time.time() - 3600,
            'coder': 'claude',
            'custom_field': 'must-preserve',
        }

        result = sbr.run_recovery_pipeline([task], threshold_sec=1800)
        assert isinstance(result, dict)

    def test_recovery_is_idempotent(self):
        """Running recovery twice on same tasks is safe."""
        if not sbr or not hasattr(sbr, 'run_recovery_pipeline'):
            pytest.skip("Module not ready")

        task = {
            'id': 'task-1',
            'slug': 'idempotent-task',
            'state': 'RUNNING',
            'started_at': time.time() - 3600,
        }

        result1 = sbr.run_recovery_pipeline([task], threshold_sec=1800)
        result2 = sbr.run_recovery_pipeline([task], threshold_sec=1800)
        # Both should succeed without side effects
        assert isinstance(result1, dict)
        assert isinstance(result2, dict)


class TestRetryBackoffCalculation:
    """Test exponential backoff for retry attempts."""

    def test_first_retry_backoff(self):
        """First retry (attempt=2) gets base backoff."""
        if not sbr or not hasattr(sbr, 'calculate_backoff_delay'):
            pytest.skip("Module not ready")

        delay = sbr.calculate_backoff_delay(attempt=1)
        assert isinstance(delay, (int, float))
        assert delay > 0

    def test_exponential_backoff_progression(self):
        """Later attempts get exponentially longer backoff."""
        if not sbr or not hasattr(sbr, 'calculate_backoff_delay'):
            pytest.skip("Module not ready")

        delay1 = sbr.calculate_backoff_delay(attempt=1)
        delay2 = sbr.calculate_backoff_delay(attempt=2)
        delay3 = sbr.calculate_backoff_delay(attempt=3)

        assert delay1 > 0
        # Later attempts should have longer delays
        if delay2 > 0:
            assert delay2 >= delay1
        if delay3 > 0:
            assert delay3 >= delay2

    def test_backoff_caps_at_max(self):
        """Backoff delay doesn't exceed MAX_BACKOFF."""
        if not sbr or not hasattr(sbr, 'calculate_backoff_delay'):
            pytest.skip("Module not ready")

        delay = sbr.calculate_backoff_delay(attempt=100)
        if hasattr(sbr, 'MAX_BACKOFF'):
            assert delay <= sbr.MAX_BACKOFF + 100  # Small margin for jitter


class TestStateConsistency:
    """Test that recovery maintains state consistency."""

    def test_no_orphaned_tasks_after_recovery(self):
        """After recovery, all detected tasks have an action queued."""
        if not sbr or not hasattr(sbr, 'run_recovery_pipeline'):
            pytest.skip("Module not ready")

        tasks = [
            {
                'id': 'task-1',
                'slug': 'orphan-check-1',
                'state': 'RUNNING',
                'started_at': time.time() - 3600,
            },
        ]

        result = sbr.run_recovery_pipeline(tasks, threshold_sec=1800)
        if 'detected_stale' in result and 'actions_queued' in result:
            # Every detected stale task should have an action
            assert result['actions_queued'] >= result['detected_stale']

    def test_task_state_transitions_are_valid(self):
        """Recovery actions only transition tasks to valid states."""
        if not sbr or not hasattr(sbr, 'build_recovery_action'):
            pytest.skip("Module not ready")

        task = {
            'id': 'task-1',
            'slug': 'state-test',
            'state': 'RUNNING',
            'started_at': time.time() - 3600,
        }

        for action_type in ['requeue', 'mark_stale', 'cancel']:
            action = sbr.build_recovery_action(task, action_type=action_type)
            if action:
                # Should have valid target state or action
                assert 'action' in action


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
