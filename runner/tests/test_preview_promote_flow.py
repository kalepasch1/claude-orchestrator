#!/usr/bin/env python3
"""
test_preview_promote_flow.py — end-to-end tests for the preview→smoke→promote pipeline.

Covers four scenarios:
  1. create_preview (isolated) → run_smokes (pass) → promote_to_prod (success)
  2. rollback_on_smoke_failure: smokes fail → preview NOT promoted
  3. preview env creation failure → graceful degradation
  4. preview env cleanup: no leaked envs after success or failure

Uses unittest.mock to stub Vercel/Supabase API calls.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import preview_deployer
import smoke_test_runner
import promotion_pipeline
import preview_promote


class TestPreviewDeployer(unittest.TestCase):
    """Unit tests for preview_deployer with mocked supabase_twin."""

    @mock.patch("preview_deployer.supabase_twin")
    def test_create_returns_preview_env(self, mock_twin):
        mock_twin.create.return_value = {
            "branch_id": "br-123",
            "db_url": "postgresql://preview:5432/test",
        }
        env = preview_deployer.create_preview_env("my-slug")
        self.assertIsNotNone(env)
        self.assertEqual(env.branch_id, "br-123")
        self.assertTrue(env.env_id.startswith("preview-my-slug-"))
        self.assertIn("preview", env.db_url)

    @mock.patch("preview_deployer.supabase_twin")
    def test_create_failure_returns_none(self, mock_twin):
        mock_twin.create.side_effect = RuntimeError("API down")
        env = preview_deployer.create_preview_env("fail-slug")
        self.assertIsNone(env)

    @mock.patch("preview_deployer.supabase_twin")
    def test_destroy_calls_delete(self, mock_twin):
        mock_twin.delete.return_value = True
        env = preview_deployer.PreviewEnv("e1", "br-1", "db://x", "n1")
        ok = preview_deployer.destroy_preview_env(env)
        self.assertTrue(ok)
        mock_twin.delete.assert_called_once_with("br-1")

    @mock.patch("preview_deployer.supabase_twin")
    def test_destroy_none_returns_false(self, mock_twin):
        self.assertFalse(preview_deployer.destroy_preview_env(None))


class TestSmokeTestRunner(unittest.TestCase):
    """Unit tests for smoke_test_runner with mocked HTTP endpoints."""

    @mock.patch("smoke_test_runner.urllib.request.urlopen")
    def test_all_pass(self, mock_urlopen):
        resp = mock.MagicMock()
        resp.status = 200
        resp.read.return_value = b'{"status":"ok"}'
        resp.__enter__ = mock.Mock(return_value=resp)
        resp.__exit__ = mock.Mock(return_value=False)
        mock_urlopen.return_value = resp

        result = smoke_test_runner.run_smoke_tests("https://preview.example.com")
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["tests"]), 3)
        for t in result["tests"]:
            self.assertEqual(t["status"], "pass")

    def test_no_url_fails(self):
        result = smoke_test_runner.run_smoke_tests("")
        self.assertFalse(result["passed"])
        self.assertEqual(result["tests"][0]["status"], "fail")

    @mock.patch("smoke_test_runner._http_get")
    def test_health_fail(self, mock_get):
        mock_get.side_effect = [
            (200, "ok"),    # GET /
            (500, "error"), # GET /api/health
            (200, "ok"),    # GET /login
        ]
        result = smoke_test_runner.run_smoke_tests("https://preview.example.com")
        self.assertFalse(result["passed"])
        statuses = [t["status"] for t in result["tests"]]
        self.assertEqual(statuses, ["pass", "fail", "pass"])


class TestPromotionPipeline(unittest.TestCase):
    """Unit tests for promotion_pipeline with mocked Vercel API."""

    @mock.patch("promotion_pipeline._vreq")
    def test_promote_success(self, mock_vreq):
        mock_vreq.side_effect = [
            {"deployments": [{"uid": "dep-1", "projectId": "proj-1"}]},
            {"status": "ok"},
        ]
        result = promotion_pipeline.promote_to_prod("https://preview-abc.vercel.app")
        self.assertTrue(result["success"])
        self.assertEqual(result["deployment_id"], "dep-1")

    @mock.patch("promotion_pipeline._vreq")
    def test_promote_no_deployment(self, mock_vreq):
        mock_vreq.return_value = {"deployments": []}
        result = promotion_pipeline.promote_to_prod("https://nonexistent.vercel.app")
        self.assertFalse(result["success"])

    @mock.patch("promotion_pipeline._vreq")
    def test_rollback_success(self, mock_vreq):
        mock_vreq.side_effect = [
            {"projectId": "proj-1"},
            {"status": "ok"},
        ]
        result = promotion_pipeline.rollback_prod("dep-old")
        self.assertTrue(result["success"])

    def test_rollback_no_id(self):
        result = promotion_pipeline.rollback_prod("")
        self.assertFalse(result["success"])


class TestPreviewPromoteFlow(unittest.TestCase):
    """End-to-end flow tests (all external calls mocked)."""

    def _task(self):
        return {"id": "t-1", "slug": "test-feature", "project_id": "p-1"}

    def _proj(self):
        return {"id": "p-1", "name": "testapp", "vercel_project": "web"}

    @mock.patch.dict(os.environ, {"ORCH_PREVIEW_PROMOTE_ENABLED": "true"})
    @mock.patch("preview_promote.db")
    @mock.patch("preview_promote._promotion_pipeline")
    @mock.patch("preview_promote._smoke_test_runner")
    @mock.patch("preview_promote._preview_deployer")
    @mock.patch("preview_promote._wait_for_preview")
    def test_happy_path(self, mock_wait, mock_deployer, mock_smoke, mock_promote, mock_db):
        # Ensure modules are "loaded"
        preview_promote._preview_deployer = mock_deployer
        preview_promote._smoke_test_runner = mock_smoke
        preview_promote._promotion_pipeline = mock_promote

        env = preview_deployer.PreviewEnv("e1", "br-1", "db://x", "n1")
        mock_deployer.create_preview_env.return_value = env
        mock_wait.return_value = "https://preview.vercel.app"
        mock_smoke.run_smoke_tests.return_value = {"passed": True, "tests": []}
        mock_promote.promote_to_prod.return_value = {"success": True}

        result = preview_promote.run_preview_promote("test-feature", self._task(), self._proj())
        self.assertTrue(result["promoted"])
        self.assertTrue(result["smoke_passed"])
        mock_deployer.destroy_preview_env.assert_called_once_with(env)

    @mock.patch.dict(os.environ, {"ORCH_PREVIEW_PROMOTE_ENABLED": "true"})
    @mock.patch("preview_promote.db")
    @mock.patch("preview_promote._promotion_pipeline")
    @mock.patch("preview_promote._smoke_test_runner")
    @mock.patch("preview_promote._preview_deployer")
    @mock.patch("preview_promote._wait_for_preview")
    def test_smoke_failure_no_promote(self, mock_wait, mock_deployer, mock_smoke, mock_promote, mock_db):
        preview_promote._preview_deployer = mock_deployer
        preview_promote._smoke_test_runner = mock_smoke
        preview_promote._promotion_pipeline = mock_promote

        env = preview_deployer.PreviewEnv("e1", "br-1", "db://x", "n1")
        mock_deployer.create_preview_env.return_value = env
        mock_wait.return_value = "https://preview.vercel.app"
        mock_smoke.run_smoke_tests.return_value = {
            "passed": False,
            "tests": [{"name": "GET /", "status": "fail", "error": "HTTP 500"}],
        }

        result = preview_promote.run_preview_promote("test-feature", self._task(), self._proj())
        self.assertFalse(result["promoted"])
        self.assertFalse(result["smoke_passed"])
        mock_promote.promote_to_prod.assert_not_called()
        mock_deployer.destroy_preview_env.assert_called_once_with(env)

    @mock.patch.dict(os.environ, {"ORCH_PREVIEW_PROMOTE_ENABLED": "true"})
    @mock.patch("preview_promote.db")
    @mock.patch("preview_promote._promotion_pipeline")
    @mock.patch("preview_promote._smoke_test_runner")
    @mock.patch("preview_promote._preview_deployer")
    def test_env_creation_failure(self, mock_deployer, mock_smoke, mock_promote, mock_db):
        preview_promote._preview_deployer = mock_deployer
        preview_promote._smoke_test_runner = mock_smoke
        preview_promote._promotion_pipeline = mock_promote

        mock_deployer.create_preview_env.return_value = None

        result = preview_promote.run_preview_promote("test-feature", self._task(), self._proj())
        self.assertFalse(result["promoted"])
        self.assertIsNone(result["smoke_passed"])
        self.assertIn("failed to create", result.get("error", ""))
        mock_smoke.run_smoke_tests.assert_not_called()
        mock_promote.promote_to_prod.assert_not_called()

    @mock.patch.dict(os.environ, {"ORCH_PREVIEW_PROMOTE_ENABLED": "true"})
    @mock.patch("preview_promote.db")
    @mock.patch("preview_promote._promotion_pipeline")
    @mock.patch("preview_promote._smoke_test_runner")
    @mock.patch("preview_promote._preview_deployer")
    @mock.patch("preview_promote._wait_for_preview")
    def test_no_env_leak_on_exception(self, mock_wait, mock_deployer, mock_smoke, mock_promote, mock_db):
        preview_promote._preview_deployer = mock_deployer
        preview_promote._smoke_test_runner = mock_smoke
        preview_promote._promotion_pipeline = mock_promote

        env = preview_deployer.PreviewEnv("e1", "br-1", "db://x", "n1")
        mock_deployer.create_preview_env.return_value = env
        mock_wait.return_value = "https://preview.vercel.app"
        mock_smoke.run_smoke_tests.side_effect = RuntimeError("boom")

        result = preview_promote.run_preview_promote("test-feature", self._task(), self._proj())
        self.assertFalse(result["promoted"])
        # cleanup always called even on exception
        mock_deployer.destroy_preview_env.assert_called_once_with(env)

    def test_disabled_by_default(self):
        result = preview_promote.run_preview_promote("s", {}, {"vercel_project": "web"})
        self.assertFalse(result["promoted"])
        self.assertIn("disabled", result.get("error", ""))


if __name__ == "__main__":
    unittest.main()
