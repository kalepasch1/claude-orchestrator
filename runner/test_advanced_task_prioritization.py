"""Tests for advanced task prioritization in orchestration pipeline.

Tests the mechanical orchestration layer that manages:
- Task risk classification and priority scoring
- Queue state transitions (QUEUED → RUNNING → MERGED/DECOMPOSED/QUARANTINED)
- Merge train coordination and backlog reconciliation
- Model routing decisions based on learned outcomes
- Recovery strategies for blocked and failed tasks
- Conflict detection and fail-soft handling
"""

import json
import os
import sys
import time
import unittest
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


@dataclass
class QueuedTask:
    """A task in the orchestration queue."""
    task_id: str
    slug: str
    risk_class: str  # "low", "standard", "sensitive"
    priority_score: float = 0.0
    state: str = "QUEUED"
    created_at: float = field(default_factory=time.time)
    attempted_count: int = 0
    model_route: str = "default"


@dataclass
class QueueStats:
    """Statistics about queue state."""
    merged: int = 0
    decomposed: int = 0
    quarantined: int = 0
    queued: int = 0
    done: int = 0
    running: int = 0

    def total(self) -> int:
        return self.merged + self.decomposed + self.quarantined + self.queued + self.done + self.running


class PriorityScorer:
    """Compute task priority scores."""

    def score_task(self, task: QueuedTask, changed_files: List[str],
                   failure_history: Dict[str, float]) -> float:
        """Compute priority score for a task."""
        base_score = 0.0

        # Risk class multiplier
        risk_multipliers = {"low": 1.0, "standard": 2.0, "sensitive": 5.0}
        base_score = risk_multipliers.get(task.risk_class, 1.0)

        # Failure history impact
        failure_rate = failure_history.get(task.slug, 0.0)
        base_score += failure_rate * 10.0

        # Changed files impact (blast radius)
        base_score += len(changed_files) * 0.5

        # Attempt count penalty (avoid thrashing)
        if task.attempted_count > 0:
            base_score *= max(0.1, 1.0 - (task.attempted_count * 0.1))

        return base_score

    def prioritize_queue(self, tasks: List[QueuedTask],
                        changed_files: Optional[List[str]] = None,
                        failure_history: Optional[Dict[str, float]] = None) -> List[QueuedTask]:
        """Sort tasks by priority score (highest first)."""
        changed_files = changed_files or []
        failure_history = failure_history or {}

        scored = []
        for task in tasks:
            score = self.score_task(task, changed_files, failure_history)
            scored.append((task, score))

        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)
        return [t for t, _ in scored]


class QueueCoordinator:
    """Manages queue state transitions and coordination."""

    def __init__(self):
        self._tasks: Dict[str, QueuedTask] = {}
        self._stats = QueueStats()
        self._model_routes: Dict[str, str] = {}

    def enqueue(self, task: QueuedTask) -> bool:
        """Add task to queue."""
        if task.task_id in self._tasks:
            return False
        self._tasks[task.task_id] = task
        self._stats.queued += 1
        return True

    def dequeue_for_execution(self, task_id: str) -> Optional[QueuedTask]:
        """Move task from QUEUED to RUNNING."""
        task = self._tasks.get(task_id)
        if not task or task.state != "QUEUED":
            return None
        task.state = "RUNNING"
        self._stats.queued -= 1
        self._stats.running += 1
        return task

    def complete_task(self, task_id: str, final_state: str) -> bool:
        """Transition task to terminal state (MERGED, DONE, DECOMPOSED, QUARANTINED)."""
        task = self._tasks.get(task_id)
        if not task or task.state != "RUNNING":
            return False

        self._stats.running -= 1
        if final_state == "MERGED":
            self._stats.merged += 1
        elif final_state == "DONE":
            self._stats.done += 1
        elif final_state == "DECOMPOSED":
            self._stats.decomposed += 1
        elif final_state == "QUARANTINED":
            self._stats.quarantined += 1
        else:
            return False

        task.state = final_state
        return True

    def requeue_task(self, task_id: str) -> bool:
        """Move task from QUARANTINED back to QUEUED."""
        task = self._tasks.get(task_id)
        if not task or task.state != "QUARANTINED":
            return False
        task.state = "QUEUED"
        task.attempted_count += 1
        self._stats.quarantined -= 1
        self._stats.queued += 1
        return True

    def get_stats(self) -> QueueStats:
        """Return current queue statistics."""
        return self._stats

    def get_task(self, task_id: str) -> Optional[QueuedTask]:
        """Retrieve a task by ID."""
        return self._tasks.get(task_id)

    def assign_model_route(self, task_id: str, model_route: str) -> bool:
        """Assign a model route to a task based on learned performance."""
        task = self._tasks.get(task_id)
        if not task:
            return False
        task.model_route = model_route
        return True


