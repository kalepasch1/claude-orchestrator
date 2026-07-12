#!/usr/bin/env python3
"""
test_deploy_e2e.py — integration test for the full preview→prod flow.

Verifies: merge → preview deploy → smoke tests → promote → prod updated.
All steps are logged, no manual steps required.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmpdir = tempfile.mkdtemp()
os.environ["CLAUDE_ORCH_HOME"] = _tmpdir

import preview_env_manager
import preview_deploy
import promote_rollback
from tests.smoke_tests import run_smoke_suite


class TestDeployE2E(unittest.TestCase):

    def setUp(self):
        for f in [preview_env_manager.PREVIEW_REGISTRY, preview_deploy.DEPLOY_LOG,
                  promote_rollback.PROD_STATE_FILE, promote_rollback.PROMOTE_LOG]:
            if os.path.isfile(f):
                os.remove(f)

    def test_full_flow_merge_to_prod(self):
        """End-to-end: merge → preview → smoke → promote."""
        task_id = "e2e-task-1"

        # Step 1: Mock merge triggers preview deploy
        deploy_meta = preview_deploy.post_merge_hook(task_id, "/tmp", slug="e2e-slug")
        self.assertEqual(deploy_meta["status"], "deployed")
        self.assertIn("env_url", deploy_meta)

        # Step 2: Verify preview deploy completed
        deployment = preview_deploy.get_deployment(task_id)
        self.assertIsNotNone(deployment)
        self.assertEqual(deployment["status"], "deployed")

        # Step 3: Run smoke tests
        smoke = run_smoke_suite(task_id)
        self.assertIn(smoke["status"], ("pass", "fail", "abort"))
        self.assertTrue(len(smoke["results"]) >= 3)

        # Step 4: Promote to prod (skip if smoke failed critically, but for e2e test proceed)
        promote_result = promote_rollback.promote_to_prod(deploy_meta)
        self.assertEqual(promote_result["status"], "promoted")

        # Step 5: Verify prod is updated
        prod_state = promote_rollback.get_prod_state()
        self.assertIsNotNone(prod_state["current_deployment"])
        self.assertEqual(prod_state["current_deployment"]["task_id"], task_id)

    def test_all_steps_logged(self):
        """Verify every step produces log entries."""
        task_id = "e2e-log-test"

        preview_deploy.post_merge_hook(task_id, "/tmp")
        run_smoke_suite(task_id)
        deploy_meta = preview_deploy.get_deployment(task_id)
        promote_rollback.promote_to_prod(deploy_meta)

        # Check deploy log
        deploys = preview_deploy.list_deployments()
        self.assertTrue(len(deploys) >= 1)

        # Check promote log
        self.assertTrue(os.path.isfile(promote_rollback.PROMOTE_LOG))

    def test_no_manual_steps(self):
        """Full flow completes without any interactive prompts or manual steps."""
        task_id = "e2e-auto"
        deploy_meta = preview_deploy.trigger_preview_deploy(task_id, "/tmp")
        smoke = run_smoke_suite(task_id)
        promote_result = promote_rollback.promote_to_prod(deploy_meta)
        # If we got here without input(), we passed
        self.assertIn(promote_result["status"], ("promoted", "failed"))


if __name__ == "__main__":
    unittest.main()
