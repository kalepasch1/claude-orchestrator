#!/usr/bin/env python3
"""The post-deploy smoke suite must be able to FAIL (canary-deepseek-6).

Running the deepseek-6 smoke tests found them all green — but green because the
implementation could not go red:

  * db_connectivity returned passed=True with the detail "(logical)" when there
    was no supabase client at all. It is one of the two CRITICAL checks, the
    ones whose failure aborts a promote, so the abort could not fire for the
    case it exists to catch.
  * workflow_smoke accepted `base_url` and never read it, so it passed for an
    environment with no deploy behind it.
  * the mismatch branch leaked its marker file, so the next run for the same
    task read back the stale marker and passed on it.

These tests pin the failure paths. A smoke check that cannot fail is not a
check, and the way that defect hides is by looking like a passing suite.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmpdir = tempfile.mkdtemp()

from env_during_import import during_import  # noqa: E402

with during_import(CLAUDE_ORCH_HOME=_tmpdir):
    from tests import smoke_tests  # noqa: E402

ENV = {"PREVIEW_DB_REF": "abc123", "PREVIEW_DB_URL": "postgres://preview"}


class DbConnectivityFailsHonestlyTest(unittest.TestCase):
    def test_no_db_configured_fails(self):
        r = smoke_tests.db_connectivity_check({})
        self.assertFalse(r.passed)
        self.assertIn("no DB configured", r.detail)

    def test_absent_client_is_a_failure_not_a_logical_pass(self):
        """The regression itself."""
        fake = mock.Mock(spec=["supabase"])
        fake.supabase = None
        with mock.patch.dict(sys.modules, {"db": fake}):
            r = smoke_tests.db_connectivity_check(ENV)
        self.assertFalse(r.passed, "no client must not report healthy")
        self.assertNotIn("logical", r.detail)

    def test_query_failure_is_reported_as_failure(self):
        fake = mock.Mock(spec=["supabase", "select"])
        fake.supabase = object()
        fake.select.side_effect = RuntimeError("connection refused")
        with mock.patch.dict(sys.modules, {"db": fake}):
            r = smoke_tests.db_connectivity_check(ENV)
        self.assertFalse(r.passed)
        self.assertIn("connection refused", r.detail)

    def test_successful_query_passes(self):
        fake = mock.Mock(spec=["supabase", "select"])
        fake.supabase = object()
        fake.select.return_value = [{"id": "1"}]
        with mock.patch.dict(sys.modules, {"db": fake}):
            r = smoke_tests.db_connectivity_check(ENV)
        self.assertTrue(r.passed)
        self.assertIn("query ok", r.detail)
        fake.select.assert_called_once()

    def test_a_real_query_is_actually_issued(self):
        """Importing the module proves nothing about reachability."""
        fake = mock.Mock(spec=["supabase", "select"])
        fake.supabase = object()
        fake.select.return_value = []
        with mock.patch.dict(sys.modules, {"db": fake}):
            smoke_tests.db_connectivity_check(ENV)
        self.assertTrue(fake.select.called, "no round-trip was attempted")


class WorkflowSmokeUsesTheUrlTest(unittest.TestCase):
    def test_empty_base_url_fails(self):
        r = smoke_tests.workflow_smoke_test("", {"PREVIEW_TASK_ID": "t1"})
        self.assertFalse(r.passed)
        self.assertIn("no preview URL", r.detail)

    def test_round_trip_passes_with_a_url(self):
        r = smoke_tests.workflow_smoke_test(
            "http://localhost:3001", {"PREVIEW_TASK_ID": "t2"})
        self.assertTrue(r.passed)

    def test_marker_is_cleaned_up_on_success(self):
        smoke_tests.workflow_smoke_test(
            "http://localhost:3001", {"PREVIEW_TASK_ID": "t3"})
        marker = os.path.join(smoke_tests.HOME, "smoke-markers", "smoke-t3.json")
        self.assertFalse(os.path.exists(marker))

    def test_a_stale_marker_cannot_be_read_back_as_this_runs_entity(self):
        """The leak: a previous failure's marker must not make the next run pass."""
        marker_dir = os.path.join(smoke_tests.HOME, "smoke-markers")
        os.makedirs(marker_dir, exist_ok=True)
        marker = os.path.join(marker_dir, "smoke-t4.json")
        with open(marker, "w") as f:
            json.dump({"id": "smoke-t4", "type": "stale"}, f)

        smoke_tests.workflow_smoke_test(
            "http://localhost:3001", {"PREVIEW_TASK_ID": "t4"})
        self.assertFalse(os.path.exists(marker), "stale marker survived the run")


class CriticalFailureAbortsTest(unittest.TestCase):
    def test_db_failure_aborts_the_suite(self):
        """db_connectivity is critical: its failure must block a promote."""
        env = {"url": "http://127.0.0.1:1", "env_vars": ENV}
        fake_mgr = mock.Mock()
        fake_mgr.get_preview_env.return_value = env
        fake_db = mock.Mock(spec=["supabase"])
        fake_db.supabase = None
        with mock.patch.dict(sys.modules, {"preview_env_manager": fake_mgr,
                                           "db": fake_db}):
            report = smoke_tests.run_smoke_suite("abort-1")
        self.assertEqual(report["status"], "abort")
        names = {r["name"]: r["passed"] for r in report["results"]}
        self.assertFalse(names["db_connectivity"])


if __name__ == "__main__":
    unittest.main()