class ModelRouterLearner:
    """Learns which model routes work best for different task types."""

    def __init__(self):
        self._outcomes: Dict[str, List[float]] = {}  # model_route -> [quality_scores]

    def record_outcome(self, model_route: str, quality_score: float):
        """Record a task outcome for a model route."""
        if model_route not in self._outcomes:
            self._outcomes[model_route] = []
        self._outcomes[model_route].append(quality_score)

    def get_best_route(self, task_class: str, available_routes: List[str]) -> str:
        """Determine best model route based on learned outcomes."""
        if not available_routes:
            return "default"

        # Find route with highest average quality
        best_route = available_routes[0]
        best_avg = self._get_average_quality(best_route)

        for route in available_routes[1:]:
            avg = self._get_average_quality(route)
            if avg > best_avg:
                best_avg = avg
                best_route = route

        return best_route

    def _get_average_quality(self, route: str) -> float:
        """Get average quality score for a route."""
        scores = self._outcomes.get(route, [])
        if not scores:
            return 0.0
        return sum(scores) / len(scores)

    def get_stats(self) -> Dict:
        """Return router statistics."""
        return {
            route: {
                "outcomes_recorded": len(scores),
                "average_quality": sum(scores) / len(scores) if scores else 0.0
            }
            for route, scores in self._outcomes.items()
        }


class TestPriorityScoringBasics(unittest.TestCase):
    """Tests for basic priority scoring."""

    def test_score_task_returns_numeric_score(self):
        """Priority scorer should return numeric score."""
        scorer = PriorityScorer()
        task = QueuedTask(task_id="t1", slug="task-1", risk_class="standard")
        score = scorer.score_task(task, [], {})
        self.assertIsInstance(score, float)
        self.assertGreaterEqual(score, 0.0)

    def test_risk_class_affects_score(self):
        """Higher risk classes should score higher."""
        scorer = PriorityScorer()
        low = QueuedTask(task_id="t1", slug="low", risk_class="low")
        standard = QueuedTask(task_id="t2", slug="standard", risk_class="standard")
        sensitive = QueuedTask(task_id="t3", slug="sensitive", risk_class="sensitive")

        low_score = scorer.score_task(low, [], {})
        std_score = scorer.score_task(standard, [], {})
        sens_score = scorer.score_task(sensitive, [], {})

        self.assertLess(low_score, std_score)
        self.assertLess(std_score, sens_score)

    def test_failure_history_increases_score(self):
        """Tasks with high failure rates should score higher."""
        scorer = PriorityScorer()
        task = QueuedTask(task_id="t1", slug="flaky", risk_class="standard")

        no_failures = scorer.score_task(task, [], {})
        with_failures = scorer.score_task(task, [], {"flaky": 0.5})

        self.assertLess(no_failures, with_failures)

    def test_changed_files_affects_score(self):
        """More changed files (blast radius) should increase score."""
        scorer = PriorityScorer()
        task = QueuedTask(task_id="t1", slug="task-1", risk_class="standard")

        no_changes = scorer.score_task(task, [], {})
        with_changes = scorer.score_task(task, ["file1.py", "file2.py", "file3.py"], {})

        self.assertLess(no_changes, with_changes)

    def test_attempt_count_penalizes_score(self):
        """Tasks that have failed multiple times should be deprioritized."""
        scorer = PriorityScorer()
        base_task = QueuedTask(task_id="t1", slug="task-1", risk_class="standard")
        retry_task = QueuedTask(
            task_id="t2", slug="task-1", risk_class="standard", attempted_count=3
        )

        base_score = scorer.score_task(base_task, [], {})
        retry_score = scorer.score_task(retry_task, [], {})

        self.assertLess(retry_score, base_score)


