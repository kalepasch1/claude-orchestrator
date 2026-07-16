import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import branch_recovery_periodic


class BranchRecoveryPeriodicTest(unittest.TestCase):
    def setUp(self):
        branch_recovery_periodic._stats.update({
            "runs": 0, "last_run": None,
            "total_detected": 0, "total_recovered": 0,
            "projects_scanned": 0, "errors": 0,
        })

    def test_stats_returns_dict_copy(self):
        s = branch_recovery_periodic.stats()
        self.assertIsInstance(s, dict)
        self.assertIn("runs", s)
        self.assertIn("total_detected", s)
        s["runs"] = 999
        self.assertEqual(branch_recovery_periodic._stats["runs"], 0)

    @mock.patch.dict(os.environ, {"ORCH_BRANCH_RECOVERY_ENABLED": "false"})
    def test_run_disabled_returns_skipped(self):
        # Reload to pick up env
        import importlib
        importlib.reload(branch_recovery_periodic)
        result = branch_recovery_periodic.run()
        self.assertTrue(result.get("skipped"))
        self.assertEqual(result.get("reason"), "disabled")
        # Restore
        importlib.reload(branch_recovery_periodic)

    @mock.patch.object(branch_recovery_periodic, "ENABLED", True)
    @mock.patch.object(branch_recovery_periodic, "_load_projects", return_value=[])
    def test_run_no_projects(self, _load):
        result = branch_recovery_periodic.run()
        self.assertEqual(result["projects"], 0)
        self.assertEqual(result["detected"], 0)

    @mock.patch.object(branch_recovery_periodic, "ENABLED", True)
    @mock.patch.object(branch_recovery_periodic, "DRY_RUN", True)
    @mock.patch.object(branch_recovery_periodic, "_load_projects")
    @mock.patch.object(branch_recovery_periodic, "_detect_missing_branches")
    def test_dry_run_detects_but_does_not_recover(self, detect_mock, load_mock):
        load_mock.return_value = [
            {"id": "p1", "name": "testproj", "repo_path": "/tmp/fakerepo", "default_base": "master"}
        ]
        detect_mock.return_value = [
            {"id": "t1", "slug": "test-task", "project_id": "p1"}
        ]
        with mock.patch.object(branch_recovery_periodic, "_recover_project",
                               return_value=(1, 0)) as recover_mock:
            result = branch_recovery_periodic.run()
            self.assertEqual(result["detected"], 1)
            self.assertEqual(result["recovered"], 0)
            self.assertTrue(result["dry_run"])

    @mock.patch.object(branch_recovery_periodic, "ENABLED", True)
    @mock.patch.object(branch_recovery_periodic, "DRY_RUN", False)
    @mock.patch.object(branch_recovery_periodic, "_load_projects")
    @mock.patch.object(branch_recovery_periodic, "_detect_missing_branches")
    def test_live_mode_recovers(self, detect_mock, load_mock):
        load_mock.return_value = [
            {"id": "p1", "name": "testproj", "repo_path": "/tmp/fakerepo", "default_base": "master"}
        ]
        detect_mock.return_value = [
            {"id": "t1", "slug": "test-task", "project_id": "p1"}
        ]
        with mock.patch.object(branch_recovery_periodic, "_recover_project",
                               return_value=(1, 1)) as recover_mock:
            result = branch_recovery_periodic.run()
            self.assertEqual(result["detected"], 1)
            self.assertEqual(result["recovered"], 1)
            self.assertFalse(result["dry_run"])

    @mock.patch.dict(os.environ, {"ORCH_BRANCH_RECOVERY_PROJECTS": "/tmp/a:/tmp/b"})
    def test_load_projects_from_env(self):
        projects = branch_recovery_periodic._load_projects()
        self.assertEqual(len(projects), 2)
        self.assertEqual(projects[0]["repo_path"], "/tmp/a")
        self.assertEqual(projects[1]["repo_path"], "/tmp/b")

    @mock.patch.object(branch_recovery_periodic.db, "select", return_value=[
        {"id": "p1", "name": "proj1", "repo_path": "/tmp/repo1"}
    ])
    @mock.patch.object(branch_recovery_periodic.db, "localize_repo_path", side_effect=lambda x: x)
    def test_load_projects_from_db(self, _loc, _sel):
        result = branch_recovery_periodic._load_projects()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "p1")

    @mock.patch.object(branch_recovery_periodic.db, "select", side_effect=Exception("db down"))
    @mock.patch.object(branch_recovery_periodic.db, "localize_repo_path", side_effect=lambda x: x)
    def test_load_projects_db_error_returns_empty(self, _loc, _sel):
        result = branch_recovery_periodic._load_projects()
        self.assertEqual(result, [])
        self.assertGreater(branch_recovery_periodic._stats["errors"], 0)

    @mock.patch.object(branch_recovery_periodic, "ENABLED", True)
    @mock.patch.object(branch_recovery_periodic, "_load_projects")
    @mock.patch.object(branch_recovery_periodic, "_detect_missing_branches", side_effect=Exception("boom"))
    def test_run_handles_project_error_gracefully(self, _det, load_mock):
        load_mock.return_value = [
            {"id": "p1", "name": "broken", "repo_path": "/tmp/nope"}
        ]
        result = branch_recovery_periodic.run()
        self.assertEqual(result["projects"], 0)
        self.assertGreater(branch_recovery_periodic._stats["errors"], 0)

    @mock.patch.object(branch_recovery_periodic, "ENABLED", True)
    @mock.patch.object(branch_recovery_periodic, "_load_projects")
    @mock.patch.object(branch_recovery_periodic, "_detect_missing_branches", return_value=[])
    def test_run_increments_stats(self, _det, load_mock):
        load_mock.return_value = [
            {"id": "p1", "name": "proj", "repo_path": "/tmp/repo"}
        ]
        branch_recovery_periodic.run()
        s = branch_recovery_periodic.stats()
        self.assertEqual(s["runs"], 1)
        self.assertIsNotNone(s["last_run"])
        self.assertEqual(s["projects_scanned"], 1)


if __name__ == "__main__":
    unittest.main()
