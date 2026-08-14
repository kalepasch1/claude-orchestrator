"""Regression tests: an unreachable Supabase must not crash-loop the periodic jobs.

Three jobs were failing silently and permanently against the SAME root cause — a bare
urllib.error.URLError escaping db.select():

    resource-governor           10,101 tracebacks
    batch-completion             1,995 tracebacks (100% of its runs — module fully dead)
    virtual-executive-worker     1,803 tracebacks (100% of its runs — module fully dead)

db._req now classifies endpoint exhaustion as TransientDBError, the counterpart of the
existing MissingRelationError. Transient means "skip this cycle"; structural means "disable".

Imports here are flat (`import db`, `import periodic`), matching conftest.py and the rest of
the suite. `from runner import ...` is NOT safe: runner/ contains a runner.py, so once the
runner directory is on sys.path the name `runner` resolves to that module instead of the
package, and the import fails only under a whole-suite run.
"""
import json
import socket
import subprocess
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import db
import periodic

RUNNER = Path(__file__).resolve().parents[1]


class TestEndpointExhaustionIsTransient(unittest.TestCase):
    """db._req must not leak a bare URLError once every endpoint is unreachable."""

    def setUp(self):
        # Make these hermetic. _req refuses to build a request without credentials, and the
        # suite may or may not have them depending on import order, so supply throwaway values.
        # _base_urls is pinned to one endpoint so the assertion does not depend on how many
        # failover hosts are configured, nor on _ACTIVE_BASE state left behind by another test.
        env = patch.multiple(
            db,
            URL="https://unreachable.test.supabase.co",
            KEY="test-key-not-real",
            HTTP_RETRIES=0,
        )
        env.start()
        self.addCleanup(env.stop)
        bases = patch.object(
            db, "_base_urls", return_value=["https://unreachable.test.supabase.co"])
        bases.start()
        self.addCleanup(bases.stop)

    def test_url_error_becomes_transient_db_error(self):
        err = urllib.error.URLError(socket.timeout("timed out"))
        with patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(db.TransientDBError) as ctx:
                db._req("GET", "/rest/v1/runner_alerts")
        self.assertIsInstance(ctx.exception.__cause__, urllib.error.URLError)

    def test_timeout_error_becomes_transient_db_error(self):
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            with self.assertRaises(db.TransientDBError):
                db._req("GET", "/rest/v1/runner_alerts")

    def test_http_error_is_not_relabelled_as_unreachable(self):
        """HTTPError subclasses URLError; a 500 must stay a 500, not become a network error."""
        err = urllib.error.HTTPError(
            url="https://unreachable.test.supabase.co/rest/v1/tasks",
            code=500, msg="Internal Server Error", hdrs={}, fp=None)
        with patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(urllib.error.HTTPError):
                db._req("GET", "/rest/v1/tasks")

    def test_transient_is_not_confused_with_missing_relation(self):
        """The two must stay distinguishable — one disables a job, the other only skips it."""
        self.assertFalse(issubclass(db.TransientDBError, db.MissingRelationError))
        self.assertFalse(issubclass(db.MissingRelationError, db.TransientDBError))

    def test_select_surfaces_transient_db_error(self):
        """db.select() is the call site all three dead jobs died on."""
        err = urllib.error.URLError(socket.timeout("timed out"))
        with patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(db.TransientDBError):
                db.select("runner_alerts", {"select": "id"})


class TestPeriodicSkipsRatherThanDisables(unittest.TestCase):
    """A transient outage must not take a healthy job offline for its duration."""

    def test_transient_skips_and_does_not_disable(self):
        def _boom():
            raise db.TransientDBError("all Supabase endpoints unreachable")

        # A synthetic job name, so this never depends on (or perturbs) the real registry.
        with patch.dict(periodic.JOBS, {"_probe_transient": _boom}, clear=False), \
             patch.object(periodic, "_disable_job") as disable:
            result = periodic._invoke_job("_probe_transient")

        disable.assert_not_called()
        self.assertEqual(result.get("skipped"), "transient-db")

    def test_missing_relation_still_disables(self):
        """The structural path must keep working — this is the regression guard on the fix."""
        def _boom():
            raise db.MissingRelationError("relation 'legal_obligations' does not exist")

        with patch.dict(periodic.JOBS, {"_probe_missing": _boom}, clear=False), \
             patch.object(periodic, "_disable_job") as disable:
            result = periodic._invoke_job("_probe_missing")

        disable.assert_called_once()
        self.assertIsNone(result)


class TestJobsExitZeroWhenSupabaseIsDown(unittest.TestCase):
    """End-to-end: each previously-dead module must exit 0, not dump a traceback.

    Pointed at a black-holed SUPABASE_URL so every endpoint really is unreachable.
    """

    JOBS = ("resource_governor", "batch_completion", "virtual_executive_worker")

    def _run(self, module):
        env = {
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(Path.home()),
            "SUPABASE_URL": "https://127.0.0.1:1",  # nothing listens here
            "SUPABASE_SERVICE_KEY": "test-key-not-real",
            "ORCH_SUPABASE_TIMEOUT": "1",
            "HTTP_RETRIES": "0",
        }
        return subprocess.run(
            [sys.executable, str(RUNNER / f"{module}.py")],
            capture_output=True, text=True, timeout=180, env=env, cwd=str(RUNNER.parent),
        )

    def test_each_job_exits_zero_and_emits_no_traceback(self):
        for module in self.JOBS:
            with self.subTest(module=module):
                proc = self._run(module)
                self.assertEqual(
                    proc.returncode, 0,
                    f"{module} exited {proc.returncode}; stderr:\n{proc.stderr[-1500:]}")
                self.assertNotIn(
                    "Traceback (most recent call last)", proc.stderr,
                    f"{module} still dumps a traceback:\n{proc.stderr[-1500:]}")

    def test_output_stays_machine_readable(self):
        """Callers parse stdout as JSON; the skip path must not break that contract."""
        for module in self.JOBS:
            with self.subTest(module=module):
                proc = self._run(module)
                last = [ln for ln in proc.stdout.splitlines() if ln.strip()]
                self.assertTrue(last, f"{module} produced no stdout")
                self.assertIsInstance(json.loads(last[-1]), dict)


if __name__ == "__main__":
    unittest.main()
