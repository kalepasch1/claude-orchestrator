#!/usr/bin/env python3
"""
test_fleet_express_lane.py - Comprehensive tests for express lane feature.

Tests cover:
  - Normal express routing
  - Express lane overflow and fallback
  - Configuration changes
  - Disabled state
  - Performance/capacity assertions
  - Chaos scenarios (lane failures, stale entries)
"""
import os
import sys
import time
import threading

RUNNER = os.path.dirname(os.path.dirname(__file__))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import express_lane


class TestExpressLaneConfiguration:
    """Test configuration loading and defaults."""

    def test_default_enabled(self, monkeypatch):
        """Express lane is enabled by default."""
        monkeypatch.delenv("ORCH_EXPRESS_LANE_ENABLED", raising=False)
        express_lane.invalidate()
        assert express_lane.is_enabled() is True

    def test_can_disable(self, monkeypatch):
        """Express lane can be disabled via config."""
        monkeypatch.setenv("ORCH_EXPRESS_LANE_ENABLED", "false")
        express_lane.invalidate()
        assert express_lane.is_enabled() is False

    def test_default_capacity_percentage(self, monkeypatch):
        """Default express lane capacity is 15%."""
        monkeypatch.delenv("ORCH_EXPRESS_LANE_CAPACITY_PCT", raising=False)
        express_lane.invalidate()
        assert express_lane.capacity_percentage() == 15

    def test_can_configure_capacity(self, monkeypatch):
        """Express lane capacity can be configured."""
        monkeypatch.setenv("ORCH_EXPRESS_LANE_CAPACITY_PCT", "25")
        express_lane.invalidate()
        assert express_lane.capacity_percentage() == 25

    def test_capacity_clamped_to_range(self, monkeypatch):
        """Capacity is clamped to [0, 100]."""
        monkeypatch.setenv("ORCH_EXPRESS_LANE_CAPACITY_PCT", "150")
        express_lane.invalidate()
        assert express_lane.capacity_percentage() == 100

        monkeypatch.setenv("ORCH_EXPRESS_LANE_CAPACITY_PCT", "-10")
        express_lane.invalidate()
        assert express_lane.capacity_percentage() == 0


class TestLaneCapacity:
    """Test lane capacity calculations."""

    def test_express_lane_capacity_calculation(self, monkeypatch):
        """Express lane capacity based on total lanes and percentage."""
        monkeypatch.setenv("ORCH_EXPRESS_LANE_ENABLED", "true")
        monkeypatch.setenv("ORCH_EXPRESS_LANE_CAPACITY_PCT", "15")
        express_lane.invalidate()
        express_lane.set_total_lanes(40)

        # 15% of 40 = 6
        assert express_lane.express_lane_capacity() == 6

    def test_standard_lane_capacity_calculation(self, monkeypatch):
        """Standard lane capacity is remainder after express."""
        monkeypatch.setenv("ORCH_EXPRESS_LANE_ENABLED", "true")
        monkeypatch.setenv("ORCH_EXPRESS_LANE_CAPACITY_PCT", "15")
        express_lane.invalidate()
        express_lane.set_total_lanes(40)

        # 40 - 6 = 34
        assert express_lane.standard_lane_capacity() == 34

    def test_disabled_express_lanes(self, monkeypatch):
        """When disabled, express capacity is 0."""
        monkeypatch.setenv("ORCH_EXPRESS_LANE_ENABLED", "false")
        express_lane.invalidate()
        express_lane.set_total_lanes(40)

        assert express_lane.express_lane_capacity() == 0
        assert express_lane.standard_lane_capacity() == 40