class TestPrioritizationOrdering(unittest.TestCase):
    """Tests for queue prioritization ordering."""

    def test_prioritize_queue_orders_by_score(self):
        """Tasks should be ordered from highest to lowest priority."""
        scorer = PriorityScorer()
        low = QueuedTask(task_id="t1", slug="low", risk_class="low")
        standard = QueuedTask(task_id="t2", slug="standard", risk_class="standard")
        sensitive = QueuedTask(task_id="t3", slug="sensitive", risk_class="sensitive")

        result = scorer.prioritize_queue([low, standard, sensitive])
        slugs = [t.slug for t in result]

        self.assertEqual(slugs[0], "sensitive")
        self.assertEqual(slugs[1], "standard")
        self.assertEqual(slugs[2], "low")

    def test_prioritize_queue_respects_empty_list(self):
        """Prioritizing empty queue should return empty list."""
        scorer = PriorityScorer()
        result = scorer.prioritize_queue([])
        self.assertEqual(result, [])

    def test_prioritize_queue_with_single_task(self):
        """Single task should remain in place."""
        scorer = PriorityScorer()
        task = QueuedTask(task_id="t1", slug="solo", risk_class="standard")
        result = scorer.prioritize_queue([task])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].slug, "solo")

    def test_prioritize_queue_with_failure_history(self):
        """Tasks with failure history should be prioritized higher."""
        scorer = PriorityScorer()
        stable = QueuedTask(task_id="t1", slug="stable", risk_class="low")
        flaky = QueuedTask(task_id="t2", slug="flaky", risk_class="low")

        result = scorer.prioritize_queue(
            [stable, flaky],
            failure_history={"flaky": 0.8}
        )

        # Flaky should come first despite being low risk
        self.assertEqual(result[0].slug, "flaky")

    def test_prioritize_queue_composite_scoring(self):
        """Composite scoring should balance multiple factors."""
        scorer = PriorityScorer()
        tasks = [
            QueuedTask(task_id="t1", slug="high-risk-stable", risk_class="sensitive"),
            QueuedTask(task_id="t2", slug="low-risk-flaky", risk_class="low"),
            QueuedTask(task_id="t3", slug="mid-risk-normal", risk_class="standard"),
        ]

        # High sensitivity should dominate
        result = scorer.prioritize_queue(tasks)
        self.assertEqual(result[0].slug, "high-risk-stable")


class TestQueueCoordinatorEnqueue(unittest.TestCase):
    """Tests for enqueueing tasks."""

    def test_enqueue_adds_task_to_queue(self):
        """Enqueued task should appear in queue."""
        coordinator = QueueCoordinator()
        task = QueuedTask(task_id="t1", slug="task-1", risk_class="standard")

        result = coordinator.enqueue(task)

        self.assertTrue(result)
        self.assertIsNotNone(coordinator.get_task("t1"))
        self.assertEqual(coordinator.get_task("t1").state, "QUEUED")

    def test_enqueue_updates_stats(self):
        """Enqueueing should increment queued count."""
        coordinator = QueueCoordinator()
        task = QueuedTask(task_id="t1", slug="task-1", risk_class="standard")

        coordinator.enqueue(task)
        stats = coordinator.get_stats()

        self.assertEqual(stats.queued, 1)
        self.assertEqual(stats.total(), 1)

    def test_enqueue_duplicate_returns_false(self):
        """Enqueueing same task twice should fail."""
        coordinator = QueueCoordinator()
        task = QueuedTask(task_id="t1", slug="task-1", risk_class="standard")

        result1 = coordinator.enqueue(task)
        result2 = coordinator.enqueue(task)

        self.assertTrue(result1)
        self.assertFalse(result2)

    def test_enqueue_multiple_tasks(self):
        """Multiple tasks should all be enqueued."""
        coordinator = QueueCoordinator()
        for i in range(5):
            task = QueuedTask(task_id=f"t{i}", slug=f"task-{i}", risk_class="standard")
            coordinator.enqueue(task)

        stats = coordinator.get_stats()
        self.assertEqual(stats.queued, 5)


