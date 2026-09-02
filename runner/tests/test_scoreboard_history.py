#!/usr/bin/env python3
"""Tests for scoreboard.py snapshot persistence, history reads and derived views.

REWRITE NOTE (whole file)
-------------------------
The previous version of this file was written against a scoreboard API that does
not exist in this repo: `scoreboard.HISTORY_FILE`, `_append_history()`,
`history(days=...)`, `_prune_history()`, `_lead_time_metrics()` and `compute()`.
Every test in the file failed with AttributeError, so none of them asserted
anything about the module that actually ships.

The real module (runner/scoreboard.py) persists router_stats snapshots as JSONL
to `_SCOREBOARD_FILE` (`persist_snapshot()` / `run()`), reads the tail of that
file back (`read_history(max_entries=...)`), and derives two views from it
(`dashboard_summary()`, `trend(kind, coder)`). The tests below keep the original
intent — persistence, retention window, corrupt-line tolerance, fail-soft I/O,
derived metrics — but assert it against those real functions. Each substituted
test carries a comment naming what it used to assert.

Isolation follows the convention in runner/tests/test_scoreboard.py: rebind the
module-level `_SCOREBOARD_FILE` / `_SCOREBOARD_DIR` constants for the duration of
the test. The old file also installed permanent `sys.modules` stubs for `db`,
`queue_counters` and `prompt_assembler` at import time, which leaked into every
other test module in the session; router_stats is patched per-test instead.
"""
import sys, os, unittest, tempfile, shutil, json
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import scoreboard
import router_stats


def _table(score=9.5, n=20):
    """A router_stats._rebuild()-shaped table: {kind: [row, ...]} sorted by score."""
    return {
        "feature": [
            {"coder": "claude", "score": score, "rate": 0.9, "deployed_rate": 0.8,
             "n": n, "usd_per_merge": 0.42, "objective": "merge_rate"},
            {"coder": "codex", "score": 4.0, "rate": 0.5, "deployed_rate": 0.3,
             "n": 8, "usd_per_merge": 1.1, "objective": "merge_rate"},
        ],
        "bugfix": [
            {"coder": "codex", "score": 6.0, "rate": 0.7, "deployed_rate": 0.6,
             "n": 12, "usd_per_merge": 0.8, "objective": "merge_rate"},
        ],
    }