class TestExpressRouting:
    """Test routing decision logic."""

    # NOTE: these used task = {"priority": "express"} — a STRING — but tasks.priority is an
    # INTEGER column, so the old predicate answered "not_express_priority" for every possible
    # input and should_use_express_lane() could never return True. The tests passed anyway
    # because a MagicMock-free string compare is happy to be false. Urgency in this schema is
    # a low integer rank (db.claim_task defaults a missing priority to 1000) or an operator
    # pin, so that is what these now exercise.

    def test_route_express_priority_task(self, monkeypatch):
        """An urgent numeric priority routes to the express lane when space is available."""
        monkeypatch.setenv("ORCH_EXPRESS_LANE_ENABLED", "true")
        monkeypatch.setenv("ORCH_EXPRESS_LANE_CAPACITY_PCT", "25")
        express_lane.invalidate()
        express_lane.set_total_lanes(40)

        task = {"id": "task-1", "priority": 5}
        use_express, reason = express_lane.should_use_express_lane(task)

        assert use_express is True
        assert reason == "express_priority"

    def test_route_pinned_task_to_express(self, monkeypatch):
        """An operator pin is the other express signal the schema provides."""
        monkeypatch.setenv("ORCH_EXPRESS_LANE_ENABLED", "true")
        monkeypatch.setenv("ORCH_EXPRESS_LANE_CAPACITY_PCT", "25")
        express_lane.invalidate()
        express_lane.set_total_lanes(40)

        task = {"id": "task-1", "priority": 1000, "pinned": True, "pin_rank": 1}
        use_express, reason = express_lane.should_use_express_lane(task)

        assert use_express is True
        assert reason == "pinned"

    def test_route_non_express_task_to_standard(self, monkeypatch):
        """A default-priority task routes to the standard lane."""
        monkeypatch.setenv("ORCH_EXPRESS_LANE_ENABLED", "true")
        express_lane.invalidate()

        task = {"id": "task-1", "priority": 1000}
        use_express, reason = express_lane.should_use_express_lane(task)

        assert use_express is False
        assert reason == "not_express_priority"

    def test_disabled_express_lane_routes_to_standard(self, monkeypatch):
        """When disabled, even express-priority tasks route to standard."""
        monkeypatch.setenv("ORCH_EXPRESS_LANE_ENABLED", "false")
        express_lane.invalidate()

        task = {"id": "task-1", "priority": 5}
        use_express, reason = express_lane.should_use_express_lane(task)

        assert use_express is False
        assert reason == "express_lane_disabled"


class TestLaneUtilization:
    """Test express lane capacity tracking."""

    def test_express_lane_utilization_when_empty(self, monkeypatch):
        """Utilization is 0 when express lane is empty."""
        monkeypatch.setenv("ORCH_EXPRESS_LANE_ENABLED", "true")
        monkeypatch.setenv("ORCH_EXPRESS_LANE_CAPACITY_PCT", "25")
        express_lane.invalidate()
        express_lane.set_total_lanes(40)

        used, capacity, percent = express_lane.express_lane_utilization()

        assert used == 0
        assert capacity == 10  # 25% of 40
        assert percent == 0.0

    def test_express_lane_capacity_exceeded_routes_to_standard(self, monkeypatch):
        """When express lane is full, subsequent tasks route to standard."""
        monkeypatch.setenv("ORCH_EXPRESS_LANE_ENABLED", "true")
        monkeypatch.setenv("ORCH_EXPRESS_LANE_CAPACITY_PCT", "25")
        express_lane.invalidate()
        express_lane.set_total_lanes(40)

        # Fill express lane
        capacity = express_lane.express_lane_capacity()
        for i in range(capacity):
            express_lane.assign_task_lane(f"task-{i}", f"runner-{i}", use_express=True)

        # Next express task should go to standard (fallback)
        task = {"id": "task-overflow", "priority": 5}
        use_express, reason = express_lane.should_use_express_lane(task)

        assert use_express is False
        assert reason == "express_lane_full"


class TestTaskAssignment:
    """Test task lane assignment tracking."""

    def test_assign_task_to_express_lane(self, monkeypatch):
        """Task assignment records express lane placement."""
        monkeypatch.setenv("ORCH_EXPRESS_LANE_ENABLED", "true")
        express_lane.invalidate()

        assignment = express_lane.assign_task_lane("task-1", "runner-1", use_express=True)

        assert assignment["lane"] == "express"
        assert assignment["fallback"] is False
        assert "assigned_at" in assignment

    def test_assign_task_to_standard_as_fallback(self, monkeypatch):
        """Task assignment tracks fallback to standard lane."""
        monkeypatch.setenv("ORCH_EXPRESS_LANE_ENABLED", "true")
        express_lane.invalidate()

        assignment = express_lane.assign_task_lane("task-1", "runner-1", use_express=False)

        assert assignment["lane"] == "standard"
        assert assignment["fallback"] is True  # Explicit False passed, so fallback=True

    def test_get_task_lane_assignment(self, monkeypatch):
        """Can retrieve task assignment."""
        monkeypatch.setenv("ORCH_EXPRESS_LANE_ENABLED", "true")
        express_lane.invalidate()

        express_lane.assign_task_lane("task-1", "runner-1", use_express=True)
        assignment = express_lane.get_task_lane_assignment("task-1")

        assert assignment is not None
        assert assignment["lane"] == "express"

    def test_active_express_lanes_count(self, monkeypatch):
        """Track active express lanes."""
        monkeypatch.setenv("ORCH_EXPRESS_LANE_ENABLED", "true")
        express_lane.invalidate()

        express_lane.assign_task_lane("task-1", "runner-1", use_express=True)
        express_lane.assign_task_lane("task-2", "runner-2", use_express=True)

        assert express_lane.active_express_lanes() == 2

    def test_active_standard_lanes_count(self, monkeypatch):
        """Track active standard lanes."""
        monkeypatch.setenv("ORCH_EXPRESS_LANE_ENABLED", "true")
        express_lane.invalidate()

        express_lane.assign_task_lane("task-1", "runner-1", use_express=False)
        express_lane.assign_task_lane("task-2", "runner-2", use_express=False)

        assert express_lane.active_standard_lanes() == 2


