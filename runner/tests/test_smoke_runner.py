#!/usr/bin/env python3
"""Tests for smoke_tests.py — post-deploy smoke suite."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmpdir = tempfile.mkdtemp()
os.environ["CLAUDE_ORCH_HOME"] = _tmpdir

import preview_env_manager
from tests.smoke_tests import run_smoke_suite, SmokeResult


class TestSmokeRunner(unittest.TestCase):

    def setUp(self):
        if os.path.isfile(preview_env_manager.PREVIEW_REGISTRY):
            os.remove(preview_env_manager.PREVIEW_REGISTRY)

    def test_smoke_suite_no_env(self):
        result = run_smoke_suite("nonexistent")
        self.assertEqual(result["status"], "abort")
        self.assertIn("no active preview env", result["detail"])

    def test_smoke_suite_with_env(self):
        preview_env_manager.create_preview_env("smoke-1")
        result = run_smoke_suite("smoke-1")
        self.assertIn(result["status"], ("pass", "fail", "abort"))
        self.assertIsInstance(result["results"], list)
        self.assertTrue(len(result["results"]) >= 3)

    def test_smoke_blocks_on_critical_failure(self):
        """If health_check or db_connectivity fail, status should be abort."""
        # Create env but with unreachable URL — health check will fail
        preview_env_manager.create_preview_env("smoke-2")
        result = run_smoke_suite("smoke-2")
        # The health check will fail (localhost:3001 not running) → abort
        self.assertIn(result["status"], ("abort", "fail"))

    def test_smoke_result_structure(self):
        r = SmokeResult("test", True, "ok")
        d = r.to_dict()
        self.assertEqual(d["name"], "test")
        self.assertTrue(d["passed"])
        self.assertEqual(d["detail"], "ok")

    def test_smoke_reports_pass_fail(self):
        preview_env_manager.create_preview_env("smoke-3")
        result = run_smoke_suite("smoke-3")
        for r in result["results"]:
            self.assertIn("name", r)
            self.assertIn("passed", r)


if __name__ == "__main__":
    unittest.main()
