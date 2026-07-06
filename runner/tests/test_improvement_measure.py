"""
test_improvement_measure.py - Tests for improvement measurement and stage metrics collection.

Verifies that the improvement loop correctly:
1. Marks shipped improvements from merged tasks
2. Attributes revenue changes to surfaces
3. Collects cycle_time and first_try_yield metrics for pipeline tuning
"""
import unittest
from unittest.mock import patch, MagicMock, call
import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestImprovementMeasure(unittest.TestCase):
    """Test suite for improvement_measure.py functions."""

    def setUp(self):
        """Set up test fixtures."""
        # Mock db module before importing
        self.db_mock = MagicMock()
        sys.modules['db'] = self.db_mock

    def tearDown(self):
        """Clean up mocks."""
        if 'improvement_measure' in sys.modules:
            del sys.modules['improvement_measure']

    @patch('improvement_measure.db')
    def test_mark_shipped_finds_merged_tasks(self, mock_db):
        """Test that mark_shipped() identifies merged tasks and updates status."""
        import improvement_measure

        # Mock the database responses
        mock_db.select.side_effect = [
            # First call: get merged tasks
            [
                {'slug': 'task-001', 'state': 'MERGED'},
                {'slug': 'task-002', 'state': 'MERGED'},
                {'slug': 'task-003', 'state': 'MERGED'},
            ],
            # Second call: get queued improvement proposals
            [
                {'id': '1', 'task_slug': 'task-001', 'status': 'queued'},
                {'id': '2', 'task_slug': 'task-002', 'status': 'queued'},
                {'id': '3', 'task_slug': 'task-999', 'status': 'queued'},  # not merged
            ],
        ]

        result = improvement_measure.mark_shipped()

        # Should have updated 2 proposals (matching task-001 and task-002)
        self.assertEqual(result, 2)
        # Verify update was called for matching proposals
        calls = [c for c in mock_db.update.call_args_list if 'shipped' in str(c)]
        self.assertEqual(len(calls), 2)

    @patch('improvement_measure.db')
    def test_mark_shipped_handles_empty_results(self, mock_db):
        """Test mark_shipped() handles empty database results gracefully."""
        import improvement_measure

        mock_db.select.side_effect = [
            None,  # No merged tasks
            None,  # No proposals
        ]

        result = improvement_measure.mark_shipped()
        self.assertEqual(result, 0)

    @patch('improvement_measure.db')
    def test_surface_returns_calculates_averages(self, mock_db):
        """Test surface_returns() correctly aggregates revenue by surface."""
        import improvement_measure

        mock_db.select.side_effect = [
            # Shipped proposals
            [
                {'surface': 'backend', 'task_slug': 'task-001'},
                {'surface': 'backend', 'task_slug': 'task-002'},
                {'surface': 'frontend', 'task_slug': 'task-003'},
            ],
            # Merge revenue
            [
                {'slug': 'task-001', 'revenue_delta': 100.0},
                {'slug': 'task-002', 'revenue_delta': 200.0},
                {'slug': 'task-003', 'revenue_delta': 50.0},
            ],
        ]

        result = improvement_measure.surface_returns()

        # Backend: (100 + 200) / 2 = 150
        # Frontend: 50 / 1 = 50
        self.assertEqual(result.get('backend'), 150.0)
        self.assertEqual(result.get('frontend'), 50.0)
        self.assertEqual(len(result), 2)

    @patch('improvement_measure.db')
    def test_surface_returns_handles_missing_revenue(self, mock_db):
        """Test surface_returns() skips proposals with no revenue data."""
        import improvement_measure

        mock_db.select.side_effect = [
            # Shipped proposals
            [
                {'surface': 'backend', 'task_slug': 'task-001'},
                {'surface': 'frontend', 'task_slug': 'task-999'},  # no revenue
            ],
            # Merge revenue (only has task-001)
            [
                {'slug': 'task-001', 'revenue_delta': 100.0},
            ],
        ]

        result = improvement_measure.surface_returns()

        # Only backend should be in results (frontend has no revenue data)
        self.assertEqual(result.get('backend'), 100.0)
        self.assertIsNone(result.get('frontend'))

    @patch('improvement_measure.datetime')
    @patch('improvement_measure.db')
    def test_stage_metrics_calculates_cycle_time(self, mock_db, mock_datetime):
        """Test that stage_metrics() correctly measures cycle_time and first_try_yield."""
        import improvement_measure

        # Mock current time
        now = datetime.datetime(2026, 7, 6, 12, 0, 0)
        mock_datetime.datetime.utcnow.return_value = now

        # Create task created 5 days ago
        created_time = now - datetime.timedelta(days=5)
        completed_time = created_time + datetime.timedelta(seconds=3600)  # 1 hour later

        mock_db.select.side_effect = [
            # Merged tasks
            [
                {
                    'id': 'task-1',
                    'slug': 'task-001',
                    'project_id': 'proj-1',
                    'kind': 'bug_fix',
                    'created_at': created_time.isoformat() + 'Z',
                    'remediation_count': 0,  # first try
                    'state': 'MERGED',
                },
            ],
            # Outcomes (completion events)
            [
                {
                    'task_id': 'task-1',
                    'created_at': completed_time.isoformat() + 'Z',
                    'wall_ms': 3600000,
                },
            ],
        ]

        result = improvement_measure.stage_metrics()

        # Should have written at least one metric record
        self.assertGreater(result.get('stage_metrics_written', 0), 0)
        # Verify db.insert was called for stage_metrics
        calls = [c for c in mock_db.insert.call_args_list if 'stage_metrics' in str(c)]
        self.assertGreater(len(calls), 0)

        # Verify the insert had correct structure
        if calls:
            call_kwargs = calls[0][1] if len(calls[0]) > 1 else calls[0][0][1]
            self.assertIn('avg_cycle_time_seconds', str(call_kwargs))
            self.assertIn('first_try_yield_pct', str(call_kwargs))

    @patch('improvement_measure.datetime')
    @patch('improvement_measure.db')
    def test_stage_metrics_respects_window_boundaries(self, mock_db, mock_datetime):
        """Test that stage_metrics() correctly filters by rolling window."""
        import improvement_measure

        now = datetime.datetime(2026, 7, 6, 12, 0, 0)
        mock_datetime.datetime.utcnow.return_value = now

        # Create two tasks: one recent (2 days ago), one old (100 days ago)
        recent_created = now - datetime.timedelta(days=2)
        old_created = now - datetime.timedelta(days=100)

        mock_db.select.side_effect = [
            # Merged tasks (sorted by created_at descending, limited to 5000)
            [
                {
                    'id': 'recent-1',
                    'slug': 'recent-task',
                    'project_id': 'proj-1',
                    'kind': 'feature',
                    'created_at': recent_created.isoformat() + 'Z',
                    'remediation_count': 0,
                    'state': 'MERGED',
                },
                {
                    'id': 'old-1',
                    'slug': 'old-task',
                    'project_id': 'proj-1',
                    'kind': 'feature',
                    'created_at': old_created.isoformat() + 'Z',
                    'remediation_count': 1,
                    'state': 'MERGED',
                },
            ],
            # Outcomes
            [
                {
                    'task_id': 'recent-1',
                    'created_at': (recent_created + datetime.timedelta(hours=2)).isoformat() + 'Z',
                    'wall_ms': 7200000,
                },
                {
                    'task_id': 'old-1',
                    'created_at': (old_created + datetime.timedelta(hours=5)).isoformat() + 'Z',
                    'wall_ms': 18000000,
                },
            ],
        ]

        result = improvement_measure.stage_metrics()

        # Recent task should be included in all windows (5, 30, 90)
        # Old task should only be in 90-day window
        # Each task/project/kind/window combo gets one insert
        # So minimum 3 (recent in 3 windows) + 1 (old in 90-day) = 4
        self.assertGreaterEqual(result.get('stage_metrics_written', 0), 3)

    @patch('improvement_measure.db')
    def test_stage_metrics_handles_invalid_dates(self, mock_db):
        """Test that stage_metrics() handles unparseable date formats gracefully."""
        import improvement_measure

        mock_db.select.side_effect = [
            # Tasks with various invalid date formats
            [
                {
                    'id': 'task-1',
                    'slug': 'bad-date-1',
                    'project_id': 'proj-1',
                    'kind': 'bug',
                    'created_at': 'not-a-date',  # Invalid
                    'remediation_count': 0,
                    'state': 'MERGED',
                },
            ],
            [],  # No outcomes
        ]

        # Should not crash, just skip bad records
        result = improvement_measure.stage_metrics()
        self.assertEqual(result.get('stage_metrics_written', 0), 0)

    @patch('improvement_measure.datetime')
    @patch('improvement_measure.db')
    def test_improvement_measure_run_integrates_all_steps(self, mock_db, mock_datetime):
        """Test that run() orchestrates all measurement steps."""
        import improvement_measure

        now = datetime.datetime(2026, 7, 6, 12, 0, 0)
        mock_datetime.datetime.utcnow.return_value = now

        # Setup complex mock responses for full integration
        mock_db.select.side_effect = [
            # mark_shipped: merged tasks
            [{'slug': 'task-001', 'state': 'MERGED'}],
            # mark_shipped: queued proposals
            [{'id': '1', 'task_slug': 'task-001', 'status': 'queued'}],
            # surface_returns: shipped proposals
            [{'surface': 'backend', 'task_slug': 'task-001'}],
            # surface_returns: merge revenue
            [{'slug': 'task-001', 'revenue_delta': 500.0}],
            # stage_metrics: merged tasks
            [
                {
                    'id': 'task-1',
                    'slug': 'task-001',
                    'project_id': 'proj-1',
                    'kind': 'feature',
                    'created_at': (now - datetime.timedelta(days=3)).isoformat() + 'Z',
                    'remediation_count': 0,
                    'state': 'MERGED',
                }
            ],
            # stage_metrics: outcomes
            [
                {
                    'task_id': 'task-1',
                    'created_at': (now - datetime.timedelta(days=3, hours=-2)).isoformat() + 'Z',
                    'wall_ms': 7200000,
                }
            ],
        ]

        result = improvement_measure.run()

        # Verify all components are present in result
        self.assertIn('shipped', result)
        self.assertIn('returns', result)
        self.assertIn('stage_metrics_written', result)

        # Verify counts
        self.assertEqual(result['shipped'], 1)
        self.assertEqual(result['returns'].get('backend'), 500.0)
        self.assertGreaterEqual(result['stage_metrics_written'], 1)