class TestLaneRelease:
    """Test lane release and cleanup."""

    def test_release_express_lane(self, monkeypatch):
        """Releasing a lane removes it from active tracking."""
        monkeypatch.setenv("ORCH_EXPRESS_LANE_ENABLED", "true")
        express_lane.invalidate()

        express_lane.assign_task_lane("task-1", "runner-1", use_express=True)
        assert express_lane.active_express_lanes() == 1

        express_lane.release_lane("runner-1")
        assert express_lane.active_express_lanes() == 0

    def test_prune_stale_lanes(self, monkeypatch):
        """Stale lanes (>30min old) are pruned."""
        monkeypatch.setenv("ORCH_EXPRESS_LANE_ENABLED", "true")
        express_lane.invalidate()
        express_lane.set_total_lanes(40)

        # Manually create a stale entry
        with express_lane._lock:
            express_lane._active_lanes["express"]["stale-runner"] = {
                "task_id": "task-stale",
                "claimed_at": time.time() - 2000,  # >30 min old
            }

        # Prune happens automatically in utilization calculation
        used, _, _ = express_lane.express_lane_utilization()
        assert used == 0  # Stale entry pruned


class TestStats:
    """Test statistics reporting."""

    def test_stats_report(self, monkeypatch):
        """Statistics report includes comprehensive lane data."""
        monkeypatch.setenv("ORCH_EXPRESS_LANE_ENABLED", "true")
        monkeypatch.setenv("ORCH_EXPRESS_LANE_CAPACITY_PCT", "20")
        express_lane.invalidate()
        express_lane.set_total_lanes(50)

        express_lane.assign_task_lane("task-1", "runner-1", use_express=True)
        express_lane.assign_task_lane("task-2", "runner-2", use_express=False)

        stats = express_lane.stats()

        assert stats["enabled"] is True
        assert stats["capacity_percentage"] == 20
        assert stats["total_lanes"] == 50
        assert stats["express"]["capacity"] == 10  # 20% of 50
        assert stats["express"]["active"] == 1
        assert stats["standard"]["capacity"] == 40  # 80% of 50
        assert stats["standard"]["active"] == 1


