import unittest
import importlib.util
import pathlib
import sys
from unittest.mock import patch

RUNNER_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNNER_DIR))
SPEC = importlib.util.spec_from_file_location("business_os_worker", RUNNER_DIR / "business_os_worker.py")
worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)


class BusinessOsWorkerTests(unittest.TestCase):
    def test_success_is_claimed_once_and_sent_to_review(self):
        job = {"id": "job-1", "action_run_id": "run-1", "capability": "image", "brief": "launch image", "selected_provider": "bfl", "provider_candidates": ["bfl"], "controls": {}, "attempts": 1, "provenance": {"source": "business_os"}}
        with patch.object(worker.db, "select", return_value=[]), patch.object(worker.db, "rpc", return_value=[job]) as claim, patch.object(worker.db, "update") as update, patch.object(worker.db, "insert"), patch.object(worker.creative_dispatch, "available", return_value=["bfl"]), patch.object(worker.creative_dispatch, "generate_image", return_value={"status": "ok", "provider": "bfl", "output_url": "https://asset.test/a.png", "cost_usd": .03}):
            result = worker.run_once("test-worker")
        claim.assert_called_once_with("claim_creative_production_job", {"p_worker": "test-worker"})
        self.assertTrue(result["review_required"])
        self.assertTrue(any(call.args[2].get("status") == "review" for call in update.call_args_list))
        self.assertTrue(any(call.args[2].get("state") == "completed" for call in update.call_args_list))

    def test_missing_runtime_credential_fails_safe(self):
        job = {"id": "job-2", "action_run_id": "run-2", "capability": "motion", "brief": "launch video", "selected_provider": "runway", "provider_candidates": ["runway"], "attempts": 1}
        with patch.object(worker.db, "select", return_value=[]), patch.object(worker.db, "rpc", return_value=[job]), patch.object(worker.db, "update") as update, patch.object(worker.db, "insert"), patch.object(worker.creative_dispatch, "available", return_value=[]), patch.object(worker.creative_dispatch, "generate_video") as generate:
            result = worker.run_once("test-worker")
        generate.assert_not_called()
        self.assertEqual(result["status"], "connector_required")
        self.assertTrue(any(call.args[2].get("status") == "connector_required" for call in update.call_args_list))

    def test_budget_cap_is_delayed_not_failed(self):
        job = {"id": "job-3", "capability": "3d", "brief": "model", "selected_provider": "meshy", "provider_candidates": ["meshy"], "controls": {}, "attempts": 1}
        with patch.object(worker.db, "select", return_value=[]), patch.object(worker.db, "rpc", return_value=[job]), patch.object(worker.db, "update") as update, patch.object(worker.db, "insert"), patch.object(worker.creative_dispatch, "available", return_value=["meshy"]), patch.object(worker.creative_dispatch, "generate_3d", return_value={"status": "error", "provider": "meshy", "errors": ["creative hourly cap reached"]}):
            worker.run_once("test-worker")
        patch_value = update.call_args_list[0].args[2]
        self.assertEqual(patch_value["status"], "ready")
        self.assertIsNotNone(patch_value["next_attempt_at"])

    def test_schema_rollout_gap_does_not_crash_scheduler(self):
        with patch.object(worker.db, "select", return_value=[]), patch.object(worker.db, "rpc", side_effect=RuntimeError("function not found")), patch.object(worker.creative_dispatch, "available", return_value=[]):
            result = worker.run_once("test-worker")
        self.assertEqual(result["status"], "control_plane_unavailable")


if __name__ == "__main__":
    unittest.main()