class _ScoreboardTempFile(unittest.TestCase):
    """Point scoreboard at a throwaway JSONL file for the duration of a test."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.history_file = os.path.join(self.tmpdir, "scoreboard.jsonl")
        self._orig_file = scoreboard._SCOREBOARD_FILE
        self._orig_dir = scoreboard._SCOREBOARD_DIR
        scoreboard._SCOREBOARD_FILE = self.history_file
        scoreboard._SCOREBOARD_DIR = self.tmpdir

    def tearDown(self):
        scoreboard._SCOREBOARD_FILE = self._orig_file
        scoreboard._SCOREBOARD_DIR = self._orig_dir
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _lines(self):
        with open(self.history_file) as f:
            return [l for l in f if l.strip()]


class TestHistoryPersistence(_ScoreboardTempFile):

    # was test_append_creates_file: called the non-existent _append_history().
    # persist_snapshot() is the real writer.
    def test_persist_snapshot_creates_file(self):
        with patch.object(router_stats, "_rebuild", lambda: _table()):
            snapshot = scoreboard.persist_snapshot()
        self.assertTrue(os.path.isfile(self.history_file))
        self.assertEqual(sorted(snapshot["routes"]), ["bugfix", "feature"])
        self.assertEqual(json.loads(self._lines()[0])["routes"]["feature"][0]["coder"],
                         "claude")

    # was test_append_multiple (_append_history x2): one JSONL line per snapshot.
    def test_persist_snapshot_appends_one_line_each(self):
        with patch.object(router_stats, "_rebuild", lambda: _table()):
            scoreboard.persist_snapshot()
            scoreboard.persist_snapshot()
        self.assertEqual(len(self._lines()), 2)

    # was test_history_read: history(days=1). read_history() is the real reader.
    def test_read_history_returns_persisted_snapshot(self):
        with patch.object(router_stats, "_rebuild", lambda: _table(score=7.25)):
            scoreboard.persist_snapshot()
        history = scoreboard.read_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["routes"]["feature"][0]["score"], 7.25)
        self.assertIn("epoch", history[0])

    # was test_history_filters_old: assumed history(days=30) filtered by age.
    # The real retention knob is a COUNT, not an age: read_history(max_entries=N)
    # returns the N most recent snapshots, oldest dropped.
    def test_read_history_returns_only_most_recent_entries(self):
        for i in range(5):
            with patch.object(router_stats, "_rebuild", lambda i=i: _table(score=float(i))):
                scoreboard.persist_snapshot()
        history = scoreboard.read_history(max_entries=2)
        self.assertEqual(len(history), 2)
        self.assertEqual([h["routes"]["feature"][0]["score"] for h in history], [3.0, 4.0])

    # was test_prune_removes_old: _prune_history() does not exist and the module
    # never rewrites the file. The real bound on what gets written is per-snapshot:
    # only the top 5 coders per kind are persisted (rows[:5]).
    def test_snapshot_keeps_only_top_five_rows_per_kind(self):
        wide = {"feature": [{"coder": f"c{i}", "score": 10.0 - i, "rate": 0.5,
                             "deployed_rate": 0.5, "n": 3, "usd_per_merge": 1.0}
                            for i in range(9)]}
        with patch.object(router_stats, "_rebuild", lambda: wide):
            snapshot = scoreboard.persist_snapshot()
        self.assertEqual(len(snapshot["routes"]["feature"]), 5)
        self.assertEqual([r["coder"] for r in snapshot["routes"]["feature"]],
                         ["c0", "c1", "c2", "c3", "c4"])

    # was test_prune_no_file: pruning a missing file. The real read paths must
    # tolerate a missing file; trend() is the one not covered elsewhere.
    def test_trend_on_missing_file_returns_empty(self):
        os.unlink(self.history_file) if os.path.exists(self.history_file) else None
        self.assertEqual(scoreboard.trend("feature", "claude"), [])

    def test_read_history_empty_file(self):
        with open(self.history_file, "w"):
            pass
        self.assertEqual(scoreboard.read_history(), [])

    # unchanged intent: a truncated/garbage line must not sink the whole read.
    def test_read_history_skips_corrupt_lines(self):
        with open(self.history_file, "w") as f:
            f.write("not json\n")
            f.write(json.dumps({"timestamp": "2026-07-12T00:00:00Z", "routes": {}}) + "\n")
        history = scoreboard.read_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["timestamp"], "2026-07-12T00:00:00Z")

    # was test_30_day_retention (>= 30 days of history). The real default window
    # is 50 snapshots, so >= 30 snapshots are still readable by default.
    def test_default_window_keeps_at_least_thirty_snapshots(self):
        for i in range(35):
            with patch.object(router_stats, "_rebuild", lambda i=i: _table(score=float(i))):
                scoreboard.persist_snapshot()
        self.assertGreaterEqual(len(scoreboard.read_history()), 30)
        self.assertEqual(len(scoreboard.read_history(max_entries=50)), 35)

    # was test_append_failsoft. This is a real fail-soft contract (CLAUDE.md rule 2:
    # I/O must not raise on permission/path errors) and scoreboard.run() is on the
    # fleet schedule, so an unwritable directory must degrade, not crash the job.
    def test_persist_snapshot_failsoft_on_unwritable_dir(self):
        blocker = os.path.join(self.tmpdir, "blocker")
        with open(blocker, "w") as f:
            f.write("i am a file, not a directory")
        scoreboard._SCOREBOARD_DIR = os.path.join(blocker, "sub")
        scoreboard._SCOREBOARD_FILE = os.path.join(blocker, "sub", "scoreboard.jsonl")

        with patch.object(router_stats, "_rebuild", lambda: _table()):
            snapshot = scoreboard.persist_snapshot()

        # No file could be written, but the caller still gets the snapshot back.
        self.assertFalse(os.path.exists(scoreboard._SCOREBOARD_FILE))
        self.assertIn("routes", snapshot)


class TestDerivedViews(_ScoreboardTempFile):
    """Was TestLeadTimeMetrics, which exercised the non-existent _lead_time_metrics().

    The module's real derived views over persisted history are dashboard_summary()
    and trend(); these tests assert the same properties the old ones wanted —
    empty-data handling, result structure, a value computed from data, and
    fail-soft behaviour — against those functions.
    """

    # was test_no_data_returns_none (lead times None with no rows).
    def test_dashboard_summary_with_no_history(self):
        summary = scoreboard.dashboard_summary()
        self.assertEqual(summary, {"status": "no data", "routes": {}})

    # was test_tokens_per_task_from_assembler: a numeric metric carried through
    # from its source. Here the top coder's score/n come from the router_stats row.
    def test_dashboard_summary_reports_top_coder_per_kind(self):
        with patch.object(router_stats, "_rebuild", lambda: _table(score=9.5, n=20)):
            scoreboard.persist_snapshot()
        summary = scoreboard.dashboard_summary()
        self.assertEqual(summary["top_coders"]["feature"],
                         {"coder": "claude", "score": 9.5, "rate": 0.9, "n": 20})
        self.assertEqual(summary["top_coders"]["bugfix"]["coder"], "codex")
        self.assertEqual(summary["route_count"], 3)  # 2 feature rows + 1 bugfix row

    # was test_result_structure.
    def test_dashboard_summary_structure(self):
        with patch.object(router_stats, "_rebuild", lambda: _table()):
            scoreboard.persist_snapshot()
        summary = scoreboard.dashboard_summary()
        for key in ("timestamp", "route_count", "top_coders"):
            self.assertIn(key, summary)
        self.assertIsNotNone(summary["timestamp"])

    # was test_prompt_to_merged_with_data (a metric computed across two tables).
    # trend() is the real across-snapshots computation: one point per snapshot for
    # the requested kind+coder, and nothing for a coder that never appears.
    def test_trend_tracks_one_coder_across_snapshots(self):
        for score in (1.0, 2.0, 3.0):
            with patch.object(router_stats, "_rebuild", lambda s=score: _table(score=s)):
                scoreboard.persist_snapshot()
        points = scoreboard.trend("feature", "claude")
        self.assertEqual([p["score"] for p in points], [1.0, 2.0, 3.0])
        self.assertEqual(points[0]["n"], 20)
        self.assertEqual(scoreboard.trend("feature", "nobody"), [])

    # was test_lead_time_failsoft (DB errors must not crash the computation).
    # The equivalent real path: router_stats._rebuild() blowing up must leave
    # persist_snapshot() returning None instead of raising into the scheduler.
    def test_persist_snapshot_failsoft_when_router_stats_raises(self):
        def _boom():
            raise RuntimeError("db down")

        with patch.object(router_stats, "_rebuild", _boom):
            self.assertIsNone(scoreboard.persist_snapshot())
        self.assertFalse(os.path.exists(self.history_file))


class TestRunEntryPoint(_ScoreboardTempFile):
    """Was TestComputeIntegration, which called scoreboard.compute() — a function
    this module never defined. run() is the module's real periodic-job entry point
    (it is what the fleet schedule invokes), so the integration assertions moved
    onto it and onto the snapshot payload it produces.
    """

    # was test_compute_includes_lead_times.
    def test_run_persists_snapshot_with_all_route_kinds(self):
        with patch.object(router_stats, "_rebuild", lambda: _table()):
            payload = scoreboard.run()
        self.assertEqual(sorted(payload["routes"]), ["bugfix", "feature"])
        self.assertEqual(len(self._lines()), 1)
        row = payload["routes"]["feature"][0]
        for key in ("coder", "score", "rate", "deployed_rate", "n", "usd_per_merge", "objective"):
            self.assertIn(key, row)

    # was test_compute_has_generated_at: the payload must be timestamped.
    def test_run_payload_is_timestamped(self):
        with patch.object(router_stats, "_rebuild", lambda: _table()):
            payload = scoreboard.run()
        self.assertIn("timestamp", payload)
        self.assertTrue(payload["timestamp"].endswith("Z"))
        self.assertGreater(payload["epoch"], 0)

    # was test_compute_has_overall: the run must feed the dashboard aggregate.
    def test_run_output_feeds_dashboard_summary(self):
        with patch.object(router_stats, "_rebuild", lambda: _table()):
            payload = scoreboard.run()
        summary = scoreboard.dashboard_summary()
        self.assertEqual(summary["timestamp"], payload["timestamp"])
        self.assertEqual(summary["route_count"], 3)
        self.assertEqual(set(summary["top_coders"]), {"feature", "bugfix"})

    # A missing 'objective' on a router_stats row must still snapshot (the module
    # defaults it) — this is the one field _rebuild() does not always emit.
    def test_missing_objective_defaults_to_unknown(self):
        rows = {"feature": [{"coder": "claude", "score": 1.0, "rate": 0.1,
                             "deployed_rate": 0.0, "n": 1, "usd_per_merge": 2.0}]}
        with patch.object(router_stats, "_rebuild", lambda: rows):
            payload = scoreboard.run()
        self.assertEqual(payload["routes"]["feature"][0]["objective"], "unknown")


if __name__ == "__main__":
    unittest.main()
