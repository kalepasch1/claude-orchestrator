"""Tests for runner/events.py structured event stream."""
import datetime
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import events


class TestEmitAndReadBack(unittest.TestCase):
    """Core emit/read-back functionality."""

    def setUp(self):
        """Use a temporary directory for all event tests."""
        self.tmpdir = tempfile.mkdtemp()
        self.old_runtime = events.RUNTIME
        self.old_events_dir = events.EVENTS_DIR
        events.RUNTIME = self.tmpdir
        events.EVENTS_DIR = os.path.join(self.tmpdir, "events")

    def tearDown(self):
        """Restore original paths and clean up."""
        events.RUNTIME = self.old_runtime
        events.EVENTS_DIR = self.old_events_dir
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_emit_creates_jsonl_file(self):
        """Emitting an event should create a JSONL file."""
        result = events.emit("test:event", value=42)
        self.assertTrue(result)
        today = datetime.date.today().isoformat()
        path = os.path.join(events.EVENTS_DIR, f"{today}.jsonl")
        self.assertTrue(os.path.exists(path))

    def test_emit_appends_valid_json(self):
        """Emitted events should be valid JSONL lines."""
        events.emit("sentinel:db-down", reason="timeout")
        events.emit("train:merged", pr=42, commit="abc123")
        today = datetime.date.today().isoformat()
        path = os.path.join(events.EVENTS_DIR, f"{today}.jsonl")
        with open(path, "r") as f:
            lines = f.readlines()
        self.assertEqual(len(lines), 2)
        for line in lines:
            obj = json.loads(line.strip())
            self.assertIn("timestamp", obj)
            self.assertIn("kind", obj)

    def test_emit_includes_custom_fields(self):
        """Emitted events should include all custom fields."""
        events.emit("test:fields", a=1, b="hello", c={"nested": True})
        path = os.path.join(events.EVENTS_DIR, f"{datetime.date.today().isoformat()}.jsonl")
        with open(path, "r") as f:
            obj = json.loads(f.read().strip())
        self.assertEqual(obj["a"], 1)
        self.assertEqual(obj["b"], "hello")
        self.assertEqual(obj["c"]["nested"], True)

    def test_read_events_returns_list(self):
        """read_events should return a list of dicts."""
        events.emit("test:one", x=1)
        events.emit("test:two", x=2)
        result = events.read_events()
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["kind"], "test:one")
        self.assertEqual(result[1]["kind"], "test:two")

    def test_read_events_specific_date(self):
        """read_events should handle date parameter."""
        today = datetime.date.today()
        yesterday = today - datetime.timedelta(days=1)
        events.emit("today:event", value=1)
        result_today = events.read_events(today)
        result_yesterday = events.read_events(yesterday)
        self.assertEqual(len(result_today), 1)
        self.assertEqual(len(result_yesterday), 0)

    def test_read_events_empty_on_missing_file(self):
        """read_events should return empty list if file doesn't exist."""
        tomorrow = datetime.date.today() + datetime.timedelta(days=1)
        result = events.read_events(tomorrow)
        self.assertEqual(result, [])

    def test_read_events_handles_corrupted_lines(self):
        """read_events should skip corrupt JSON lines."""
        today = datetime.date.today().isoformat()
        path = os.path.join(events.EVENTS_DIR, f"{today}.jsonl")
        os.makedirs(events.EVENTS_DIR, exist_ok=True)
        with open(path, "w") as f:
            f.write('{"kind": "good", "x": 1}\n')
            f.write('not valid json\n')
            f.write('{"kind": "also-good", "x": 2}\n')
        result = events.read_events()
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["kind"], "good")
        self.assertEqual(result[1]["kind"], "also-good")


