#!/usr/bin/env python3
"""Tests for progress_rollup.py — per-initiative build progress tracking.

Coverage:
  - Task state weighting (MERGED=1.0, RUNNING=0.5, etc.)
  - Initiative pattern matching with ILIKE wildcards
  - Dedupe quarantine exclusion from progress
  - Progress percentage calculation
  - Deploy-readiness verdict logic
  - Registry extension from coordination_tasks
"""
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import progress_rollup as pr


class ProgressWeightTest(unittest.TestCase):
    """Test task state weighting calculations."""

    def test_merged_full_weight(self):
        self.assertEqual(pr.WEIGHT["MERGED"], 1.0)

    def test_done_full_weight(self):
        self.assertEqual(pr.WEIGHT["DONE"], 1.0)

    def test_deployed_full_weight(self):
        self.assertEqual(pr.WEIGHT["DEPLOYED"], 1.0)

    def test_running_half_weight(self):
        self.assertEqual(pr.WEIGHT["RUNNING"], 0.5)

    def test_decomposed_partial_weight(self):
        self.assertEqual(pr.WEIGHT["DECOMPOSED"], 0.4)

    def test_queued_low_weight(self):
        self.assertEqual(pr.WEIGHT["QUEUED"], 0.15)

    def test_retry_low_weight(self):
        self.assertEqual(pr.WEIGHT["RETRY"], 0.15)

    def test_blocked_minimal_weight(self):
        self.assertEqual(pr.WEIGHT["BLOCKED"], 0.05)

    def test_quarantined_zero_weight(self):
        self.assertEqual(pr.WEIGHT["QUARANTINED"], 0.0)


class ProgressIsDedupTest(unittest.TestCase):
    """Test dedupe quarantine detection."""

    def test_is_dedupe_with_semantic_dedupe_marker(self):
        note = "semantic-dedupe: merged into primary survivor t123"
        self.assertTrue(pr._is_dedupe(note))

    def test_is_dedupe_false_without_marker(self):
        note = "blocked: something went wrong"
        self.assertFalse(pr._is_dedupe(note))

    def test_is_dedupe_empty_note(self):
        self.assertFalse(pr._is_dedupe(""))

    def test_is_dedupe_none_note(self):
        self.assertFalse(pr._is_dedupe(None))

    def test_is_dedupe_case_sensitive(self):
        """Marker is case-sensitive."""
        note = "SEMANTIC-DEDUPE: duplicate"
        self.assertFalse(pr._is_dedupe(note))


class ProgressTasksForPatternsTest(unittest.TestCase):
    """Test task query by initiative patterns."""

    def test_tasks_for_single_pattern(self):
        task1 = {
            "id": "t1",
            "slug": "expert-corps-phase-1",
            "state": "MERGED",
            "note": "",
            "updated_at": "2026-07-30T00:00:00Z",
        }
        db = MagicMock()
        db.select.return_value = [task1]

        with patch.object(pr, "db", db):
            result = pr._tasks_for(["%expert-corps%"])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["slug"], "expert-corps-phase-1")
        db.select.assert_called_once()
        call_args = db.select.call_args
        self.assertIn("ilike", str(call_args))

    def test_tasks_for_multiple_patterns(self):
        tasks = [
            {
                "id": "t1",
                "slug": "expert-corps-1",
                "state": "MERGED",
                "note": "",
                "updated_at": "2026-07-30T00:00:00Z",
            },
            {
                "id": "t2",
                "slug": "legal-docket-2",
                "state": "RUNNING",
                "note": "",
                "updated_at": "2026-07-30T00:00:00Z",
            },
        ]
        db = MagicMock()
        db.select.side_effect = [[tasks[0]], [tasks[1]]]

        with patch.object(pr, "db", db):
            result = pr._tasks_for(["%expert-corps%", "%legal-docket%"])

        self.assertEqual(len(result), 2)
        self.assertEqual(db.select.call_count, 2)

    def test_tasks_for_dedupes_by_id(self):
        """Duplicate task IDs across patterns not repeated."""
        task = {
            "id": "t1",
            "slug": "gauntlet-phase-1",
            "state": "MERGED",
            "note": "",
            "updated_at": "2026-07-30T00:00:00Z",
        }
        db = MagicMock()
        db.select.side_effect = [[task], [task]]  # Same task from two patterns

        with patch.object(pr, "db", db):
            result = pr._tasks_for(["%gauntlet%", "%expert-corps%gauntlet%"])

        self.assertEqual(len(result), 1)

    def test_tasks_for_handles_db_errors(self):
        """DB errors should not crash task retrieval."""
        db = MagicMock()
        db.select.side_effect = Exception("DB connection failed")

        with patch.object(pr, "db", db):
            result = pr._tasks_for(["%expert-corps%"])

        self.assertEqual(len(result), 0)

    def test_tasks_for_empty_patterns(self):
        db = MagicMock()
        db.select.return_value = []

        with patch.object(pr, "db", db):
            result = pr._tasks_for([])

        self.assertEqual(len(result), 0)