class TestThreadSafety:
    """Test thread-safe operations."""

    def test_concurrent_lane_assignments(self, monkeypatch):
        """Multiple threads can safely assign lanes."""
        monkeypatch.setenv("ORCH_EXPRESS_LANE_ENABLED", "true")
        express_lane.invalidate()
        express_lane.set_total_lanes(100)

        # Uniqueness comes from the thread's INDEX, not threading.current_thread().ident.
        # CPython recycles idents once a thread exits, and this body is fast enough that an
        # early thread can finish before a later one starts — so the ids collided, lanes
        # overwrote each other, and the count came in under 50 non-deterministically (20 on
        # the first run that ever reached this test). This test had never executed before:
        # stats() deadlocked earlier in the file and stalled the suite here.
        def assign_lanes(thread_index):
            for i in range(10):
                express_lane.assign_task_lane(
                    f"task-{thread_index}-{i}",
                    f"runner-{thread_index}-{i}",
                    use_express=(i % 2 == 0)
                )

        threads = [threading.Thread(target=assign_lanes, args=(n,)) for n in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 5 threads x 10 distinct runner ids = 50 lanes
        total = express_lane.active_express_lanes() + express_lane.active_standard_lanes()
        assert total == 50

    def test_concurrent_lane_release(self, monkeypatch):
        """Multiple threads can safely release lanes."""
        monkeypatch.setenv("ORCH_EXPRESS_LANE_ENABLED", "true")
        express_lane.invalidate()

        # Pre-populate lanes
        for i in range(20):
            express_lane.assign_task_lane(f"task-{i}", f"runner-{i}", use_express=(i % 2 == 0))

        def release_lanes():
            for i in range(10, 15):
                express_lane.release_lane(f"runner-{i}")

        threads = [threading.Thread(target=release_lanes) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Both threads release the SAME five ids (runner-10..14), so five lanes go, not ten:
        # 20 - 5 = 15. The old `assert total == 10` double-counted the duplicate releases and
        # would only have held if release_lane were NOT idempotent. 15 is the property worth
        # pinning — two threads releasing the same lane must remove it exactly once. This
        # test had never executed before; the stats() deadlock stalled the suite ahead of it.
        total = express_lane.active_express_lanes() + express_lane.active_standard_lanes()
        assert total == 15


class TestCapacityOverflow:
    """Test behavior when capacity limits are exceeded."""

    def test_express_lane_overflow_scenario(self, monkeypatch):
        """Multiple express tasks after capacity fill are routed to standard."""
        monkeypatch.setenv("ORCH_EXPRESS_LANE_ENABLED", "true")
        monkeypatch.setenv("ORCH_EXPRESS_LANE_CAPACITY_PCT", "25")
        express_lane.invalidate()
        express_lane.set_total_lanes(40)

        # Fill express lane completely
        capacity = express_lane.express_lane_capacity()
        for i in range(capacity):
            express_lane.assign_task_lane(f"task-{i}", f"runner-{i}", use_express=True)

        # Attempt to route more express tasks
        fallback_count = 0
        for i in range(capacity, capacity + 5):
            task = {"id": f"task-{i}", "priority": 5}
            use_express, _ = express_lane.should_use_express_lane(task)
            if not use_express:
                fallback_count += 1

        # All overflow should fallback
        assert fallback_count == 5

    def test_mixed_express_and_standard_workload(self, monkeypatch):
        """Mixed express/standard workload distributes correctly."""
        monkeypatch.setenv("ORCH_EXPRESS_LANE_ENABLED", "true")
        monkeypatch.setenv("ORCH_EXPRESS_LANE_CAPACITY_PCT", "30")
        express_lane.invalidate()
        express_lane.set_total_lanes(100)

        express_capacity = express_lane.express_lane_capacity()

        # Simulate workload
        for i in range(50):
            task = {"id": f"task-{i}", "priority": 5 if i < 25 else 1000}
            use_express, _ = express_lane.should_use_express_lane(task)
            # Only up to express_capacity should use express lane
            assert i < express_capacity or not use_express


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_zero_capacity_when_disabled(self, monkeypatch):
        """Disabled express lane has 0 capacity."""
        monkeypatch.setenv("ORCH_EXPRESS_LANE_ENABLED", "false")
        monkeypatch.setenv("ORCH_EXPRESS_LANE_CAPACITY_PCT", "50")
        express_lane.invalidate()
        express_lane.set_total_lanes(100)

        assert express_lane.express_lane_capacity() == 0
        assert express_lane.standard_lane_capacity() == 100

    def test_capacity_percent_zero(self, monkeypatch):
        """0% capacity means no express lane."""
        monkeypatch.setenv("ORCH_EXPRESS_LANE_ENABLED", "true")
        monkeypatch.setenv("ORCH_EXPRESS_LANE_CAPACITY_PCT", "0")
        express_lane.invalidate()
        express_lane.set_total_lanes(100)

        assert express_lane.express_lane_capacity() == 0
        assert express_lane.standard_lane_capacity() == 100

    def test_single_lane_total(self, monkeypatch):
        """Single total lane edge case."""
        monkeypatch.setenv("ORCH_EXPRESS_LANE_ENABLED", "true")
        monkeypatch.setenv("ORCH_EXPRESS_LANE_CAPACITY_PCT", "50")
        express_lane.invalidate()
        express_lane.set_total_lanes(1)

        assert express_lane.express_lane_capacity() == 1
        assert express_lane.standard_lane_capacity() == 0

    def test_missing_priority_field(self, monkeypatch):
        """Tasks missing priority field default to standard."""
        monkeypatch.setenv("ORCH_EXPRESS_LANE_ENABLED", "true")
        express_lane.invalidate()

        task = {"id": "task-1"}  # No priority field
        use_express, reason = express_lane.should_use_express_lane(task)

        assert use_express is False
        # More specific than the old blanket "not_express_priority": the field is absent,
        # which is a different diagnosis from "present but not urgent enough".
        assert reason == "no_priority"

    def test_invalid_priority_value(self, monkeypatch):
        """Invalid priority values route to standard."""
        monkeypatch.setenv("ORCH_EXPRESS_LANE_ENABLED", "true")
        express_lane.invalidate()

        # tasks.priority is an INTEGER column, so any non-numeric value is malformed data
        # rather than a lower priority band — say which.
        task = {"id": "task-1", "priority": "urgent"}
        use_express, reason = express_lane.should_use_express_lane(task)

        assert use_express is False
        assert reason == "priority_not_numeric"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
