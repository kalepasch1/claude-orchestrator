#!/usr/bin/env python3
"""Tests for preview_deploy.py — mock merge event triggers preview deploy."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmpdir = tempfile.mkdtemp()
os.environ["CLAUDE_ORCH_HOME"] = _tmpdir

import preview_deploy
import preview_env_manager


class TestMergeToPreview(unittest.TestCase):

    def setUp(self):
        for f in [preview_deploy.DEPLOY_LOG, preview_env_manager.PREVIEW_REGISTRY]:
            if os.path.isfile(f):
                os.remove(f)

    def test_trigger_preview_deploy(self):
        meta = preview_deploy.trigger_preview_deploy("merge-1", repo_path="/tmp", slug="test-slug")
        self.assertEqual(meta["status"], "deployed")
        self.assertEqual(meta["task_id"], "merge-1")
        self.assertEqual(meta["slug"], "test-slug")
        self.assertIn("env_url", meta)
        self.assertIn("git_sha", meta)
        self.assertIn("deploy_started_at", meta)
        self.assertIn("deploy_completed_at", meta)

    def test_deployment_metadata_stored(self):
        preview_deploy.trigger_preview_deploy("merge-2", repo_path="/tmp")
        entries = preview_deploy.list_deployments()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["task_id"], "merge-2")

    def test_get_deployment(self):
        preview_deploy.trigger_preview_deploy("merge-3", repo_path="/tmp")
        dep = preview_deploy.get_deployment("merge-3")
        self.assertIsNotNone(dep)
        self.assertEqual(dep["status"], "deployed")

    def test_post_merge_hook(self):
        meta = preview_deploy.post_merge_hook("merge-4", "/tmp", slug="hook-test")
        self.assertEqual(meta["status"], "deployed")

    def test_does_not_affect_prod(self):
        """Preview deploy should not touch prod state."""
        prod_state_file = os.path.join(_tmpdir, "prod-state.json")
        preview_deploy.trigger_preview_deploy("merge-5", repo_path="/tmp")
        self.assertFalse(os.path.isfile(prod_state_file))


if __name__ == "__main__":
    unittest.main()