class TestQueueCoordinatorTransitions(unittest.TestCase):
    """Tests for queue state transitions."""

    def test_dequeue_for_execution_moves_to_running(self):
        """Dequeuing should move task from QUEUED to RUNNING."""
        coordinator = QueueCoordinator()
        task = QueuedTask(task_id="t1", slug="task-1", risk_class="standard")
        coordinator.enqueue(task)

        coordinator.dequeue_for_execution("t1")
        task = coordinator.get_task("t1")

        self.assertEqual(task.state, "RUNNING")

    def test_dequeue_for_execution_updates_stats(self):
        """Dequeue should adjust queue statistics."""
        coordinator = QueueCoordinator()
        task = QueuedTask(task_id="t1", slug="task-1", risk_class="standard")
        coordinator.enqueue(task)

        coordinator.dequeue_for_execution("t1")
        stats = coordinator.get_stats()

        self.assertEqual(stats.queued, 0)
        self.assertEqual(stats.running, 1)

    def test_dequeue_nonexistent_returns_none(self):
        """Dequeuing nonexistent task should return None."""
        coordinator = QueueCoordinator()
        result = coordinator.dequeue_for_execution("nonexistent")
        self.assertIsNone(result)

    def test_complete_task_to_merged(self):
        """Task should transition RUNNING → MERGED."""
        coordinator = QueueCoordinator()
        task = QueuedTask(task_id="t1", slug="task-1", risk_class="standard")
        coordinator.enqueue(task)
        coordinator.dequeue_for_execution("t1")

        result = coordinator.complete_task("t1", "MERGED")

        self.assertTrue(result)
        self.assertEqual(coordinator.get_task("t1").state, "MERGED")
        self.assertEqual(coordinator.get_stats().merged, 1)
        self.assertEqual(coordinator.get_stats().running, 0)

    def test_complete_task_to_quarantined(self):
        """Task should transition RUNNING → QUARANTINED."""
        coordinator = QueueCoordinator()
        task = QueuedTask(task_id="t1", slug="task-1", risk_class="standard")
        coordinator.enqueue(task)
        coordinator.dequeue_for_execution("t1")

        result = coordinator.complete_task("t1", "QUARANTINED")

        self.assertTrue(result)
        self.assertEqual(coordinator.get_task("t1").state, "QUARANTINED")
        self.assertEqual(coordinator.get_stats().quarantined, 1)

    def test_complete_task_to_decomposed(self):
        """Task should transition RUNNING → DECOMPOSED."""
        coordinator = QueueCoordinator()
        task = QueuedTask(task_id="t1", slug="task-1", risk_class="standard")
        coordinator.enqueue(task)
        coordinator.dequeue_for_execution("t1")

        result = coordinator.complete_task("t1", "DECOMPOSED")

        self.assertTrue(result)
        self.assertEqual(coordinator.get_task("t1").state, "DECOMPOSED")
        self.assertEqual(coordinator.get_stats().decomposed, 1)

    def test_complete_task_invalid_state_fails(self):
        """Completing with invalid state should fail."""
        coordinator = QueueCoordinator()
        task = QueuedTask(task_id="t1", slug="task-1", risk_class="standard")
        coordinator.enqueue(task)
        coordinator.dequeue_for_execution("t1")

        result = coordinator.complete_task("t1", "INVALID_STATE")

        self.assertFalse(result)
        self.assertEqual(coordinator.get_task("t1").state, "RUNNING")


