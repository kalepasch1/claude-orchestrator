#!/usr/bin/env python3
"""The narrowest check that real-time sync is actually reachable from the runner.

Three prior attempts at "implement real-time sync" failed on which-module
ambiguity, and the modules that existed were never scheduled. These tests assert
the two things that make the feature real: the canonical module exposes a
periodic-job entry point, and both jobs are registered AND scheduled.
"""
import os
import re
import sys
import unittest
from unittest import mock

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)


class TestCanonicalRunEntryPoint(unittest.TestCase):
    def setUp(self):
        import realtime_config_sync
        self.mod = realtime_config_sync
        self.mod._last_hash = ""

    def test_run_is_callable(self):
        self.assertTrue(callable(self.mod.run))

    def test_first_run_records_baseline_without_applying(self):
        rows = [{"key": "ORCH_X", "value": "1"}]
        with mock.patch.dict(sys.modules, {"db": mock.Mock(select=lambda *a, **k: rows)}):
            with mock.patch.object(self.mod, "_apply_config") as apply_:
                out = self.mod.run()
        apply_.assert_not_called()
        self.assertEqual(out["applied"], 0)
        self.assertIsNone(out["error"])
        self.assertNotEqual(self.mod._last_hash, "")

    def test_second_run_applies_when_hash_changes(self):
        first = [{"key": "ORCH_X", "value": "1"}]
        second = [{"key": "ORCH_X", "value": "2"}]
        batches = [first, second]
        fake_db = mock.Mock(select=lambda *a, **k: batches.pop(0))
        with mock.patch.dict(sys.modules, {"db": fake_db}):
            with mock.patch.object(self.mod, "_apply_config", return_value=1) as apply_:
                self.mod.run()
                out = self.mod.run()
        apply_.assert_called_once()
        self.assertEqual(out["applied"], 1)

    def test_run_is_fail_soft_on_db_error(self):
        fake_db = mock.Mock()
        fake_db.select.side_effect = Exception("supabase 522")
        before = self.mod.stats()["errors"]
        with mock.patch.dict(sys.modules, {"db": fake_db}):
            out = self.mod.run()  # must not raise
        self.assertEqual(out["applied"], 0)
        self.assertIn("522", out["error"])
        self.assertGreater(self.mod.stats()["errors"], before)


class TestJobsAreRegisteredAndScheduled(unittest.TestCase):
    """A job in JOBS but not in runner.py's table never runs, and vice versa."""

    def test_registered_in_periodic_jobs(self):
        import periodic
        for job in ("rtmon", "rtconfig"):
            self.assertIn(job, periodic.JOBS, f"{job} missing from periodic.JOBS")
            self.assertTrue(callable(periodic.JOBS[job]))

    def test_scheduled_in_runner_interval_table(self):
        src = open(os.path.join(RUNNER, "runner.py"), errors="replace").read()
        for job in ("rtmon", "rtconfig"):
            self.assertRegex(
                src,
                r'\(\s*"[^"]*",\s*"%s"\s*,\s*"interval"' % re.escape(job),
                f"{job} is in periodic.JOBS but nothing schedules it",
            )

    def test_jobs_are_safe_when_paused(self):
        """Neither spends tokens; both must survive the kill switch."""
        src = open(os.path.join(RUNNER, "periodic.py"), errors="replace").read()
        block = src.split("_SAFE_WHEN_PAUSED", 1)[1].split("}", 1)[0]
        for job in ("rtmon", "rtconfig"):
            self.assertIn(f'"{job}"', block)


class TestDeprecatedRivalsAreLabelled(unittest.TestCase):
    """Five rival implementations is what made this task unimplementable."""

    DEPRECATED = ("realtime_sync.py", "config_sync_realtime.py", "realtime_monitor.py")

    def test_rivals_say_deprecated_and_name_the_canonical_module(self):
        for name in self.DEPRECATED:
            head = open(os.path.join(RUNNER, name), errors="replace").read(2000)
            self.assertIn("DEPRECATED", head, f"{name} is dead but not labelled")
            self.assertTrue(
                "realtime_config_sync" in head or "realtime_approval_monitor" in head,
                f"{name} does not point at a canonical module",
            )

    def test_rivals_are_still_unimported(self):
        """If one of these gains an importer, this test fails and the label is a lie."""
        stems = [n[:-3] for n in self.DEPRECATED]
        for fname in os.listdir(RUNNER):
            if not fname.endswith(".py") or fname in self.DEPRECATED:
                continue
            src = open(os.path.join(RUNNER, fname), errors="replace").read()
            for stem in stems:
                self.assertNotRegex(
                    src,
                    r"^\s*(import|from)\s+%s\b" % re.escape(stem),
                    f"{fname} imports deprecated {stem}",
                )


if __name__ == "__main__":
    unittest.main()