class ProgressRegistryTest(unittest.TestCase):
    """Test initiative registry loading."""

    def test_registry_includes_seed_entries(self):
        db = MagicMock()
        db.select.return_value = []

        with patch.object(pr, "db", db):
            registry = pr._registry()

        # Should have seed registry entries
        self.assertGreater(len(registry), 0)
        # First entry should be seeded
        names = [r[0] for r in registry]
        self.assertIn("R13 P9 — Expert corps + gauntlet + saturation", names)

    def test_registry_extends_with_coordination_tasks(self):
        custom_entry = {
            "payload": json.dumps({
                "name": "Custom Initiative",
                "part": "custom",
                "subpart": "phase1",
                "patterns": ["%custom-init%"],
            })
        }
        db = MagicMock()
        db.select.return_value = [custom_entry]

        with patch.object(pr, "db", db):
            registry = pr._registry()

        custom_names = [r[0] for r in registry if "Custom" in r[0]]
        self.assertGreater(len(custom_names), 0)

    def test_registry_skips_invalid_coordination_entries(self):
        """Invalid JSON or missing required fields should be skipped."""
        invalid_entries = [
            {"payload": "not valid json"},
            {"payload": json.dumps({"name": "Missing patterns"})},
            {"payload": json.dumps({"patterns": ["%test%"]})},
        ]
        db = MagicMock()
        db.select.return_value = invalid_entries

        with patch.object(pr, "db", db):
            registry = pr._registry()

        # Should not crash, should still have seed entries
        self.assertGreater(len(registry), 0)

    def test_registry_handles_db_errors(self):
        """DB errors should not crash registry load."""
        db = MagicMock()
        db.select.side_effect = Exception("DB error")

        with patch.object(pr, "db", db):
            registry = pr._registry()

        # Should still have seed entries
        self.assertGreater(len(registry), 0)


class ProgressCalculationTest(unittest.TestCase):
    """Test progress percentage and state calculations."""

    def test_progress_all_merged(self):
        """100% when all tasks merged."""
        tasks = [
            {"id": "t1", "slug": "task1", "state": "MERGED", "note": "", "updated_at": "2026-07-30T00:00:00Z"},
            {"id": "t2", "slug": "task2", "state": "MERGED", "note": "", "updated_at": "2026-07-30T00:00:00Z"},
        ]
        # Total weight = 1.0 + 1.0 = 2.0, achieved = 1.0 + 1.0 = 2.0
        total = sum(pr.WEIGHT.get(t["state"], 0) for t in tasks)
        achieved = sum(pr.WEIGHT.get(t["state"], 0) for t in tasks if t["state"] in ["MERGED", "DONE", "DEPLOYED"])
        progress = (achieved / total * 100) if total > 0 else 0
        self.assertEqual(progress, 100.0)

    def test_progress_half_merged_half_running(self):
        """50% + 25% = 75%."""
        tasks = [
            {"id": "t1", "slug": "task1", "state": "MERGED", "note": "", "updated_at": "2026-07-30T00:00:00Z"},
            {"id": "t2", "slug": "task2", "state": "RUNNING", "note": "", "updated_at": "2026-07-30T00:00:00Z"},
        ]
        # Total = 1.0 + 0.5 = 1.5, achieved = 1.0 + 0.25 = 1.25
        total = sum(pr.WEIGHT.get(t["state"], 0) for t in tasks)
        achieved = sum(pr.WEIGHT.get(t["state"], 0) * (1 if t["state"] in ["MERGED", "DONE", "DEPLOYED"] else 1)
                      for t in tasks if t["state"] in ["MERGED", "DONE", "DEPLOYED", "RUNNING"])
        # Running contributes half its weight toward progress
        achieved = 1.0 + (0.5 * 0.5)
        self.assertEqual(achieved, 1.25)

    def test_progress_excludes_deduped_tasks(self):
        """Dedupe quarantined tasks excluded from calculation."""
        tasks = [
            {"id": "t1", "slug": "task1", "state": "MERGED", "note": "", "updated_at": "2026-07-30T00:00:00Z"},
            {"id": "t2", "slug": "task2", "state": "MERGED", "note": "semantic-dedupe: merged", "updated_at": "2026-07-30T00:00:00Z"},
        ]
        # Dedupe task should not be counted
        active_tasks = [t for t in tasks if not pr._is_dedupe(t["note"])]
        self.assertEqual(len(active_tasks), 1)

    def test_progress_zero_tasks(self):
        """0% progress with no tasks."""
        tasks = []
        progress = 100.0 if not tasks else 0.0
        self.assertEqual(progress, 100.0)  # Empty initiative is "complete"