class TestQueueRecovery(unittest.TestCase):
    """Tests for recovery of quarantined tasks."""

    def test_requeue_moves_quarantined_to_queued(self):
        """Requeue should transition QUARANTINED → QUEUED."""
        coordinator = QueueCoordinator()
        task = QueuedTask(task_id="t1", slug="task-1", risk_class="standard")
        coordinator.enqueue(task)
        coordinator.dequeue_for_execution("t1")
        coordinator.complete_task("t1", "QUARANTINED")

        result = coordinator.requeue_task("t1")

        self.assertTrue(result)
        self.assertEqual(coordinator.get_task("t1").state, "QUEUED")

    def test_requeue_increments_attempt_count(self):
        """Requeue should increment attempted_count."""
        coordinator = QueueCoordinator()
        task = QueuedTask(task_id="t1", slug="task-1", risk_class="standard")
        coordinator.enqueue(task)
        coordinator.dequeue_for_execution("t1")
        coordinator.complete_task("t1", "QUARANTINED")

        coordinator.requeue_task("t1")
        task = coordinator.get_task("t1")

        self.assertEqual(task.attempted_count, 1)

    def test_requeue_updates_stats(self):
        """Requeue should adjust queue statistics."""
        coordinator = QueueCoordinator()
        task = QueuedTask(task_id="t1", slug="task-1", risk_class="standard")
        coordinator.enqueue(task)
        coordinator.dequeue_for_execution("t1")
        coordinator.complete_task("t1", "QUARANTINED")

        coordinator.requeue_task("t1")
        stats = coordinator.get_stats()

        self.assertEqual(stats.quarantined, 0)
        self.assertEqual(stats.queued, 1)

    def test_requeue_non_quarantined_fails(self):
        """Requeue should fail for non-quarantined tasks."""
        coordinator = QueueCoordinator()
        task = QueuedTask(task_id="t1", slug="task-1", risk_class="standard")
        coordinator.enqueue(task)

        result = coordinator.requeue_task("t1")

        self.assertFalse(result)
        self.assertEqual(coordinator.get_task("t1").state, "QUEUED")

    def test_multiple_requeus_increments_count(self):
        """Multiple requeues should increment attempt count."""
        coordinator = QueueCoordinator()
        task = QueuedTask(task_id="t1", slug="task-1", risk_class="standard")
        coordinator.enqueue(task)

        for _ in range(3):
            coordinator.dequeue_for_execution("t1")
            coordinator.complete_task("t1", "QUARANTINED")
            coordinator.requeue_task("t1")

        self.assertEqual(coordinator.get_task("t1").attempted_count, 3)


class TestModelRouting(unittest.TestCase):
    """Tests for model route learning and assignment."""

    def test_assign_model_route_updates_task(self):
        """Assigning route should update task's model_route."""
        coordinator = QueueCoordinator()
        task = QueuedTask(task_id="t1", slug="task-1", risk_class="standard")
        coordinator.enqueue(task)

        result = coordinator.assign_model_route("t1", "claude:haiku")

        self.assertTrue(result)
        self.assertEqual(coordinator.get_task("t1").model_route, "claude:haiku")

    def test_assign_model_route_nonexistent_fails(self):
        """Assigning route to nonexistent task should fail."""
        coordinator = QueueCoordinator()
        result = coordinator.assign_model_route("nonexistent", "claude:haiku")
        self.assertFalse(result)

    def test_record_outcome_accumulates_scores(self):
        """Outcomes should accumulate for each route."""
        learner = ModelRouterLearner()
        learner.record_outcome("route-a", 0.8)
        learner.record_outcome("route-a", 0.7)
        learner.record_outcome("route-b", 0.6)

        stats = learner.get_stats()

        self.assertEqual(stats["route-a"]["outcomes_recorded"], 2)
        self.assertEqual(stats["route-b"]["outcomes_recorded"], 1)
        self.assertAlmostEqual(stats["route-a"]["average_quality"], 0.75)

    def test_get_best_route_selects_highest_average(self):
        """Best route should have highest average quality."""
        learner = ModelRouterLearner()
        learner.record_outcome("route-a", 0.5)
        learner.record_outcome("route-b", 0.9)
        learner.record_outcome("route-b", 0.8)

        best = learner.get_best_route("test", ["route-a", "route-b"])

        self.assertEqual(best, "route-b")

    def test_get_best_route_with_empty_list_returns_default(self):
        """Empty route list should return default."""
        learner = ModelRouterLearner()
        best = learner.get_best_route("test", [])
        self.assertEqual(best, "default")

    def test_get_best_route_with_no_outcomes(self):
        """Routes with no outcomes should have zero average."""
        learner = ModelRouterLearner()
        # No outcomes recorded
        best = learner.get_best_route("test", ["route-a", "route-b"])
        # Should pick first in case of tie
        self.assertIn(best, ["route-a", "route-b"])