class TestReadRecent(unittest.TestCase):
    """read_recent functionality."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.old_events_dir = events.EVENTS_DIR
        events.EVENTS_DIR = os.path.join(self.tmpdir, "events")

    def tearDown(self):
        events.EVENTS_DIR = self.old_events_dir
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_read_recent_across_dates(self):
        """read_recent should return events from multiple dates."""
        today = datetime.date.today()
        yesterday = today - datetime.timedelta(days=1)
        os.makedirs(events.EVENTS_DIR, exist_ok=True)
        for date in [yesterday, today]:
            path = os.path.join(events.EVENTS_DIR, f"{date.isoformat()}.jsonl")
            with open(path, "w") as f:
                f.write(json.dumps({"kind": f"event:{date}", "value": 1}) + "\n")
        result = events.read_recent(limit=10)
        self.assertGreaterEqual(len(result), 2)

    def test_read_recent_respects_limit(self):
        """read_recent should cap at limit."""
        os.makedirs(events.EVENTS_DIR, exist_ok=True)
        for i in range(50):
            events.emit(f"test:event-{i}", index=i)
        result = events.read_recent(limit=20)
        self.assertEqual(len(result), 20)

    def test_read_recent_empty_directory(self):
        """read_recent should return empty list if no events."""
        os.makedirs(events.EVENTS_DIR, exist_ok=True)
        result = events.read_recent(limit=10)
        self.assertEqual(result, [])


class TestRotation(unittest.TestCase):
    """File rotation and size-capping."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.old_events_dir = events.EVENTS_DIR
        self.old_max_size = events.MAX_FILE_SIZE
        events.EVENTS_DIR = os.path.join(self.tmpdir, "events")
        events.MAX_FILE_SIZE = 1024  # 1KB for testing

    def tearDown(self):
        events.EVENTS_DIR = self.old_events_dir
        events.MAX_FILE_SIZE = self.old_max_size
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_rotation_creates_backup(self):
        """When file exceeds MAX_FILE_SIZE, rotation should create .jsonl.0."""
        os.makedirs(events.EVENTS_DIR, exist_ok=True)
        today = datetime.date.today().isoformat()
        path = os.path.join(events.EVENTS_DIR, f"{today}.jsonl")
        with open(path, "w") as f:
            f.write("x" * 2000)
        events._rotate_if_needed(path)
        self.assertTrue(os.path.exists(f"{path}.0"))

    def test_rotation_truncates_current_file(self):
        """After rotation, current file should be empty."""
        os.makedirs(events.EVENTS_DIR, exist_ok=True)
        today = datetime.date.today().isoformat()
        path = os.path.join(events.EVENTS_DIR, f"{today}.jsonl")
        with open(path, "w") as f:
            f.write("x" * 2000)
        events._rotate_if_needed(path)
        self.assertEqual(os.path.getsize(path), 0)

    def test_emit_triggers_rotation(self):
        """Emitting a large event should trigger rotation if file is at limit."""
        os.makedirs(events.EVENTS_DIR, exist_ok=True)
        today = datetime.date.today().isoformat()
        path = os.path.join(events.EVENTS_DIR, f"{today}.jsonl")
        with open(path, "w") as f:
            f.write("x" * 2000)
        events.emit("test:after-rotation", x=1)
        self.assertTrue(os.path.exists(f"{path}.0"))


class TestStats(unittest.TestCase):
    """stats() and invalidate() functionality."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.old_events_dir = events.EVENTS_DIR
        events.EVENTS_DIR = os.path.join(self.tmpdir, "events")

    def tearDown(self):
        events.EVENTS_DIR = self.old_events_dir
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_stats_empty_directory(self):
        """stats should return (0, 0, 0) for empty directory."""
        os.makedirs(events.EVENTS_DIR, exist_ok=True)
        total, size, count = events.stats()
        self.assertEqual(total, 0)
        self.assertEqual(size, 0)
        self.assertEqual(count, 0)

    def test_stats_counts_events(self):
        """stats should count events correctly."""
        events.emit("test:one", x=1)
        events.emit("test:two", x=2)
        events.emit("test:three", x=3)
        total, size, count = events.stats()
        self.assertGreaterEqual(total, 3)
        self.assertGreater(size, 0)
        self.assertGreater(count, 0)

    def test_invalidate_clears_all(self):
        """invalidate should remove all event files."""
        events.emit("test:event", x=1)
        result = events.invalidate()
        self.assertTrue(result)
        total, size, count = events.stats()
        self.assertEqual(total, 0)
        self.assertEqual(count, 0)

    def test_invalidate_allows_new_events(self):
        """After invalidate, new events should work."""
        events.emit("test:before", x=1)
        events.invalidate()
        events.emit("test:after", x=2)
        result = events.read_events()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["kind"], "test:after")


class TestMigratedEmitters(unittest.TestCase):
    """Test that key emitters have been wired to emit events."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.old_events_dir = events.EVENTS_DIR
        events.EVENTS_DIR = os.path.join(self.tmpdir, "events")

    def tearDown(self):
        events.EVENTS_DIR = self.old_events_dir
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_sentinel_can_emit(self):
        """sentinel module should be able to emit events."""
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
            import sentinel
            result = sentinel.emit("test:sentinel", action="probe_db")
            self.assertIsNotNone(result)
        except ImportError:
            self.skipTest("sentinel module not importable")

    def test_merge_train_can_emit(self):
        """merge_train module should be able to emit events."""
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
            import merge_train
            result = merge_train.emit("test:merge_train", pr=1, status="merged")
            self.assertIsNotNone(result)
        except ImportError:
            self.skipTest("merge_train module not importable")

    def test_resource_governor_can_emit(self):
        """resource_governor module should be able to emit events."""
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
            import resource_governor
            result = resource_governor.emit("test:governor", disk_pct=75)
            self.assertIsNotNone(result)
        except ImportError:
            self.skipTest("resource_governor module not importable")


class TestThreadSafety(unittest.TestCase):
    """Concurrent emit calls should not corrupt the file."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.old_events_dir = events.EVENTS_DIR
        events.EVENTS_DIR = os.path.join(self.tmpdir, "events")

    def tearDown(self):
        events.EVENTS_DIR = self.old_events_dir
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_concurrent_emits(self):
        """Multiple threads emitting concurrently should not corrupt events."""
        import threading
        errors = []

        def emit_bunch(thread_id):
            try:
                for i in range(10):
                    events.emit(f"thread:{thread_id}", event=i)
            except Exception as e:
                errors.append((thread_id, e))

        threads = [threading.Thread(target=emit_bunch, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        result = events.read_events()
        self.assertEqual(len(result), 50)


if __name__ == "__main__":
    unittest.main()