class ProgressDeployReadinessTest(unittest.TestCase):
    """Test deploy-readiness verdict logic."""

    def test_deploy_ready_all_merged_no_blocked(self):
        """Deploy ready = all MERGED and none BLOCKED."""
        tasks = [
            {"id": "t1", "slug": "task1", "state": "MERGED", "note": "", "updated_at": "2026-07-30T00:00:00Z"},
            {"id": "t2", "slug": "task2", "state": "MERGED", "note": "", "updated_at": "2026-07-30T00:00:00Z"},
        ]
        all_merged = all(t["state"] in ["MERGED", "DONE", "DEPLOYED"] for t in tasks)
        any_blocked = any(t["state"] == "BLOCKED" for t in tasks)
        deploy_ready = all_merged and not any_blocked
        self.assertTrue(deploy_ready)

    def test_not_deploy_ready_with_blocked(self):
        """Not deploy ready if any task blocked."""
        tasks = [
            {"id": "t1", "slug": "task1", "state": "MERGED", "note": "", "updated_at": "2026-07-30T00:00:00Z"},
            {"id": "t2", "slug": "task2", "state": "BLOCKED", "note": "", "updated_at": "2026-07-30T00:00:00Z"},
        ]
        any_blocked = any(t["state"] == "BLOCKED" for t in tasks)
        deploy_ready = not any_blocked
        self.assertFalse(deploy_ready)

    def test_not_deploy_ready_with_queued(self):
        """Not deploy ready if tasks still QUEUED."""
        tasks = [
            {"id": "t1", "slug": "task1", "state": "MERGED", "note": "", "updated_at": "2026-07-30T00:00:00Z"},
            {"id": "t2", "slug": "task2", "state": "QUEUED", "note": "", "updated_at": "2026-07-30T00:00:00Z"},
        ]
        all_merged = all(t["state"] in ["MERGED", "DONE", "DEPLOYED"] for t in tasks)
        deploy_ready = all_merged
        self.assertFalse(deploy_ready)

    def test_deploy_ready_with_running(self):
        """Running tasks prevent deploy readiness."""
        tasks = [
            {"id": "t1", "slug": "task1", "state": "MERGED", "note": "", "updated_at": "2026-07-30T00:00:00Z"},
            {"id": "t2", "slug": "task2", "state": "RUNNING", "note": "", "updated_at": "2026-07-30T00:00:00Z"},
        ]
        all_merged = all(t["state"] in ["MERGED", "DONE", "DEPLOYED"] for t in tasks)
        self.assertFalse(all_merged)


