"""Tests for queue_preopt — queue pre-optimization system."""
import unittest
from unittest.mock import patch, MagicMock
import time
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestCacheOperations(unittest.TestCase):
    def setUp(self):
        import queue_preopt
        queue_preopt.invalidate_all()

    def test_get_returns_none_when_empty(self):
        import queue_preopt
        self.assertIsNone(queue_preopt.get("nonexistent-id"))

    def test_store_and_get(self):
        import queue_preopt
        queue_preopt._store("task-1", {"context_pack": "test data"}, "abc123")
        result = queue_preopt.get("task-1")
        self.assertIsNotNone(result)
        self.assertEqual(result["context_pack"], "test data")

    def test_invalidate_removes_entry(self):
        import queue_preopt
        queue_preopt._store("task-2", {"foo": "bar"}, "def456")
        queue_preopt.invalidate("task-2")
        self.assertIsNone(queue_preopt.get("task-2"))

    def test_invalidate_all_clears_cache(self):
        import queue_preopt
        queue_preopt._store("task-a", {"a": 1}, "h1")
        queue_preopt._store("task-b", {"b": 2}, "h2")
        queue_preopt.invalidate_all()
        self.assertIsNone(queue_preopt.get("task-a"))
        self.assertIsNone(queue_preopt.get("task-b"))

    def test_ttl_expiration(self):
        import queue_preopt
        queue_preopt._store("task-ttl", {"data": "old"}, "h3")
        # Manually age the entry
        with queue_preopt._cache_lock:
            queue_preopt._cache["task-ttl"]["ts"] = time.time() - queue_preopt.CACHE_TTL - 1
        self.assertIsNone(queue_preopt.get("task-ttl"))

    def test_stats_reports_correctly(self):
        import queue_preopt
        queue_preopt._store("s1", {"x": 1}, "h1")
        queue_preopt._store("s2", {"x": 2}, "h2")
        # Age one entry
        with queue_preopt._cache_lock:
            queue_preopt._cache["s1"]["ts"] = time.time() - queue_preopt.CACHE_TTL - 1
        s = queue_preopt.stats()
        self.assertEqual(s["cached_tasks"], 2)
        self.assertEqual(s["fresh"], 1)
        self.assertEqual(s["stale"], 1)


class TestTaskHash(unittest.TestCase):
    def test_same_task_same_hash(self):
        import queue_preopt
        t = {"slug": "fix-bug", "prompt": "Fix the login bug", "note": None, "kind": "code"}
        h1 = queue_preopt._task_hash(t)
        h2 = queue_preopt._task_hash(t)
        self.assertEqual(h1, h2)

    def test_different_task_different_hash(self):
        import queue_preopt
        t1 = {"slug": "fix-bug", "prompt": "Fix the login bug", "note": None, "kind": "code"}
        t2 = {"slug": "fix-bug", "prompt": "Fix the signup bug", "note": None, "kind": "code"}
        self.assertNotEqual(queue_preopt._task_hash(t1), queue_preopt._task_hash(t2))


class TestSystemCapacity(unittest.TestCase):
    @patch("queue_preopt.os.environ", {"MAX_PARALLEL": "10"})
    @patch("db.select")
    def test_has_capacity_when_low_load(self, mock_select):
        import queue_preopt
        # 3 active tasks out of 10 max
        mock_select.return_value = [{"id": i} for i in range(3)]
        self.assertTrue(queue_preopt._system_has_capacity())

    @patch("queue_preopt.os.environ", {"MAX_PARALLEL": "10"})
    @patch("db.select")
    def test_no_capacity_when_high_load(self, mock_select):
        import queue_preopt
        # 9 active tasks out of 10 max (> 0.85 ceiling)
        mock_select.return_value = [{"id": i} for i in range(9)]
        self.assertFalse(queue_preopt._system_has_capacity())


class TestApplyCached(unittest.TestCase):
    def setUp(self):
        import queue_preopt
        queue_preopt.invalidate_all()

    def test_returns_unchanged_when_no_cache(self):
        import queue_preopt
        prompt, extras, notes = queue_preopt.apply_cached(
            "no-cache", "original prompt", {}, "/repo", "proj", 0)
        self.assertEqual(prompt, "original prompt")
        self.assertEqual(extras, "")
        self.assertEqual(notes, [])

    def test_applies_context_pack(self):
        import queue_preopt
        queue_preopt._store("t1", {"context_pack": "\n## Repo Map\nfile1.py\n"}, "h1")
        prompt, extras, notes = queue_preopt.apply_cached(
            "t1", "do the thing", {}, "/repo", "proj", 0)
        self.assertIn("Repo Map", extras)
        self.assertIn("preopt:context_pack", notes)

    def test_invalidates_after_apply(self):
        import queue_preopt
        queue_preopt._store("t2", {"context_pack": "data"}, "h2")
        queue_preopt.apply_cached("t2", "prompt", {}, "/repo", "proj", 0)
        # Cache should be consumed
        self.assertIsNone(queue_preopt.get("t2"))

    def test_ai_review_logged_in_notes(self):
        import queue_preopt
        queue_preopt._store("t3", {
            "ai_review": {
                "issues": ["missing test file"],
                "merge_risk": "medium",
            }
        }, "h3")
        prompt, extras, notes = queue_preopt.apply_cached(
            "t3", "prompt", {}, "/repo", "proj", 0)
        self.assertTrue(any("ai_review" in n for n in notes))


class TestDaemonStartStop(unittest.TestCase):
    def test_start_stop_lifecycle(self):
        import queue_preopt
        # Save original
        orig_enabled = queue_preopt.ENABLED
        queue_preopt.ENABLED = True
        try:
            queue_preopt.start()
            self.assertTrue(queue_preopt._daemon_thread.is_alive())
            queue_preopt.stop()
            # Thread should stop within timeout
            time.sleep(0.5)
            self.assertFalse(queue_preopt._daemon_thread.is_alive())
        finally:
            queue_preopt.ENABLED = orig_enabled
            queue_preopt._stop_event.set()  # ensure cleanup


if __name__ == "__main__":
    unittest.main()
