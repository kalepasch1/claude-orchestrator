#!/usr/bin/env python3
"""Tests for blocked_triage.py — auto-remediation of blocked task shards.

Coverage:
  - Classification of blocked tasks by error pattern
  - Requeue limit enforcement via [triage:N] markers
  - Age-based filtering (MIN_AGE_MIN)
  - Unknown blocker handling
  - State transitions during requeue
  - Escalation when max requeues exceeded
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import blocked_triage as bt


class BlockedTriageClassificationTest(unittest.TestCase):
    """Test blocker pattern matching and classification."""

    def test_classify_secret_shaped_data(self):
        name, fix = bt._classify("verify rejected: secret-shaped data in config")
        self.assertEqual(name, "secret_shaped")
        self.assertIn("env vars referenced by NAME only", fix)

    def test_classify_secret_shaped_introduced_secret(self):
        name, fix = bt._classify("added secret key to migrations")
        self.assertEqual(name, "secret_shaped")

    def test_classify_secret_shaped_secret_like(self):
        name, fix = bt._classify("secret like field found")
        self.assertEqual(name, "secret_shaped")

    def test_classify_permissive_allowlist(self):
        name, fix = bt._classify("permissive allowlist found in access control")
        self.assertEqual(name, "permissive_allowlist")
        self.assertIn("deny-by-default", fix)

    def test_classify_permissive_allowlist_variant(self):
        name, fix = bt._classify("without proper authorization or allowlist")
        self.assertEqual(name, "permissive_allowlist")

    def test_classify_integrate_contention_local_lock(self):
        name, fix = bt._classify("integrate=BLOCKED (local lock contention)")
        self.assertEqual(name, "integrate_contention")
        self.assertIn("worktree convention", fix)

    def test_classify_integrate_contention_index_lock(self):
        name, fix = bt._classify("fatal: lock file .git/index.lock exists")
        self.assertEqual(name, "integrate_contention")

    def test_classify_integrate_contention_branch_held(self):
        name, fix = bt._classify("branch is held for merge; worktree operation failed")
        self.assertEqual(name, "integrate_contention")

    def test_classify_integrate_contention_worktree_locked(self):
        name, fix = bt._classify("worktree locked for operation")
        self.assertEqual(name, "integrate_contention")

    def test_classify_exhausted_retries(self):
        name, fix = bt._classify("exhausted retries; task needs human review")
        self.assertEqual(name, "exhausted_retries")
        self.assertIn("SHARD:", fix)

    def test_classify_exhausted_retries_max_retries(self):
        name, fix = bt._classify("max retries exceeded")
        self.assertEqual(name, "exhausted_retries")

    def test_classify_exhausted_retries_retry_budget(self):
        name, fix = bt._classify("retry budget exhausted")
        self.assertEqual(name, "exhausted_retries")

    def test_classify_model_misroute_404(self):
        name, fix = bt._classify("model 'gemini-9.0-pro' does not exist")
        self.assertEqual(name, "model_misroute_404")
        self.assertIn("misroute guard", fix)

    def test_classify_model_misroute_not_found(self):
        name, fix = bt._classify("404 Not Found: model not found")
        self.assertEqual(name, "model_misroute_404")

    def test_classify_model_misroute_invalid(self):
        name, fix = bt._classify("invalid model id: claude-x999")
        self.assertEqual(name, "model_misroute_404")

    def test_classify_missing_tests(self):
        name, fix = bt._classify("missing test coverage for new feature")
        self.assertEqual(name, "missing_tests")
        self.assertIn("vitest/pytest", fix)

    def test_classify_missing_tests_no_coverage(self):
        name, fix = bt._classify("no test coverage")
        self.assertEqual(name, "missing_tests")

    def test_classify_missing_tests_without_tests(self):
        name, fix = bt._classify("without tests")
        self.assertEqual(name, "missing_tests")

    def test_classify_unknown_blocker(self):
        name, fix = bt._classify("some random error we have never seen")
        self.assertIsNone(name)
        self.assertIsNone(fix)

    def test_classify_empty_note(self):
        name, fix = bt._classify("")
        self.assertIsNone(name)

    def test_classify_none_note(self):
        name, fix = bt._classify(None)
        self.assertIsNone(name)

    def test_classify_case_insensitive(self):
        name, _ = bt._classify("EXHAUSTED RETRIES FOR TASK")
        self.assertEqual(name, "exhausted_retries")


class BlockedTriageRequeueTrackingTest(unittest.TestCase):
    """Test [triage:N] requeue count marker tracking."""

    def test_requeue_count_first_attempt(self):
        count = bt._requeue_count("verify rejected: secret-shaped data")
        self.assertEqual(count, 0)

    def test_requeue_count_with_marker_1(self):
        count = bt._requeue_count("verify rejected [triage:1] secret-shaped data")
        self.assertEqual(count, 1)

    def test_requeue_count_with_marker_2(self):
        count = bt._requeue_count("blocked [triage:2] on retry")
        self.assertEqual(count, 2)

    def test_requeue_count_with_marker_3(self):
        count = bt._requeue_count("failed [triage:3]")
        self.assertEqual(count, 3)

    def test_requeue_count_empty_note(self):
        count = bt._requeue_count("")
        self.assertEqual(count, 0)

    def test_requeue_count_marker_at_end(self):
        count = bt._requeue_count("some error [triage:1]")
        self.assertEqual(count, 1)

    def test_requeue_count_multiple_markers_uses_first(self):
        count = bt._requeue_count("[triage:1] error [triage:2]")
        self.assertEqual(count, 1)

    def test_requeue_count_none_note(self):
        count = bt._requeue_count(None)
        self.assertEqual(count, 0)


class BlockedTriageRequeueLogicTest(unittest.TestCase):
    """Test requeue filtering and state transitions."""

    def test_run_returns_stats_structure(self):
        db = MagicMock()
        db.select.return_value = []
        db.insert.return_value = None

        with patch.object(bt, "db", db):
            result = bt.run()

        self.assertIn("scanned", result)
        self.assertIn("requeued", result)
        self.assertIn("escalated", result)
        self.assertIn("unknown", result)
        self.assertIn("too_fresh", result)
        self.assertEqual(result["scanned"], 0)

    def test_run_skips_unknown_blockers(self):
        task = {
            "id": "t1",
            "slug": "mystery-task",
            "note": "some unknown error",
            "updated_at": "2026-07-30T00:00:00Z",
            "state": "BLOCKED",
        }
        updates = []
        db = MagicMock()
        db.select.return_value = [task]
        db.update.side_effect = lambda table, match, patch: updates.append((table, match, patch))
        db.insert.return_value = None

        with patch.object(bt, "db", db):
            result = bt.run()

        self.assertEqual(result["unknown"], 1)
        self.assertEqual(result["requeued"], 0)
        self.assertEqual(result["escalated"], 0)
        db.update.assert_not_called()

    def test_run_respects_max_requeue_limit(self):
        task = {
            "id": "t2",
            "slug": "over-limit-task",
            "note": "verify rejected [triage:2] secret-shaped data",
            "updated_at": "2026-07-30T00:00:00Z",
            "state": "BLOCKED",
        }
        emissions = []
        db = MagicMock()
        db.select.return_value = [task]
        db.insert.return_value = None

        def mock_emit(kind, **kw):
            emissions.append((kind, kw))

        with patch.dict(os.environ, {"ORCH_TRIAGE_MAX_REQUEUES": "2"}), \
             patch.object(bt, "db", db), \
             patch.object(bt, "_emit", side_effect=mock_emit):
            result = bt.run()

        self.assertEqual(result["escalated"], 1)
        self.assertEqual(result["requeued"], 0)

    def test_run_allows_requeue_below_max_limit(self):
        task = {
            "id": "t3",
            "slug": "requeue-me-once",
            "note": "verify rejected [triage:0] secret-shaped data",
            "updated_at": "2026-07-30T00:00:00Z",
            "state": "BLOCKED",
        }
        updates = []
        db = MagicMock()
        db.select.return_value = [task]
        db.update.side_effect = lambda table, match, patch: updates.append((table, match, patch))
        db.insert.return_value = None

        with patch.dict(os.environ, {"ORCH_TRIAGE_MAX_REQUEUES": "2"}), \
             patch.object(bt, "db", db):
            result = bt.run()

        self.assertEqual(result["requeued"], 1)
        self.assertEqual(result["escalated"], 0)

    def test_run_requeue_increments_marker(self):
        task = {
            "id": "t4",
            "slug": "increment-marker",
            "note": "verify rejected [triage:0] secret-shaped data",
            "updated_at": "2026-07-30T00:00:00Z",
            "state": "BLOCKED",
        }
        updates = []
        db = MagicMock()
        db.select.return_value = [task]
        db.update.side_effect = lambda table, match, patch: updates.append((table, match, patch))
        db.insert.return_value = None

        with patch.object(bt, "db", db):
            result = bt.run()

        self.assertEqual(result["requeued"], 1)
        update = updates[0][2]
        self.assertIn("[triage:1]", update["note"])

    def test_run_appends_rework_rules_to_prompt(self):
        task = {
            "id": "t5",
            "slug": "test-rework-rules",
            "note": "permissive allowlist found",
            "updated_at": "2026-07-30T00:00:00Z",
            "state": "BLOCKED",
        }
        updates = []
        db = MagicMock()
        db.select.return_value = [task]
        db.update.side_effect = lambda table, match, patch: updates.append((table, match, patch))
        db.insert.return_value = None

        with patch.object(bt, "db", db):
            bt.run()

        update = updates[0][2]
        self.assertIn("AUTO-TRIAGE REQUEUE", update["prompt"])
        self.assertIn("deny-by-default", update["prompt"])

    def test_run_state_transitions_to_queued(self):
        task = {
            "id": "t6",
            "slug": "state-transition",
            "note": "integrate=BLOCKED (local lock contention)",
            "updated_at": "2026-07-30T00:00:00Z",
            "state": "BLOCKED",
        }
        updates = []
        db = MagicMock()
        db.select.return_value = [task]
        db.update.side_effect = lambda table, match, patch: updates.append((table, match, patch))
        db.insert.return_value = None

        with patch.object(bt, "db", db):
            bt.run()

        update = updates[0][2]
        self.assertEqual(update["state"], "QUEUED")

    def test_run_filters_by_age(self):
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        old = (now - timedelta(minutes=15)).isoformat() + "Z"
        fresh = (now - timedelta(minutes=5)).isoformat() + "Z"

        old_task = {
            "id": "t7",
            "slug": "old-blocked",
            "note": "secret-shaped data",
            "updated_at": old,
            "state": "BLOCKED",
        }
        fresh_task = {
            "id": "t8",
            "slug": "fresh-blocked",
            "note": "secret-shaped data",
            "updated_at": fresh,
            "state": "BLOCKED",
        }
        updates = []
        db = MagicMock()
        db.select.return_value = [old_task, fresh_task]
        db.update.side_effect = lambda table, match, patch: updates.append((table, match, patch))
        db.insert.return_value = None

        with patch.dict(os.environ, {"ORCH_TRIAGE_MIN_AGE_MIN": "10"}), \
             patch.object(bt, "db", db):
            result = bt.run()

        self.assertEqual(result["too_fresh"], 1)
        self.assertEqual(result["requeued"], 1)

    def test_run_batch_limit(self):
        tasks = [
            {
                "id": f"t{i}",
                "slug": f"task-{i}",
                "note": "secret-shaped data",
                "updated_at": "2026-07-30T00:00:00Z",
                "state": "BLOCKED",
            }
            for i in range(20)
        ]
        updates = []
        db = MagicMock()
        db.select.return_value = tasks
        db.update.side_effect = lambda table, match, patch: updates.append((table, match, patch))
        db.insert.return_value = None

        with patch.object(bt, "db", db):
            result = bt.run(limit=5)

        self.assertLessEqual(result["requeued"], 5)


class BlockedTriageIntegrationTest(unittest.TestCase):
    """Integration tests for full triage workflow."""

    def test_secret_shaped_requeue_cycle(self):
        """Full cycle: detect secret-shaped, append rules, requeue."""
        task = {
            "id": "t10",
            "slug": "secret-cycle",
            "note": "verify rejected: added secret to config",
            "updated_at": "2026-07-30T00:00:00Z",
            "state": "BLOCKED",
        }
        updates = []
        db = MagicMock()
        db.select.return_value = [task]
        db.update.side_effect = lambda table, match, patch: updates.append((table, match, patch))
        db.insert.return_value = None

        with patch.object(bt, "db", db):
            result = bt.run()

        self.assertEqual(result["requeued"], 1)
        update = updates[0][2]
        self.assertEqual(update["state"], "QUEUED")
        self.assertIn("[triage:1]", update["note"])
        self.assertIn("env vars referenced by NAME only", update["prompt"])

    def test_contention_retry_workflow(self):
        """Contention retry should not force merge, just re-integrate."""
        task = {
            "id": "t11",
            "slug": "preserve-branch",
            "note": "integrate=BLOCKED (local lock/branch contention)",
            "updated_at": "2026-07-30T00:00:00Z",
            "state": "BLOCKED",
        }
        updates = []
        db = MagicMock()
        db.select.return_value = [task]
        db.update.side_effect = lambda table, match, patch: updates.append((table, match, patch))
        db.insert.return_value = None

        with patch.object(bt, "db", db):
            result = bt.run()

        self.assertEqual(result["requeued"], 1)
        update = updates[0][2]
        self.assertIn("worktree convention", update["prompt"])

    def test_escalation_emits_coordination_event(self):
        """Escalation should emit a coordination event."""
        task = {
            "id": "t12",
            "slug": "escalate-task",
            "note": "blocked [triage:2] secret-shaped",
            "updated_at": "2026-07-30T00:00:00Z",
            "state": "BLOCKED",
        }
        emissions = []
        db = MagicMock()
        db.select.return_value = [task]
        db.insert.return_value = None

        def mock_emit(kind, **kw):
            emissions.append((kind, kw))

        with patch.dict(os.environ, {"ORCH_TRIAGE_MAX_REQUEUES": "2"}), \
             patch.object(bt, "db", db), \
             patch.object(bt, "_emit", side_effect=mock_emit):
            result = bt.run()

        self.assertEqual(result["escalated"], 1)
        self.assertGreater(len(emissions), 0)
        self.assertEqual(emissions[0][0], "triage-escalation")

    def test_digest_persists_to_db(self):
        """Digest should be persisted to coordination_tasks."""
        task = {
            "id": "t13",
            "slug": "persist-digest",
            "note": "secret-shaped data",
            "updated_at": "2026-07-30T00:00:00Z",
            "state": "BLOCKED",
        }
        inserts = []
        db = MagicMock()
        db.select.return_value = [task]
        db.update.return_value = None
        db.insert.side_effect = lambda table, data, **kw: inserts.append((table, data))

        with patch.object(bt, "db", db):
            bt.run()

        # Check that digest was persisted
        digest_inserts = [i for i in inserts if i[0] == "coordination_tasks"]
        self.assertGreater(len(digest_inserts), 0)

    def test_db_errors_gracefully_handled(self):
        """DB errors should not crash the triage."""
        db = MagicMock()
        db.select.side_effect = Exception("DB connection failed")

        with patch.object(bt, "db", db):
            result = bt.run()

        self.assertEqual(result["scanned"], 0)
        self.assertEqual(result["requeued"], 0)


if __name__ == "__main__":
    unittest.main()