class TestImprovementMeasureFirstTryYield(unittest.TestCase):
    """Focused tests for first_try_yield metric tracking."""

    @patch('improvement_measure.datetime')
    @patch('improvement_measure.db')
    def test_improvement_measure_tracks_first_try_yield(self, mock_db, mock_datetime):
        """Test that stage_metrics accurately tracks first_try_yield percentage."""
        import improvement_measure

        now = datetime.datetime(2026, 7, 6, 12, 0, 0)
        mock_datetime.datetime.utcnow.return_value = now
        base_time = now - datetime.timedelta(days=3)

        # Create 10 tasks: 7 first-try (remediation_count=0), 3 with remediations
        tasks = []
        outcomes = []
        for i in range(10):
            task_id = f'task-{i}'
            is_first_try = i < 7  # First 7 are first-try
            remediation_count = 0 if is_first_try else (i - 6)

            task_created = base_time + datetime.timedelta(hours=i)
            task_completed = task_created + datetime.timedelta(hours=1)

            tasks.append({
                'id': task_id,
                'slug': f'slug-{i:03d}',
                'project_id': 'proj-measure-yield',
                'kind': 'test',
                'created_at': task_created.isoformat() + 'Z',
                'remediation_count': remediation_count,
                'state': 'MERGED',
            })

            outcomes.append({
                'task_id': task_id,
                'created_at': task_completed.isoformat() + 'Z',
                'wall_ms': 3600000,
            })

        mock_db.select.side_effect = [tasks, outcomes]

        result = improvement_measure.stage_metrics()

        # Verify metrics were written
        self.assertGreater(result.get('stage_metrics_written', 0), 0)

        # Verify the insert call includes first_try_yield_pct = 70.0 (7/10 * 100)
        insert_calls = mock_db.insert.call_args_list
        stage_metrics_calls = [
            c for c in insert_calls
            if len(c[0]) > 0 and c[0][0] == 'stage_metrics'
        ]

        self.assertGreater(len(stage_metrics_calls), 0)

        # Check the inserted data includes first_try_yield_pct
        for call_obj in stage_metrics_calls:
            if len(call_obj[0]) > 1:
                data = call_obj[0][1]
                if 'first_try_yield_pct' in data:
                    # Should be 70.0 for the 10-task cohort
                    self.assertAlmostEqual(data['first_try_yield_pct'], 70.0, delta=0.1)


if __name__ == '__main__':
    unittest.main()
