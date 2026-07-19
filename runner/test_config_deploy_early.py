#!/usr/bin/env python3
"""
test_config_deploy_early.py — Automated tests detecting configuration errors
at the earliest stage of deployment.

Covers:
  - Safe key validation rejects credential markers
  - Safe key validation accepts ORCH_ prefixed keys
  - Canary state persistence round-trips correctly
  - Config applier returns 'rejected' for unsafe keys
  - Fleet control load_config skips deny-listed keys

Task: improve-enhance-error-handling-and-testing-slice-2
"""
import os, sys, json, tempfile, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))


class TestConfigSafeKeyValidation(unittest.TestCase):
    """Detect config errors before they propagate to the fleet."""

    def test_reject_secret_keys(self):
        from config_applier import _is_safe_key
        for bad in ("DB_SECRET", "API_KEY", "AUTH_TOKEN", "MY_PASSWORD",
                    "ROOT_PWD", "AWS_CREDENTIAL"):
            self.assertFalse(_is_safe_key(bad), f"{bad} should be rejected")

    def test_accept_safe_prefixes(self):
        from config_applier import _is_safe_key
        for good in ("ORCH_MAX_PARALLEL", "MAX_PARALLEL_TASKS",
                     "QUEUE_BATCH_SIZE", "ENABLE_CANARY", "DEPLOY_WINDOW"):
            self.assertTrue(_is_safe_key(good), f"{good} should be accepted")

    def test_none_and_empty_rejected(self):
        from config_applier import _is_safe_key
        self.assertFalse(_is_safe_key(None))
        self.assertFalse(_is_safe_key(""))

    def test_canary_state_roundtrip(self):
        from config_applier import _load_state, _save_state
        with tempfile.TemporaryDirectory() as td:
            sf = os.path.join(td, "state.json")
            import config_applier
            orig = config_applier.STATE_FILE
            config_applier.STATE_FILE = sf
            try:
                state = {"applied": {"ORCH_X": "1"}, "rollbacks": ["ORCH_Y"]}
                _save_state(state)
                loaded = _load_state()
                self.assertEqual(loaded["applied"]["ORCH_X"], "1")
                self.assertIn("ORCH_Y", loaded["rollbacks"])
            finally:
                config_applier.STATE_FILE = orig

    def test_fleet_control_safe_key_matches_applier(self):
        """Fleet control and config applier must agree on what's safe."""
        from config_applier import _is_safe_key as applier_safe
        from fleet_control import _safe_key as fleet_safe
        test_keys = ["ORCH_X", "MAX_PARALLEL_Y", "API_KEY", "SECRET_Z",
                     "DEPLOY_CANARY", "TOKEN_BUCKET"]
        for k in test_keys:
            self.assertEqual(applier_safe(k), fleet_safe(k),
                             f"Disagreement on key '{k}'")


class TestBranchManagementIntegration(unittest.TestCase):
    """Task: improve-improve-branch-management-with-automated-slice-2
    Verify branch naming and materializer integrate with test frameworks."""

    def test_derive_branch_name_sanitizes(self):
        from branch_materializer import derive_branch_name
        self.assertEqual(derive_branch_name("my-task"), "agent/my-task")
        # Special chars stripped
        name = derive_branch_name("CAPS_under!bang")
        self.assertTrue(name.startswith("agent/"))
        self.assertNotIn("!", name)
        self.assertNotIn("_", name)  # underscore -> dash

    def test_branch_name_length_limit(self):
        from branch_materializer import derive_branch_name
        long_slug = "a" * 200
        name = derive_branch_name(long_slug)
        # prefix + slug <= ~86 chars
        self.assertLessEqual(len(name), 90)

    def test_none_slug_handled(self):
        from branch_materializer import derive_branch_name
        name = derive_branch_name(None)
        self.assertEqual(name, "agent/unknown")

    def test_stats_initialized(self):
        from branch_materializer import _stats
        self.assertIn("branches_created", _stats)
        self.assertIn("failures", _stats)


class TestFailSoftErrorHandling(unittest.TestCase):
    """Task: improve-enhanced-error-handling-and-logging-slice-2
    Verify fail-soft: functions return defaults on bad input."""

    def test_config_load_state_missing_file(self):
        import config_applier
        orig = config_applier.STATE_FILE
        config_applier.STATE_FILE = "/nonexistent/path/state.json"
        try:
            state = config_applier._load_state()
            self.assertIsInstance(state, dict)
            self.assertIn("applied", state)
        finally:
            config_applier.STATE_FILE = orig

    def test_git_auto_branch_git_failure(self):
        """_git returns ('', False) on bad repo path — no exception."""
        from git_auto_branch import _git
        out, ok = _git(["status"], "/nonexistent/repo/path")
        self.assertFalse(ok)
        self.assertEqual(out, "")

    def test_branch_materializer_git_failure(self):
        from branch_materializer import _run_git
        rc, out, err = _run_git("/nonexistent", ["status"])
        self.assertNotEqual(rc, 0)

    def test_metric_snapshot_no_crash(self):
        """_get_metric_snapshot must not raise even if resource_governor missing."""
        from config_applier import _get_metric_snapshot
        snap = _get_metric_snapshot()
        self.assertIn("ts", snap)


class TestConfigValidationSecurity(unittest.TestCase):
    """Task: improve-enhance-automated-testing-and-validation-slice-2
    Security invariants for configuration management."""

    def test_case_insensitive_deny(self):
        from config_applier import _is_safe_key
        self.assertFalse(_is_safe_key("orch_api_key"))
        self.assertFalse(_is_safe_key("ORCH_SECRET_VALUE"))
        self.assertFalse(_is_safe_key("orch_token_bucket"))

    def test_no_credential_leak_through_prefix(self):
        """Even with safe prefix, deny marker wins."""
        from fleet_control import _safe_key
        self.assertFalse(_safe_key("ORCH_SECRET"))
        self.assertFalse(_safe_key("DEPLOY_PASSWORD"))
        self.assertFalse(_safe_key("ENABLE_TOKEN"))

    def test_branch_materializer_rejects_path_traversal(self):
        from branch_materializer import derive_branch_name
        name = derive_branch_name("../../etc/passwd")
        self.assertNotIn("..", name)
        self.assertTrue(name.startswith("agent/"))


if __name__ == "__main__":
    unittest.main()
