"""crash_loop_detector: the 19-day silent preflight_gate failure must not be possible again."""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import crash_loop_detector as cld

# The real traceback that repeated 4,961 times in .runtime/logs/preflight.err.
PREFLIGHT_TB = (
    "Traceback (most recent call last):\n"
    '  File "/Users/kpasch/Documents/beethoven/claude-orchestrator/runner/periodic.py", line 867, in <module>\n'
    "    _run_job_locked(job)\n"
    '  File "/Users/kpasch/Documents/beethoven/claude-orchestrator/runner/preflight_gate.py", line 145, in run\n'
    "    admission = pipeline_contract.task_fields(\n"
    "AttributeError: module 'pipeline_contract' has no attribute 'task_fields'\n"
)
NAME_TB = (
    "Traceback (most recent call last):\n"
    '  File "/x/runner/resource_governor.py", line 12, in run\n'
    "    total = _elapsed_ms(start)\n"
    "NameError: name '_elapsed_ms' is not defined\n"
)
WEATHER_TB = (
    "Traceback (most recent call last):\n"
    '  File "/x/runner/db.py", line 279, in _req\n'
    "    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:\n"
    "urllib.error.HTTPError: HTTP Error 522: <none>\n"
)


class CrashLoopDetectorTest(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cld-test-")
        self.home = tempfile.mkdtemp(prefix="cld-home-")
        os.environ["CLAUDE_ORCH_HOME"] = self.home

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)
        shutil.rmtree(self.home, ignore_errors=True)

    def _job(self, name, err_body, log_body="", log_age=0):
        with open(os.path.join(self.dir, name + ".err"), "w") as f:
            f.write(err_body)
        log = os.path.join(self.dir, name + ".log")
        with open(log, "w") as f:
            f.write(log_body)
        if log_age:
            old = time.time() - log_age
            os.utime(log, (old, old))

    # ── parsing ─────────────────────────────────────────────────────────────
    def test_parses_repeated_tracebacks_into_one_signature(self):
        found = cld.parse_tracebacks(PREFLIGHT_TB * 7)
        self.assertEqual(len(found), 7)
        self.assertEqual(len({t["signature"] for t in found}), 1)
        self.assertIn("task_fields", found[0]["exception"])
        self.assertIn("preflight_gate.py", found[0]["last_frame"])

    def test_line_numbers_and_paths_do_not_split_a_signature(self):
        a = cld.parse_tracebacks(PREFLIGHT_TB)[0]
        b = cld.parse_tracebacks(PREFLIGHT_TB.replace("line 145", "line 151"))[0]
        self.assertEqual(a["signature"], b["signature"])

    def test_different_bugs_get_different_signatures(self):
        a = cld.parse_tracebacks(PREFLIGHT_TB)[0]
        b = cld.parse_tracebacks(NAME_TB)[0]
        self.assertNotEqual(a["signature"], b["signature"])

    # ── classification ──────────────────────────────────────────────────────
    def test_module_that_never_succeeds_is_flagged_dead(self):
        self._job("synthdead", PREFLIGHT_TB * 60, log_body="", log_age=99999)
        findings = cld.classify(cld.scan(self.dir))
        self.assertEqual(len(findings), 1)
        self.assertIn("module_dead", findings[0]["reasons"])
        self.assertEqual(findings[0]["severity"], "critical")
        self.assertEqual(findings[0]["share"], 1.0)

    def test_high_volume_repetition_fires_even_with_a_healthy_log(self):
        self._job("synthnoisy", NAME_TB * 120, log_body="ran\n" * 50)
        findings = cld.classify(cld.scan(self.dir))
        self.assertEqual(len(findings), 1)
        self.assertIn("repeating", findings[0]["reasons"])
        self.assertNotIn("module_dead", findings[0]["reasons"])

    def test_occasional_failures_do_not_fire(self):
        self._job("synthhealthy", PREFLIGHT_TB * 3, log_body="ok\n" * 500)
        self.assertEqual(cld.classify(cld.scan(self.dir)), [])

    def test_network_weather_is_suppressed(self):
        self._job("synthweather", WEATHER_TB * 200, log_body="fine\n" * 100)
        self.assertEqual(cld.classify(cld.scan(self.dir)), [])

    def test_findings_are_ranked_by_blast_radius(self):
        self._job("small", PREFLIGHT_TB * 60, log_body="", log_age=99999)
        self._job("huge", NAME_TB * 5000, log_body="ran\n" * 10)
        findings = cld.classify(cld.scan(self.dir))
        self.assertEqual(findings[0]["job"], "huge")

    def test_stale_err_files_outside_the_window_are_ignored(self):
        self._job("old", PREFLIGHT_TB * 60)
        old = time.time() - 86400 * 30
        os.utime(os.path.join(self.dir, "old.err"), (old, old))
        self.assertEqual(cld.scan(self.dir, window_hours=1), {})

    # ── dedupe + firing ─────────────────────────────────────────────────────
    def test_second_run_deduplicates_the_same_signature(self):
        self._job("synthdead", PREFLIGHT_TB * 60, log_body="", log_age=99999)
        fake_db = MagicMock()
        fake_db.select.return_value = [{"id": "p1", "name": "beethoven",
                                        "repo_path": os.path.dirname(os.path.dirname(
                                            os.path.dirname(os.path.abspath(cld.__file__))))}]
        with patch.object(cld, "db", fake_db), patch.object(cld, "_alert") as alert:
            first = cld.run(log_dir=self.dir)
            second = cld.run(log_dir=self.dir)
        self.assertEqual(first["fired"], 1)
        self.assertEqual(second["fired"], 0)
        self.assertEqual(second["deduplicated"], 1)
        self.assertEqual(alert.call_count, 1)

    def test_firing_files_a_remediation_task_carrying_the_traceback(self):
        self._job("synthdead", PREFLIGHT_TB * 60, log_body="", log_age=99999)
        fake_db = MagicMock()
        fake_db.select.return_value = []
        inserted = []

        def _insert(table, row):
            inserted.append((table, row))
            return {"id": "row-%d" % len(inserted)}

        fake_db.insert.side_effect = _insert
        with patch.object(cld, "db", fake_db), \
             patch.object(cld, "_orchestrator_project", return_value={"id": "p1", "name": "beethoven"}):
            summary = cld.run(log_dir=self.dir)
        self.assertEqual(summary["tasks_filed"], 1)
        task = next(row for table, row in inserted if table == "tasks")
        self.assertTrue(task["slug"].startswith("crashloop-synthdead-"))
        self.assertEqual(task["state"], "QUEUED")
        self.assertIn("task_fields", task["prompt"])
        self.assertIn("100% dead", task["prompt"])
        self.assertTrue(any(table == "approvals" for table, _ in inserted))

    def test_dry_run_changes_nothing(self):
        self._job("synthdead", PREFLIGHT_TB * 60, log_body="", log_age=99999)
        with patch.object(cld, "db", MagicMock()), patch.object(cld, "_alert") as alert:
            summary = cld.run(log_dir=self.dir, dry_run=True)
        self.assertEqual(summary["fired"], 1)
        self.assertEqual(summary["tasks_filed"], 0)
        self.assertFalse(alert.called)
        self.assertFalse(os.path.exists(cld._state_path()))

    def test_numeric_variants_collapse_into_one_signature(self):
        """'field1'/'field2' differ only by a number: one bug, one alert — not eight."""
        for i in range(4):
            self._job("dead%d" % i, PREFLIGHT_TB.replace("task_fields", "field%d" % i) * 60,
                      log_body="", log_age=99999)
        findings = cld.classify(cld.scan(self.dir))
        self.assertEqual(len({f["signature"] for f in findings}), 1)

    def test_alert_storm_is_throttled_per_cycle(self):
        for name in ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel"):
            self._job("dead_" + name, PREFLIGHT_TB.replace("task_fields", name) * 60,
                      log_body="", log_age=99999)
        with patch.object(cld, "db", MagicMock()), patch.object(cld, "_alert"), \
             patch.object(cld, "_orchestrator_project", return_value={}):
            summary = cld.run(log_dir=self.dir)
        self.assertEqual(summary["findings"], 8)
        self.assertEqual(summary["fired"], cld.MAX_FIRES)
        self.assertEqual(summary["throttled"], 8 - cld.MAX_FIRES)


if __name__ == "__main__":
    unittest.main()
