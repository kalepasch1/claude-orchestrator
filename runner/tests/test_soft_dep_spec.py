#!/usr/bin/env python3
"""
Test suite for soft_dep_spec.py — soft-dependency speculation with rollback.

Covers:
- File scope extraction and disjointness checks
- Speculation eligibility logic
- Task registration and invalidation
- Registry state management under concurrent scenarios
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import soft_dep_spec


class TestFileScope(unittest.TestCase):
    """Tests for _file_scope extraction."""

    def test_file_scope_empty_string(self):
        task = {"file_scope": ""}
        self.assertEqual(soft_dep_spec._file_scope(task), set())

    def test_file_scope_none(self):
        task = {"file_scope": None}
        self.assertEqual(soft_dep_spec._file_scope(task), set())

    def test_file_scope_missing_key(self):
        task = {}
        self.assertEqual(soft_dep_spec._file_scope(task), set())

    def test_file_scope_single_file(self):
        task = {"file_scope": "src/main.py"}
        self.assertEqual(soft_dep_spec._file_scope(task), {"src/main.py"})

    def test_file_scope_multiple_files(self):
        task = {"file_scope": "src/main.py,src/util.py,tests/test_main.py"}
        self.assertEqual(
            soft_dep_spec._file_scope(task),
            {"src/main.py", "src/util.py", "tests/test_main.py"}
        )

    def test_file_scope_with_whitespace(self):
        task = {"file_scope": " src/main.py , src/util.py , tests/ "}
        self.assertEqual(
            soft_dep_spec._file_scope(task),
            {"src/main.py", "src/util.py", "tests/"}
        )

    def test_file_scope_trailing_comma(self):
        task = {"file_scope": "src/main.py,src/util.py,"}
        self.assertEqual(
            soft_dep_spec._file_scope(task),
            {"src/main.py", "src/util.py"}
        )


class TestIsSensitive(unittest.TestCase):
    """Tests for _is_sensitive task detection."""

    def test_sensitive_contracts(self):
        task = {"slug": "deploy-contracts-v1"}
        self.assertTrue(soft_dep_spec._is_sensitive(task))

    def test_sensitive_migrations(self):
        task = {"slug": "db-migrations-2026"}
        self.assertTrue(soft_dep_spec._is_sensitive(task))

    def test_sensitive_schema(self):
        task = {"slug": "schema-refactor"}
        self.assertTrue(soft_dep_spec._is_sensitive(task))

    def test_sensitive_deploy(self):
        task = {"slug": "canary-deploy"}
        self.assertTrue(soft_dep_spec._is_sensitive(task))

    def test_sensitive_release(self):
        task = {"slug": "release-v2"}
        self.assertTrue(soft_dep_spec._is_sensitive(task))

    def test_not_sensitive_feature(self):
        task = {"slug": "feature-new-api"}
        self.assertFalse(soft_dep_spec._is_sensitive(task))

    def test_not_sensitive_fix(self):
        task = {"slug": "fix-typo-readme"}
        self.assertFalse(soft_dep_spec._is_sensitive(task))

    def test_not_sensitive_missing_slug(self):
        task = {}
        self.assertFalse(soft_dep_spec._is_sensitive(task))

    def test_case_sensitive_check(self):
        task = {"slug": "CONTRACTS-DEPLOY"}
        self.assertTrue(soft_dep_spec._is_sensitive(task))


class TestCanSpeculate(unittest.TestCase):
    """Tests for can_speculate eligibility logic."""

    def setUp(self):
        soft_dep_spec._registry.clear()

    def test_disabled_returns_false(self):
        task = {"id": "t1", "slug": "test", "file_scope": "src/", "deps": ["other"]}
        with patch.object(soft_dep_spec, 'ENABLED', False):
            can, reason = soft_dep_spec.can_speculate(task, [])
        self.assertFalse(can)
        self.assertEqual(reason, "soft-dep-spec disabled")

    def test_sensitive_task_blocked(self):
        task = {
            "id": "t1",
            "slug": "deploy-v1",
            "file_scope": "src/",
            "deps": ["other"]
        }
        can, reason = soft_dep_spec.can_speculate(task, [])
        self.assertFalse(can)
        self.assertEqual(reason, "sensitive task")

    def test_all_deps_done_is_not_speculation(self):
        task = {
            "id": "t1",
            "slug": "feature",
            "file_scope": "src/",
            "deps": ["dep1", "dep2"]
        }
        done_slugs = ["dep1", "dep2"]
        can, reason = soft_dep_spec.can_speculate(task, done_slugs)
        self.assertTrue(can)
        self.assertEqual(reason, "all deps done")

    def test_no_deps_is_not_speculation(self):
        task = {
            "id": "t1",
            "slug": "feature",
            "file_scope": "src/",
            "deps": []
        }
        can, reason = soft_dep_spec.can_speculate(task, [])
        self.assertTrue(can)
        self.assertEqual(reason, "all deps done")

    def test_none_deps_is_safe(self):
        task = {
            "id": "t1",
            "slug": "feature",
            "file_scope": "src/",
            "deps": None
        }
        can, reason = soft_dep_spec.can_speculate(task, [])
        self.assertTrue(can)
        self.assertEqual(reason, "all deps done")

    def test_too_many_pending_deps(self):
        task = {
            "id": "t1",
            "slug": "feature",
            "file_scope": "src/",
            "deps": ["dep1", "dep2", "dep3"]
        }
        with patch.object(soft_dep_spec, 'MAX_PENDING', 2):
            can, reason = soft_dep_spec.can_speculate(task, [])
        self.assertFalse(can)
        self.assertIn("too many pending deps", reason)
        self.assertIn("3", reason)
        self.assertIn("2", reason)

    def test_no_file_scope_declared(self):
        task = {
            "id": "t1",
            "slug": "feature",
            "file_scope": "",
            "deps": ["dep1"]
        }
        can, reason = soft_dep_spec.can_speculate(task, [])
        self.assertFalse(can)
        self.assertIn("no file_scope declared", reason)

    def test_disjoint_scopes_success(self):
        task = {
            "id": "t1",
            "slug": "feature",
            "file_scope": "src/main.py,src/util.py",
            "deps": ["dep1"]
        }
        # Mock db to return non-overlapping scope for dep1
        dep_task = {"slug": "dep1", "file_scope": "tests/test_main.py"}
        with patch("soft_dep_spec._db") as mock_db:
            mock_db.select.return_value = [dep_task]
            can, reason = soft_dep_spec.can_speculate(task, [])
        self.assertTrue(can)
        self.assertIn("disjoint scopes", reason)

    def test_file_overlap_blocks_speculation(self):
        task = {
            "id": "t1",
            "slug": "feature",
            "file_scope": "src/main.py,src/util.py",
            "deps": ["dep1"]
        }
        # Mock db to return overlapping scope for dep1
        dep_task = {"slug": "dep1", "file_scope": "src/main.py,tests/"}
        with patch("soft_dep_spec._db") as mock_db:
            mock_db.select.return_value = [dep_task]
            can, reason = soft_dep_spec.can_speculate(task, [])
        self.assertFalse(can)
        self.assertIn("file overlap", reason)
        self.assertIn("dep1", reason)

    def test_overlap_with_registered_speculating_task(self):
        # Register a task already speculatively running
        soft_dep_spec._registry["existing"] = {
            "slug": "existing",
            "file_scope": {"src/main.py"},
            "pending_deps": ["dep1"]
        }

        task = {
            "id": "t2",
            "slug": "feature",
            "file_scope": "src/main.py,src/util.py",
            "deps": ["dep2"]
        }

        with patch("soft_dep_spec._db") as mock_db:
            mock_db.select.return_value = [{"slug": "dep2", "file_scope": "tests/"}]
            can, reason = soft_dep_spec.can_speculate(task, [])

        self.assertFalse(can)
        self.assertIn("file overlap", reason)
        self.assertIn("speculating task existing", reason)

    def test_done_slugs_as_list_or_set(self):
        task = {
            "id": "t1",
            "slug": "feature",
            "file_scope": "src/",
            "deps": ["dep1"]
        }

        # Test with list
        with patch("soft_dep_spec._db") as mock_db:
            mock_db.select.return_value = [{"slug": "dep1", "file_scope": "tests/"}]
            can1, _ = soft_dep_spec.can_speculate(task, ["dep1"])
        self.assertTrue(can1)

        # Test with set
        with patch("soft_dep_spec._db") as mock_db:
            mock_db.select.return_value = [{"slug": "dep1", "file_scope": "tests/"}]
            can2, _ = soft_dep_spec.can_speculate(task, {"dep1"})
        self.assertTrue(can2)


class TestRegister(unittest.TestCase):
    """Tests for task registration."""

    def setUp(self):
        soft_dep_spec._registry.clear()

    def test_disabled_register_noops(self):
        task = {"id": "t1", "slug": "feature", "file_scope": "src/"}
        with patch.object(soft_dep_spec, 'ENABLED', False):
            soft_dep_spec.register(task, ["dep1"])
        self.assertEqual(len(soft_dep_spec._registry), 0)

    def test_register_task(self):
        task = {"id": "t1", "slug": "feature", "file_scope": "src/main.py"}
        soft_dep_spec.register(task, ["dep1", "dep2"])

        self.assertIn("t1", soft_dep_spec._registry)
        reg = soft_dep_spec._registry["t1"]
        self.assertEqual(reg["slug"], "feature")
        self.assertEqual(reg["pending_deps"], ["dep1", "dep2"])
        self.assertEqual(reg["file_scope"], {"src/main.py"})

    def test_register_task_without_id_ignored(self):
        task = {"slug": "feature", "file_scope": "src/"}
        soft_dep_spec.register(task, ["dep1"])
        self.assertEqual(len(soft_dep_spec._registry), 0)

    def test_register_task_with_empty_id_ignored(self):
        task = {"id": "", "slug": "feature", "file_scope": "src/"}
        soft_dep_spec.register(task, ["dep1"])
        self.assertEqual(len(soft_dep_spec._registry), 0)

    def test_register_multiple_tasks(self):
        task1 = {"id": "t1", "slug": "feature1", "file_scope": "src/main.py"}
        task2 = {"id": "t2", "slug": "feature2", "file_scope": "src/util.py"}

        soft_dep_spec.register(task1, ["dep1"])
        soft_dep_spec.register(task2, ["dep2"])

        self.assertEqual(len(soft_dep_spec._registry), 2)
        self.assertIn("t1", soft_dep_spec._registry)
        self.assertIn("t2", soft_dep_spec._registry)

    def test_register_copies_pending_deps_list(self):
        task = {"id": "t1", "slug": "feature", "file_scope": "src/"}
        deps = ["dep1", "dep2"]
        soft_dep_spec.register(task, deps)

        # Mutate original list
        deps.append("dep3")

        # Registry should have the original list
        self.assertEqual(soft_dep_spec._registry["t1"]["pending_deps"], ["dep1", "dep2"])


class TestOnDepDone(unittest.TestCase):
    """Tests for handling dependency completion and invalidation."""

    def setUp(self):
        soft_dep_spec._registry.clear()

    def test_disabled_returns_empty(self):
        task = {"slug": "dep1", "file_scope": "src/"}
        with patch.object(soft_dep_spec, 'ENABLED', False):
            invalidated = soft_dep_spec.on_dep_done(task)
        self.assertEqual(invalidated, [])

    def test_dep_not_in_pending_ignored(self):
        # Register a task with different pending dep
        task1 = {"id": "t1", "slug": "feature", "file_scope": "src/"}
        soft_dep_spec.register(task1, ["dep1"])

        # Complete a different dep
        completed = {"slug": "dep2", "file_scope": "tests/"}
        invalidated = soft_dep_spec.on_dep_done(completed)

        self.assertEqual(invalidated, [])
        # Task should still be in registry
        self.assertIn("t1", soft_dep_spec._registry)

    def test_no_overlap_removes_from_pending(self):
        # Register with two deps
        task1 = {"id": "t1", "slug": "feature", "file_scope": "src/main.py"}
        soft_dep_spec.register(task1, ["dep1", "dep2"])

        # Complete dep1 with non-overlapping scope
        completed = {"slug": "dep1", "file_scope": "tests/"}
        invalidated = soft_dep_spec.on_dep_done(completed)

        # Should not be invalidated
        self.assertEqual(invalidated, [])
        # Pending deps should be updated
        self.assertEqual(soft_dep_spec._registry["t1"]["pending_deps"], ["dep2"])

    def test_overlap_invalidates_task(self):
        # Register task with file scope
        task1 = {"id": "t1", "slug": "feature", "file_scope": "src/main.py,src/util.py"}
        soft_dep_spec.register(task1, ["dep1"])

        # Complete dep with overlapping scope
        completed = {"slug": "dep1", "file_scope": "src/main.py,tests/"}
        invalidated = soft_dep_spec.on_dep_done(completed)

        # Should be invalidated
        self.assertIn("t1", invalidated)
        # Should be removed from registry
        self.assertNotIn("t1", soft_dep_spec._registry)

    def test_modified_files_trigger_invalidation(self):
        # Register task
        task1 = {"id": "t1", "slug": "feature", "file_scope": "src/main.py"}
        soft_dep_spec.register(task1, ["dep1"])

        # Complete dep with modified_files that overlap
        completed = {
            "slug": "dep1",
            "file_scope": "tests/",
            "modified_files": "src/main.py,src/new.py"
        }
        invalidated = soft_dep_spec.on_dep_done(completed)

        # Should be invalidated because modified_files overlap
        self.assertIn("t1", invalidated)

    def test_modified_files_as_list(self):
        task1 = {"id": "t1", "slug": "feature", "file_scope": "src/main.py"}
        soft_dep_spec.register(task1, ["dep1"])

        completed = {
            "slug": "dep1",
            "file_scope": "tests/",
            "modified_files": ["src/main.py", "src/new.py"]
        }
        invalidated = soft_dep_spec.on_dep_done(completed)

        self.assertIn("t1", invalidated)

    def test_no_more_pending_removes_from_registry(self):
        # Register with single pending dep
        task1 = {"id": "t1", "slug": "feature", "file_scope": "src/"}
        soft_dep_spec.register(task1, ["dep1"])

        # Complete the only dep with no overlap
        completed = {"slug": "dep1", "file_scope": "tests/"}
        invalidated = soft_dep_spec.on_dep_done(completed)

        # Not invalidated
        self.assertEqual(invalidated, [])
        # Should be removed from registry
        self.assertNotIn("t1", soft_dep_spec._registry)

    def test_multiple_tasks_selective_invalidation(self):
        # Register two tasks
        task1 = {"id": "t1", "slug": "feature1", "file_scope": "src/main.py"}
        task2 = {"id": "t2", "slug": "feature2", "file_scope": "tests/"}
        soft_dep_spec.register(task1, ["dep1"])
        soft_dep_spec.register(task2, ["dep1"])

        # Complete dep1 with overlap only for task1
        completed = {"slug": "dep1", "file_scope": "src/main.py"}
        invalidated = soft_dep_spec.on_dep_done(completed)

        # Only task1 invalidated
        self.assertEqual(set(invalidated), {"t1"})
        # task2 should still be in registry
        self.assertIn("t2", soft_dep_spec._registry)
        self.assertEqual(soft_dep_spec._registry["t2"]["pending_deps"], [])


class TestConfirm(unittest.TestCase):
    """Tests for confirming speculation success."""

    def setUp(self):
        soft_dep_spec._registry.clear()

    def test_confirm_removes_from_registry(self):
        task = {"id": "t1", "slug": "feature", "file_scope": "src/"}
        soft_dep_spec.register(task, ["dep1"])

        self.assertIn("t1", soft_dep_spec._registry)
        soft_dep_spec.confirm(task)
        self.assertNotIn("t1", soft_dep_spec._registry)

    def test_confirm_nonexistent_task_noops(self):
        task = {"id": "t1", "slug": "feature"}
        soft_dep_spec.confirm(task)
        # Should not raise
        self.assertEqual(len(soft_dep_spec._registry), 0)

    def test_confirm_without_id_noops(self):
        task = {"slug": "feature"}
        soft_dep_spec.confirm(task)
        self.assertEqual(len(soft_dep_spec._registry), 0)


class TestStats(unittest.TestCase):
    """Tests for statistics and state inspection."""

    def setUp(self):
        soft_dep_spec._registry.clear()

    def test_stats_reflects_enabled_status(self):
        with patch.object(soft_dep_spec, 'ENABLED', True):
            stats = soft_dep_spec.stats()
            self.assertTrue(stats["enabled"])

        with patch.object(soft_dep_spec, 'ENABLED', False):
            stats = soft_dep_spec.stats()
            self.assertFalse(stats["enabled"])

    def test_stats_reflects_max_pending(self):
        with patch.object(soft_dep_spec, 'MAX_PENDING', 5):
            stats = soft_dep_spec.stats()
            self.assertEqual(stats["max_pending"], 5)

    def test_stats_empty_registry(self):
        stats = soft_dep_spec.stats()
        self.assertEqual(stats["active_speculations"], 0)
        self.assertEqual(stats["tasks"], {})

    def test_stats_with_active_speculations(self):
        task1 = {"id": "t1", "slug": "feature1", "file_scope": "src/"}
        task2 = {"id": "t2", "slug": "feature2", "file_scope": "tests/"}
        soft_dep_spec.register(task1, ["dep1"])
        soft_dep_spec.register(task2, ["dep2"])

        stats = soft_dep_spec.stats()
        self.assertEqual(stats["active_speculations"], 2)
        self.assertEqual(stats["tasks"]["t1"], "feature1")
        self.assertEqual(stats["tasks"]["t2"], "feature2")

    def test_stats_thread_safe(self):
        import threading

        def register_task(tid, slug):
            task = {"id": tid, "slug": slug, "file_scope": "src/"}
            soft_dep_spec.register(task, ["dep1"])

        threads = []
        for i in range(10):
            t = threading.Thread(target=register_task, args=(f"t{i}", f"feature{i}"))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # All registrations should be visible
        stats = soft_dep_spec.stats()
        self.assertEqual(stats["active_speculations"], 10)


class TestConcurrency(unittest.TestCase):
    """Tests for thread-safety and concurrent scenarios."""

    def setUp(self):
        soft_dep_spec._registry.clear()

    def test_concurrent_register_and_on_dep_done(self):
        import threading
        import time

        results = {"registered": 0, "invalidated": 0}

        def register_tasks():
            for i in range(5):
                task = {"id": f"t{i}", "slug": f"feature{i}", "file_scope": f"src/file{i}.py"}
                soft_dep_spec.register(task, ["dep1"])
                results["registered"] += 1

        def complete_dep():
            time.sleep(0.01)  # Let some registrations happen first
            completed = {"slug": "dep1", "file_scope": "src/file0.py"}
            invalidated = soft_dep_spec.on_dep_done(completed)
            results["invalidated"] = len(invalidated)

        t1 = threading.Thread(target=register_tasks)
        t2 = threading.Thread(target=complete_dep)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Should have 5 registered
        self.assertEqual(results["registered"], 5)
        # Should have at least one invalidated (t0)
        self.assertGreaterEqual(results["invalidated"], 1)

    def test_registry_isolation_between_tests(self):
        # Each test should start with empty registry due to setUp
        self.assertEqual(len(soft_dep_spec._registry), 0)


class TestEdgeCases(unittest.TestCase):
    """Tests for edge cases and error handling."""

    def setUp(self):
        soft_dep_spec._registry.clear()

    def test_db_lookup_failure_doesnt_crash(self):
        task = {
            "id": "t1",
            "slug": "feature",
            "file_scope": "src/",
            "deps": ["dep1"]
        }

        # Mock db to raise exception
        with patch("soft_dep_spec._db") as mock_db:
            mock_db.select.side_effect = RuntimeError("DB down")
            # Should not crash, should check registry instead
            can, reason = soft_dep_spec.can_speculate(task, [])

        # Without registered overlaps, should allow
        self.assertTrue(can)

    def test_empty_file_scope_in_dep(self):
        task = {
            "id": "t1",
            "slug": "feature",
            "file_scope": "src/",
            "deps": ["dep1"]
        }

        # Mock db to return empty scope for dep
        with patch("soft_dep_spec._db") as mock_db:
            mock_db.select.return_value = [{"slug": "dep1", "file_scope": ""}]
            can, reason = soft_dep_spec.can_speculate(task, [])

        # Should allow since there's no overlap to detect
        self.assertTrue(can)

    def test_special_characters_in_file_scope(self):
        task = {
            "id": "t1",
            "slug": "feature",
            "file_scope": "src/[test]*.py,src/{a,b}.py"
        }
        scope = soft_dep_spec._file_scope(task)
        self.assertIn("src/[test]*.py", scope)
        self.assertIn("src/{a,b}.py", scope)


class TestIntegration(unittest.TestCase):
    """Integration tests for complete workflows."""

    def setUp(self):
        soft_dep_spec._registry.clear()

    def test_full_speculation_lifecycle(self):
        """Test: register -> check -> complete dep -> confirm."""
        # Check if task can speculate
        task = {
            "id": "t1",
            "slug": "feature",
            "file_scope": "src/feature.py",
            "deps": ["infra-dep"]
        }

        with patch("soft_dep_spec._db") as mock_db:
            mock_db.select.return_value = [{"slug": "infra-dep", "file_scope": "src/infra/"}]
            can, _ = soft_dep_spec.can_speculate(task, [])

        self.assertTrue(can)

        # Register for speculation
        soft_dep_spec.register(task, ["infra-dep"])
        self.assertIn("t1", soft_dep_spec._registry)

        # Dep completes without overlap
        completed = {"slug": "infra-dep", "file_scope": "src/infra/"}
        invalidated = soft_dep_spec.on_dep_done(completed)

        # Not invalidated
        self.assertEqual(invalidated, [])
        # Should be removed from registry
        self.assertNotIn("t1", soft_dep_spec._registry)

    def test_speculation_invalidation_on_overlap(self):
        """Test: register -> dep modifies overlapping files -> task invalidated."""
        task = {
            "id": "t1",
            "slug": "feature",
            "file_scope": "src/shared.py,src/feature.py",
            "deps": ["shared-dep"]
        }

        with patch("soft_dep_spec._db") as mock_db:
            mock_db.select.return_value = [{"slug": "shared-dep", "file_scope": "src/"}]
            can, _ = soft_dep_spec.can_speculate(task, [])

        self.assertFalse(can)  # File overlap detected upfront

    def test_multiple_tasks_partial_invalidation(self):
        """Test: multiple speculating tasks, only some invalidated on dep done."""
        task1 = {"id": "t1", "slug": "feature1", "file_scope": "src/feature1.py"}
        task2 = {"id": "t2", "slug": "feature2", "file_scope": "src/feature2.py"}
        task3 = {"id": "t3", "slug": "feature3", "file_scope": "src/util.py"}

        soft_dep_spec.register(task1, ["infra"])
        soft_dep_spec.register(task2, ["infra"])
        soft_dep_spec.register(task3, ["infra"])

        # Dep modifies only feature1 and util, not feature2
        completed = {
            "slug": "infra",
            "file_scope": "src/",
            "modified_files": "src/feature1.py,src/util.py"
        }
        invalidated = soft_dep_spec.on_dep_done(completed)

        # t1 and t3 should be invalidated
        self.assertEqual(set(invalidated), {"t1", "t3"})
        # t2 should remain (pending_deps now empty, so removed too)
        self.assertNotIn("t1", soft_dep_spec._registry)
        self.assertNotIn("t3", soft_dep_spec._registry)


if __name__ == "__main__":
    unittest.main()