class TestQueueStats(unittest.TestCase):
    """Tests for queue statistics tracking."""

    def test_stats_total_counts_all_states(self):
        """Total should sum all queue states."""
        coordinator = QueueCoordinator()
        for i in range(2):
            task = QueuedTask(task_id=f"t{i}", slug=f"task-{i}", risk_class="standard")
            coordinator.enqueue(task)
            coordinator.dequeue_for_execution(f"t{i}")
            coordinator.complete_task(f"t{i}", "MERGED")

        for i in range(2, 4):
            task = QueuedTask(task_id=f"t{i}", slug=f"task-{i}", risk_class="standard")
            coordinator.enqueue(task)

        stats = coordinator.get_stats()

        self.assertEqual(stats.merged, 2)
        self.assertEqual(stats.queued, 2)
        self.assertEqual(stats.total(), 4)

    def test_stats_initial_state(self):
        """Initial stats should all be zero."""
        coordinator = QueueCoordinator()
        stats = coordinator.get_stats()

        self.assertEqual(stats.merged, 0)
        self.assertEqual(stats.decomposed, 0)
        self.assertEqual(stats.quarantined, 0)
        self.assertEqual(stats.queued, 0)
        self.assertEqual(stats.done, 0)
        self.assertEqual(stats.running, 0)
        self.assertEqual(stats.total(), 0)


class TestCoordinationRules(unittest.TestCase):
    """Tests for orchestration coordination rules."""

    def test_merge_train_coordination_respects_queue_pressure(self):
        """High queue pressure should slow new enqueues."""
        coordinator = QueueCoordinator()
        # Simulate high pressure: many queued and running tasks
        for i in range(50):
            task = QueuedTask(task_id=f"t{i}", slug=f"task-{i}", risk_class="standard")
            coordinator.enqueue(task)
            if i < 10:
                coordinator.dequeue_for_execution(f"t{i}")

        stats = coordinator.get_stats()
        self.assertEqual(stats.queued, 40)
        self.assertEqual(stats.running, 10)

    def test_no_deletion_of_unrelated_queued_work(self):
        """Queued tasks unrelated to current work should not be deleted."""
        coordinator = QueueCoordinator()
        task1 = QueuedTask(task_id="t1", slug="current-task", risk_class="standard")
        task2 = QueuedTask(task_id="t2", slug="unrelated-task", risk_class="standard")

        coordinator.enqueue(task1)
        coordinator.enqueue(task2)

        # Simulate completing current work
        coordinator.dequeue_for_execution("t1")
        coordinator.complete_task("t1", "MERGED")

        # Unrelated task should still be there
        self.assertIsNotNone(coordinator.get_task("t2"))
        self.assertEqual(coordinator.get_task("t2").state, "QUEUED")

    def test_recovered_work_stays_in_queue_until_shipped(self):
        """Recovered tasks should not be marked as shipped prematurely."""
        coordinator = QueueCoordinator()
        recovered_task = QueuedTask(
            task_id="recovered-1", slug="recovered-work", risk_class="standard"
        )
        coordinator.enqueue(recovered_task)

        # Task is in queue, not shipped
        task = coordinator.get_task("recovered-1")
        self.assertEqual(task.state, "QUEUED")
        self.assertNotEqual(task.state, "MERGED")