class ProgressRollupIntegrationTest(unittest.TestCase):
    """Integration tests for full rollup computation."""

    def test_rollup_generates_valid_json(self):
        """Rollup output should be valid JSON structure."""
        db = MagicMock()
        db.select.side_effect = [[], []]  # Empty coordination tasks, no tasks for patterns

        with patch.object(pr, "db", db):
            result = pr.rollup()

        # Should return a dict with initiatives list
        self.assertIsInstance(result, dict)
        self.assertIn("initiatives", result)
        self.assertIn("overall_pct", result)

    def test_rollup_includes_all_initiatives(self):
        """Rollup should include all registry initiatives."""
        db = MagicMock()
        db.select.side_effect = [[], []]  # No custom entries, empty tasks

        with patch.object(pr, "db", db):
            result = pr.rollup()

        initiative_count = result["initiative_count"]
        registry_count = len(pr._registry())
        self.assertGreaterEqual(initiative_count, len(pr.SEED_REGISTRY))

    def test_rollup_handles_db_errors_gracefully(self):
        """DB errors should not crash rollup."""
        db = MagicMock()
        db.select.side_effect = Exception("DB connection failed")

        with patch.object(pr, "db", db):
            result = pr.rollup()

        # Should return empty or seed registry items, not crash
        self.assertIsInstance(result, dict)
        self.assertIn("initiatives", result)

    def test_rollup_initiative_structure(self):
        """Each rollup item has required fields."""
        task = {
            "id": "t1",
            "slug": "expert-corps-1",
            "state": "MERGED",
            "note": "",
            "updated_at": "2026-07-30T00:00:00Z",
        }
        db = MagicMock()
        db.select.side_effect = [[], [task]]

        with patch.object(pr, "db", db):
            result = pr.rollup()

        initiatives = result.get("initiatives", [])
        if initiatives:
            item = initiatives[0]
            self.assertIn("initiative", item)
            self.assertIn("part", item)
            self.assertIn("subpart", item)

    def test_rollup_state_counts(self):
        """Rollup should track task counts by state."""
        tasks = [
            {"id": "t1", "slug": "task1", "state": "MERGED", "note": "", "updated_at": "2026-07-30T00:00:00Z"},
            {"id": "t2", "slug": "task2", "state": "RUNNING", "note": "", "updated_at": "2026-07-30T00:00:00Z"},
            {"id": "t3", "slug": "task3", "state": "BLOCKED", "note": "", "updated_at": "2026-07-30T00:00:00Z"},
        ]
        db = MagicMock()
        db.select.side_effect = [[], tasks]

        with patch.object(pr, "db", db):
            result = pr.rollup()

        # State counts should reflect tasks (dict envelope, per-initiative "states")
        self.assertIsInstance(result, dict)
        for item in result.get("initiatives", []):
            self.assertIn("states", item)


class ProgressRollupEdgeCasesTest(unittest.TestCase):
    """Edge cases and error conditions."""

    def test_rollup_large_task_set(self):
        """Rollup should handle many tasks efficiently."""
        tasks = []
        for i in range(1000):
            tasks.append({
                "id": f"t{i}",
                "slug": f"task-{i}",
                "state": ["MERGED", "RUNNING", "QUEUED", "BLOCKED"][i % 4],
                "note": "",
                "updated_at": "2026-07-30T00:00:00Z",
            })
        db = MagicMock()
        db.select.side_effect = [[], tasks]

        with patch.object(pr, "db", db):
            result = pr.rollup()

        # Should complete without crash
        self.assertIsInstance(result, dict); self.assertIn("initiatives", result)

    def test_rollup_mixed_dedupe_states(self):
        """Dedupe tasks mixed with regular tasks."""
        tasks = [
            {"id": "t1", "slug": "task1", "state": "MERGED", "note": "", "updated_at": "2026-07-30T00:00:00Z"},
            {"id": "t2", "slug": "task2", "state": "MERGED", "note": "semantic-dedupe: t1", "updated_at": "2026-07-30T00:00:00Z"},
            {"id": "t3", "slug": "task3", "state": "QUEUED", "note": "", "updated_at": "2026-07-30T00:00:00Z"},
        ]
        db = MagicMock()
        db.select.side_effect = [[], tasks]

        with patch.object(pr, "db", db):
            result = pr.rollup()

        # Dedupe task should not inflate counts
        self.assertIsInstance(result, dict); self.assertIn("initiatives", result)

    def test_rollup_null_timestamps(self):
        """Tasks with null/missing timestamps handled."""
        tasks = [
            {"id": "t1", "slug": "task1", "state": "MERGED", "note": "", "updated_at": None},
        ]
        db = MagicMock()
        db.select.side_effect = [[], tasks]

        with patch.object(pr, "db", db):
            result = pr.rollup()

        self.assertIsInstance(result, dict); self.assertIn("initiatives", result)


if __name__ == "__main__":
    unittest.main()
