#!/usr/bin/env python3
"""Integration tests — verify multiple orchestrator components work together.

Tests cross-module interactions:
  - branch_materializer + speculative_parallel
  - value_router + speculative_exec
  - speculative_parallel group independence
"""
import os, sys, unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import branch_materializer
import speculative_parallel
import value_router
import speculative_exec


class TestBranchMaterializerSpeculativeIntegration(unittest.TestCase):
    """Verify branch materializer results feed into speculative parallel."""

    def test_materialized_tasks_can_be_grouped(self):
        """Tasks that pass materialization can be grouped for parallel execution."""
        tasks = [
            {"slug": "task-a", "prompt": "edit runner/foo.py", "deps": []},
            {"slug": "task-b", "prompt": "edit web/bar.ts", "deps": []},
            {"slug": "task-c", "prompt": "edit runner/baz.py", "deps": []},
        ]
        # Simulate materialization
        with patch("branch_materializer.materialize_branch") as mock_mat:
            mock_mat.return_value = {"ok": True, "branch": "agent/x", "action": "created", "error": None}
            results = branch_materializer.materialize_task_branches(tasks, "/tmp/repo")
            materialized = [r for r in results if r["ok"]]
            self.assertEqual(len(materialized), 3)

        # Materialized tasks should be groupable
        groups = speculative_parallel.find_independent_groups(tasks)
        self.assertGreaterEqual(len(groups), 1)
        total = sum(len(g) for g in groups)
        self.assertEqual(total, 3)

    def test_failed_materialization_excluded(self):
        """Failed branch materialization should tag tasks for quarantine."""
        tasks = [{"slug": "good"}, {"slug": "bad"}]
        with patch("branch_materializer.materialize_branch") as mock_mat:
            mock_mat.side_effect = [
                {"ok": True, "branch": "agent/good", "action": "created", "error": None},
                {"ok": False, "branch": "agent/bad", "action": "push-failed", "error": "err"},
            ]
            results = branch_materializer.materialize_task_branches(tasks, "/tmp/repo")
            failed = [r for r in results if not r["ok"]]
            self.assertEqual(len(failed), 1)
            self.assertEqual(failed[0]["tag"], "branch-init-failed")


class TestValueRouterSpeculativeIntegration(unittest.TestCase):
    """Verify value router decisions align with speculative exec eligibility."""

    def test_low_value_docs_eligible_for_speculation(self):
        """Low-value docs tasks should be eligible for speculative exec."""
        task = {"slug": "update-docs-readme", "kind": "docs", "prompt": "Update docs/README.md"}
        routing = value_router.route_task(task)
        self.assertEqual(routing["tier"], "LOW")
        self.assertTrue(routing["skip_integration_tests"])

        can_spec, reason = speculative_exec.should_speculate(task)
        self.assertTrue(can_spec, f"docs task should be speculative: {reason}")

    def test_high_value_payment_not_speculative(self):
        """High-value payment tasks should NOT be speculative."""
        task = {"slug": "fix-payment-flow", "kind": "bugfix",
                "prompt": "Fix payment checkout in web/checkout.tsx"}
        routing = value_router.route_task(task)
        self.assertEqual(routing["tier"], "HIGH")
        self.assertFalse(routing["skip_integration_tests"])

        can_spec, reason = speculative_exec.should_speculate(task)
        self.assertFalse(can_spec, f"payment task should not speculate: {reason}")

    def test_medium_value_standard_path(self):
        """Medium tasks get standard routing."""
        task = {"slug": "add-feature-x", "kind": "build",
                "prompt": "Implement feature X in runner/feature_x.py"}
        routing = value_router.route_task(task)
        self.assertEqual(routing["tier"], "MEDIUM")
        self.assertFalse(routing["auto_approve"])


class TestSpeculativeParallelGrouping(unittest.TestCase):
    """Verify parallel grouping preserves independence invariants."""

    def test_no_file_overlap_in_groups(self):
        tasks = [
            {"slug": "a", "prompt": "edit runner/foo.py", "deps": []},
            {"slug": "b", "prompt": "edit runner/foo.py", "deps": []},
            {"slug": "c", "prompt": "edit web/bar.ts", "deps": []},
        ]
        groups = speculative_parallel.find_independent_groups(tasks)
        # a and b share runner/foo.py, so they must be in different groups
        for group in groups:
            slugs = [t["slug"] for t in group]
            self.assertFalse("a" in slugs and "b" in slugs,
                             "Tasks sharing files must not be in same group")

    def test_dep_chain_respected(self):
        tasks = [
            {"slug": "base", "prompt": "create api", "deps": []},
            {"slug": "child", "prompt": "use api", "deps": ["base"]},
        ]
        groups = speculative_parallel.find_independent_groups(tasks)
        for group in groups:
            slugs = [t["slug"] for t in group]
            self.assertFalse("base" in slugs and "child" in slugs,
                             "Dependent tasks must not be in same group")

    def test_all_independent_single_group(self):
        tasks = [
            {"slug": "x", "prompt": "edit x.py", "deps": []},
            {"slug": "y", "prompt": "edit y.py", "deps": []},
            {"slug": "z", "prompt": "edit z.py", "deps": []},
        ]
        groups = speculative_parallel.find_independent_groups(tasks)
        # All independent, no file overlap → single group
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]), 3)


class TestValueRouterStats(unittest.TestCase):
    def test_routing_increments_stats(self):
        before = value_router.stats()
        value_router.route_task({"slug": "test", "kind": "build", "prompt": "test"})
        after = value_router.stats()
        self.assertGreater(after["tasks_routed"], before["tasks_routed"])


if __name__ == "__main__":
    unittest.main()
