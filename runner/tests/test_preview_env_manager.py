#!/usr/bin/env python3
"""Unit tests for preview_env_manager.py — create/teardown/get, env var isolation."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Isolate registry to temp dir
_tmpdir = tempfile.mkdtemp()
os.environ["CLAUDE_ORCH_HOME"] = _tmpdir

import preview_env_manager


class TestPreviewEnvManager(unittest.TestCase):

    def setUp(self):
        # Clear registry between tests
        if os.path.isfile(preview_env_manager.PREVIEW_REGISTRY):
            os.remove(preview_env_manager.PREVIEW_REGISTRY)

    def test_create_preview_env(self):
        env = preview_env_manager.create_preview_env("task-100")
        self.assertEqual(env["task_id"], "task-100")
        self.assertEqual(env["status"], "active")
        self.assertIn("url", env)
        self.assertIn("env_vars", env)
        self.assertIn("db_ref", env)

    def test_create_returns_existing(self):
        env1 = preview_env_manager.create_preview_env("task-200")
        env2 = preview_env_manager.create_preview_env("task-200")
        self.assertEqual(env1["created_at"], env2["created_at"])

    def test_env_vars_isolate_db(self):
        env1 = preview_env_manager.create_preview_env("task-a")
        env2 = preview_env_manager.create_preview_env("task-b")
        self.assertNotEqual(env1["env_vars"]["PREVIEW_DB_REF"],
                           env2["env_vars"]["PREVIEW_DB_REF"])
        self.assertEqual(env1["env_vars"]["PREVIEW_ISOLATED"], "true")

    def test_get_preview_env(self):
        preview_env_manager.create_preview_env("task-300")
        env = preview_env_manager.get_preview_env("task-300")
        self.assertIsNotNone(env)
        self.assertEqual(env["task_id"], "task-300")

    def test_get_nonexistent(self):
        self.assertIsNone(preview_env_manager.get_preview_env("nope"))

    def test_teardown(self):
        preview_env_manager.create_preview_env("task-400")
        result = preview_env_manager.teardown_preview_env("task-400")
        self.assertTrue(result)
        self.assertIsNone(preview_env_manager.get_preview_env("task-400"))

    def test_teardown_nonexistent(self):
        self.assertTrue(preview_env_manager.teardown_preview_env("nope"))

    def test_create_none_task_id(self):
        result = preview_env_manager.create_preview_env(None)
        self.assertIn("error", result)

    def test_list_active(self):
        preview_env_manager.create_preview_env("t1")
        preview_env_manager.create_preview_env("t2")
        preview_env_manager.teardown_preview_env("t1")
        active = preview_env_manager.list_active_envs()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["task_id"], "t2")


if __name__ == "__main__":
    unittest.main()
