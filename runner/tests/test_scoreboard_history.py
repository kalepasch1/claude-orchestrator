#!/usr/bin/env python3
"""Tests for scoreboard.py history persistence and lead time metrics."""
import sys, os, types, unittest, tempfile, json, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Stub db
_db_data = {}
_db_mod = types.ModuleType("db")
def _fake_select(table, params=None):
    return list(_db_data.get(table, []))
def _fake_insert(table, row, **kw):
    _db_data.setdefault(table, []).append(row)
_db_mod.select = _fake_select
_db_mod.insert = _fake_insert
_db_mod.update = lambda *a, **k: None
sys.modules["db"] = _db_mod

# Stub queue_counters
_qc = types.ModuleType("queue_counters")
_qc.exact_counts = lambda **kw: {"queued": 5, "running": 2}
sys.modules["queue_counters"] = _qc

# Stub prompt_assembler
_pa = types.ModuleType("prompt_assembler")
_pa.stats = lambda **kw: {"count": 10, "avg_tokens": 1500}
sys.modules["prompt_assembler"] = _pa

import scoreboard


class TestHistoryPersistence(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.history_file = os.path.join(self.tmpdir, "scoreboard_history.jsonl")
        scoreboard.HISTORY_FILE = self.history_file
        scoreboard.HISTORY_DIR = self.tmpdir

    def tearDown(self):
        if os.path.exists(self.history_file):
            os.unlink(self.history_file)
        os.rmdir(self.tmpdir)

    def test_append_creates_file(self):
        scoreboard._append_history({"generated_at": "2026-07-12T00:00:00", "val": 1})
        self.assertTrue(os.path.isfile(self.history_file))

    def test_append_multiple(self):
        scoreboard._append_history({"generated_at": "2026-07-12T00:00:00", "val": 1})
        scoreboard._append_history({"generated_at": "2026-07-12T01:00:00", "val": 2})
        with open(self.history_file) as f:
            lines = [l for l in f if l.strip()]
        self.assertEqual(len(lines), 2)

    def test_history_read(self):
        scoreboard._append_history({"generated_at": datetime.datetime.utcnow().isoformat(), "val": 1})
        h = scoreboard.history(days=1)
        self.assertEqual(len(h), 1)
        self.assertEqual(h[0]["val"], 1)

    def test_history_filters_old(self):
        old = (datetime.datetime.utcnow() - datetime.timedelta(days=60)).isoformat()
        recent = datetime.datetime.utcnow().isoformat()
        scoreboard._append_history({"generated_at": old, "val": "old"})
        scoreboard._append_history({"generated_at": recent, "val": "new"})
        h = scoreboard.history(days=30)
        self.assertEqual(len(h), 1)
        self.assertEqual(h[0]["val"], "new")

    def test_prune_removes_old(self):
        old = (datetime.datetime.utcnow() - datetime.timedelta(days=200)).isoformat()
        recent = datetime.datetime.utcnow().isoformat()
        scoreboard._append_history({"generated_at": old, "val": "old"})
        scoreboard._append_history({"generated_at": recent, "val": "new"})
        scoreboard._prune_history()
        with open(self.history_file) as f:
            lines = [l for l in f if l.strip()]
        self.assertEqual(len(lines), 1)
        self.assertIn("new", lines[0])

    def test_prune_no_file(self):
        """Prune with no file doesn't crash."""
        scoreboard.HISTORY_FILE = "/nonexistent/path.jsonl"
        scoreboard._prune_history()  # should not raise

    def test_history_empty_file(self):
        with open(self.history_file, "w") as f:
            f.write("")
        h = scoreboard.history(days=30)
        self.assertEqual(h, [])

    def test_history_corrupt_lines(self):
        with open(self.history_file, "w") as f:
            f.write("not json\n")
            f.write(json.dumps({"generated_at": datetime.datetime.utcnow().isoformat(), "v": 1}) + "\n")
        h = scoreboard.history(days=30)
        self.assertEqual(len(h), 1)

    def test_30_day_retention(self):
        """Verify >= 30 days of history is kept."""
        for i in range(35):
            ts = (datetime.datetime.utcnow() - datetime.timedelta(days=i)).isoformat()
            scoreboard._append_history({"generated_at": ts, "day": i})
        h = scoreboard.history(days=30)
        self.assertGreaterEqual(len(h), 30)

    def test_append_failsoft(self):
        """Bad directory doesn't crash."""
        scoreboard.HISTORY_DIR = "/nonexistent/dir"
        scoreboard.HISTORY_FILE = "/nonexistent/dir/file.jsonl"
        scoreboard._append_history({"test": 1})  # should not raise


class TestLeadTimeMetrics(unittest.TestCase):
    def setUp(self):
        global _db_data
        _db_data = {}

    def test_no_data_returns_none(self):
        r = scoreboard._lead_time_metrics()
        self.assertIsNone(r["prompt_to_merged_h"])
        self.assertIsNone(r["objective_to_prompt_h"])

    def test_tokens_per_task_from_assembler(self):
        r = scoreboard._lead_time_metrics()
        self.assertEqual(r["tokens_per_task"], 1500)

    def test_result_structure(self):
        r = scoreboard._lead_time_metrics()
        self.assertIn("objective_to_prompt_h", r)
        self.assertIn("prompt_to_merged_h", r)
        self.assertIn("tokens_per_task", r)

    def test_prompt_to_merged_with_data(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        task_ts = (now - datetime.timedelta(hours=5)).isoformat()
        outcome_ts = now.isoformat()
        _db_data["outcomes"] = [{"slug": "test-task", "project": "beethoven",
                                  "created_at": outcome_ts, "integrated": True}]
        _db_data["tasks"] = [{"slug": "test-task", "created_at": task_ts}]
        r = scoreboard._lead_time_metrics()
        self.assertIsNotNone(r["prompt_to_merged_h"])
        self.assertAlmostEqual(r["prompt_to_merged_h"], 5.0, delta=0.1)

    def test_lead_time_failsoft(self):
        """DB errors don't crash lead time computation."""
        old = _db_mod.select
        _db_mod.select = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("fail"))
        r = scoreboard._lead_time_metrics()
        self.assertIsNone(r["prompt_to_merged_h"])
        _db_mod.select = old


class TestComputeIntegration(unittest.TestCase):
    def setUp(self):
        global _db_data
        _db_data = {}

    def test_compute_includes_lead_times(self):
        payload = scoreboard.compute()
        self.assertIn("lead_times", payload)
        self.assertIn("objective_to_prompt_h", payload["lead_times"])
        self.assertIn("prompt_to_merged_h", payload["lead_times"])
        self.assertIn("tokens_per_task", payload["lead_times"])

    def test_compute_has_generated_at(self):
        payload = scoreboard.compute()
        self.assertIn("generated_at", payload)

    def test_compute_has_overall(self):
        payload = scoreboard.compute()
        self.assertIn("overall", payload)
        self.assertIn("attempts", payload["overall"])


if __name__ == "__main__":
    unittest.main()
