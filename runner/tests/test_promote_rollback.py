#!/usr/bin/env python3
"""Tests for promote_rollback.py — promote reads metadata, rollback restores."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmpdir = tempfile.mkdtemp()
os.environ["CLAUDE_ORCH_HOME"] = _tmpdir

import promote_rollback


class TestPromoteRollback(unittest.TestCase):

    def setUp(self):
        for f in [promote_rollback.PROD_STATE_FILE, promote_rollback.PROMOTE_LOG]:
            if os.path.isfile(f):
                os.remove(f)

    def test_promote(self):
        meta = {
            "task_id": "t1", "git_sha": "abc123",
            "db_ref": "preview_t1", "env_url": "http://preview/t1",
            "status": "deployed",
        }
        result = promote_rollback.promote_to_prod(meta)
        self.assertEqual(result["status"], "promoted")
        self.assertIsNone(result["previous_deployment"])
        self.assertEqual(result["promoted_deployment"]["git_sha"], "abc123")

    def test_promote_swaps_safely(self):
        m1 = {"task_id": "t1", "git_sha": "sha1", "status": "deployed"}
        m2 = {"task_id": "t2", "git_sha": "sha2", "status": "deployed"}
        promote_rollback.promote_to_prod(m1)
        result = promote_rollback.promote_to_prod(m2)
        self.assertEqual(result["previous_deployment"]["git_sha"], "sha1")
        self.assertEqual(result["promoted_deployment"]["git_sha"], "sha2")

    def test_rollback_restores(self):
        m1 = {"task_id": "t1", "git_sha": "sha1", "status": "deployed"}
        m2 = {"task_id": "t2", "git_sha": "sha2", "status": "deployed"}
        promote_rollback.promote_to_prod(m1)
        promote_rollback.promote_to_prod(m2)
        result = promote_rollback.rollback()
        self.assertEqual(result["status"], "rolled_back")
        self.assertEqual(result["rolled_back_to"]["git_sha"], "sha1")

    def test_rollback_no_history(self):
        result = promote_rollback.rollback()
        self.assertEqual(result["status"], "failed")

    def test_prod_never_points_to_preview_before_promotion(self):
        state = promote_rollback.get_prod_state()
        self.assertIsNone(state["current_deployment"])

    def test_promote_none(self):
        result = promote_rollback.promote_to_prod(None)
        self.assertEqual(result["status"], "failed")

    def test_get_prod_state(self):
        promote_rollback.promote_to_prod({"task_id": "x", "git_sha": "y", "status": "deployed"})
        state = promote_rollback.get_prod_state()
        self.assertEqual(state["current_deployment"]["task_id"], "x")


if __name__ == "__main__":
    unittest.main()