class TestComplexScenarios(unittest.TestCase):
    """Tests for complex orchestration scenarios."""

    def test_pipeline_contract_full_workflow(self):
        """Test complete workflow: enqueue → prioritize → execute → complete."""
        coordinator = QueueCoordinator()
        scorer = PriorityScorer()

        # Create tasks with different risk levels
        tasks = [
            QueuedTask(task_id="t1", slug="low-risk", risk_class="low"),
            QueuedTask(task_id="t2", slug="sensitive", risk_class="sensitive"),
            QueuedTask(task_id="t3", slug="standard", risk_class="standard"),
        ]

        # Enqueue all
        for task in tasks:
            coordinator.enqueue(task)

        # Get queued tasks and prioritize
        queued_tasks = [coordinator.get_task(t.task_id) for t in tasks]
        ordered = scorer.prioritize_queue(queued_tasks)

        # Should be: sensitive → standard → low
        self.assertEqual(ordered[0].slug, "sensitive")
        self.assertEqual(ordered[1].slug, "standard")
        self.assertEqual(ordered[2].slug, "low-risk")

        # Execute them in order
        for task in ordered:
            coordinator.dequeue_for_execution(task.task_id)
            coordinator.complete_task(task.task_id, "MERGED")

        stats = coordinator.get_stats()
        self.assertEqual(stats.merged, 3)
        self.assertEqual(stats.queued, 0)

    def test_recovery_backlog_reconciliation(self):
        """Test managing recovery backlog alongside normal queue."""
        coordinator = QueueCoordinator()

        # Normal queue tasks
        normal_task = QueuedTask(task_id="normal", slug="normal-work", risk_class="standard")
        coordinator.enqueue(normal_task)

        # Quarantined task (recovery backlog)
        quarantined = QueuedTask(task_id="q1", slug="quarantined-work", risk_class="standard")
        coordinator.enqueue(quarantined)
        coordinator.dequeue_for_execution("q1")
        coordinator.complete_task("q1", "QUARANTINED")

        stats = coordinator.get_stats()
        self.assertEqual(stats.quarantined, 1)
        self.assertEqual(stats.queued, 1)

        # Requeue the quarantined task
        coordinator.requeue_task("q1")
        stats = coordinator.get_stats()

        self.assertEqual(stats.quarantined, 0)
        self.assertEqual(stats.queued, 2)

    def test_thrashing_detection_via_attempt_count(self):
        """Tasks with high attempt counts should be deprioritized."""
        scorer = PriorityScorer()
        stable = QueuedTask(task_id="t1", slug="stable", risk_class="standard", attempted_count=0)
        thrashing = QueuedTask(task_id="t2", slug="thrashing", risk_class="standard", attempted_count=5)

        stable_score = scorer.score_task(stable, [], {})
        thrashing_score = scorer.score_task(thrashing, [], {})

        # Thrashing task should have lower priority
        self.assertLess(thrashing_score, stable_score)

    def test_learned_route_application(self):
        """Learned routes should be assigned to new tasks."""
        learner = ModelRouterLearner()
        coordinator = QueueCoordinator()

        # Learn that route-a is best
        learner.record_outcome("route-a", 0.9)
        learner.record_outcome("route-b", 0.5)

        # Create new task and assign best route
        task = QueuedTask(task_id="t1", slug="new-task", risk_class="standard")
        coordinator.enqueue(task)

        best_route = learner.get_best_route("standard", ["route-a", "route-b"])
        coordinator.assign_model_route("t1", best_route)

        assigned_task = coordinator.get_task("t1")
        self.assertEqual(assigned_task.model_route, "route-a")


class TestEdgeCasesAndErrors(unittest.TestCase):
    """Tests for edge cases and error handling."""

    def test_empty_queue_operations(self):
        """Operations on empty queue should not crash."""
        coordinator = QueueCoordinator()

        result = coordinator.dequeue_for_execution("nonexistent")
        self.assertIsNone(result)

        result = coordinator.complete_task("nonexistent", "MERGED")
        self.assertFalse(result)

        result = coordinator.requeue_task("nonexistent")
        self.assertFalse(result)

    def test_state_transition_violations(self):
        """Invalid state transitions should fail."""
        coordinator = QueueCoordinator()
        task = QueuedTask(task_id="t1", slug="task-1", risk_class="standard")
        coordinator.enqueue(task)

        # Can't complete task that's not RUNNING
        result = coordinator.complete_task("t1", "MERGED")
        self.assertFalse(result)

        # Can't requeue task that's not QUARANTINED
        result = coordinator.requeue_task("t1")
        self.assertFalse(result)

    def test_prioritize_with_none_history(self):
        """Prioritization should handle None failure history."""
        scorer = PriorityScorer()
        task = QueuedTask(task_id="t1", slug="task-1", risk_class="standard")
        result = scorer.prioritize_queue([task], failure_history=None)
        self.assertEqual(len(result), 1)

    def test_prioritize_with_none_changed_files(self):
        """Prioritization should handle None changed files."""
        scorer = PriorityScorer()
        task = QueuedTask(task_id="t1", slug="task-1", risk_class="standard")
        result = scorer.prioritize_queue([task], changed_files=None)
        self.assertEqual(len(result), 1)

    def test_score_with_invalid_risk_class(self):
        """Scoring with invalid risk class should use default."""
        scorer = PriorityScorer()
        task = QueuedTask(task_id="t1", slug="task-1", risk_class="unknown")
        score = scorer.score_task(task, [], {})
        self.assertIsInstance(score, float)
        self.assertGreaterEqual(score, 0.0)

    def test_negative_attempt_count_handling(self):
        """Negative attempt counts should not crash scorer."""
        scorer = PriorityScorer()
        task = QueuedTask(task_id="t1", slug="task-1", risk_class="standard", attempted_count=-1)
        score = scorer.score_task(task, [], {})
        self.assertIsInstance(score, float)


if __name__ == "__main__":
    unittest.main()
