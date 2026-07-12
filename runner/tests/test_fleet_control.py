import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fleet_control


class FleetControlTest(unittest.TestCase):

    def test_safe_key_rejects_credentials(self):
        self.assertTrue(fleet_control._safe_key("ORCH_AUTO_PULL"))
        self.assertTrue(fleet_control._safe_key("MAX_PARALLEL"))
        self.assertFalse(fleet_control._safe_key("OPENAI_API_KEY"))
        self.assertFalse(fleet_control._safe_key("ORCH_SECRET_TOKEN"))

    def test_safe_key_accepts_all_safe_prefixes(self):
        safe_examples = [
            "ORCH_CANARY_ONLY_OLLAMA_MODELS", "ORCH_DEPRIORITIZE_CHURN",
            "MAX_PARALLEL_CEILING", "PER_TASK_GB", "RAM_FLOOR_GB", "RAM_LIMIT",
            "RELEASE_GATE", "QUEUE_DEPTH", "CONT_TIMEOUT", "JANITOR_INTERVAL",
            "REMEDIATION_CAP", "DEFAULT_TEST_CMD", "TASK_TIMEOUT_SECONDS",
            "ENABLE_SPECULATIVE", "SESSION_TTL", "ACCOUNT_COOLDOWN_SECONDS",
            "MERGE_STRATEGY", "DEPLOY_WINDOW", "INTEGRATE_KPI", "COST_CEILING",
        ]
        for k in safe_examples:
            self.assertTrue(fleet_control._safe_key(k), f"expected safe: {k}")

    def test_safe_key_rejects_all_deny_markers(self):
        deny_cases = [
            "ORCH_API_KEY", "ORCH_SECRET", "ORCH_TOKEN_REFRESH",
            "ORCH_PASSWORD_HASH", "ORCH_PWD_RESET", "ORCH_CREDENTIAL_STORE",
            "MAX_PARALLEL_KEY_ROTATION", "app_credential_name",
            "DB_PASSWORD", "REDIS_TOKEN", "AWS_SECRET_ACCESS_KEY",
        ]
        for k in deny_cases:
            self.assertFalse(fleet_control._safe_key(k), f"expected rejected: {k}")

    def test_safe_key_rejects_unknown_prefixes(self):
        unknown = ["HOME", "PATH", "USER", "SHELL", "MY_CUSTOM_VAR", "DB_HOST"]
        for k in unknown:
            self.assertFalse(fleet_control._safe_key(k), f"expected rejected: {k}")

    def test_safe_key_case_insensitive_deny(self):
        self.assertFalse(fleet_control._safe_key("ORCH_api_key"))
        self.assertFalse(fleet_control._safe_key("orch_Secret_token"))

    def test_safe_key_case_insensitive_prefix(self):
        self.assertTrue(fleet_control._safe_key("orch_auto_pull"))
        self.assertTrue(fleet_control._safe_key("max_parallel"))

    def test_all_target_done_when_expected_hosts_ack(self):
        fake_db = MagicMock()
        fake_db.select.side_effect = [
            [{
                "id": "ctrl-1",
                "target": "all",
                "action": "reload_config",
                "handled_by": ["mac1"],
                "params": {"expected_hosts": ["mac1", "mac2"]},
            }],
            [],
        ]

        with patch.object(fleet_control, "db", fake_db), patch.object(fleet_control, "HOST", "mac2"):
            self.assertEqual(fleet_control.process_controls(), 1)

        update_patch = fake_db.update.call_args.args[2]
        self.assertEqual(update_patch["handled_by"], ["mac1", "mac2"])
        self.assertTrue(update_patch["done"])

    def test_all_target_without_expected_hosts_stays_open_for_other_machines(self):
        fake_db = MagicMock()
        fake_db.select.side_effect = [
            [{
                "id": "ctrl-1",
                "target": "all",
                "action": "reload_config",
                "handled_by": [],
                "params": {},
            }],
            [],
        ]

        with patch.object(fleet_control, "db", fake_db), patch.object(fleet_control, "HOST", "mac2"):
            self.assertEqual(fleet_control.process_controls(), 1)

        update_patch = fake_db.update.call_args.args[2]
        self.assertEqual(update_patch["handled_by"], ["mac2"])
        self.assertFalse(update_patch["done"])

    def test_pause_action_sets_host_scoped_kill_switch_and_acks(self):
        fake_db = MagicMock()
        fake_db.select.return_value = [{
            "id": "ctrl-p",
            "target": "Mac-2.local",
            "action": "pause",
            "handled_by": [],
            "params": {"reason": "cost spike"},
        }]
        fake_ks = MagicMock()

        with patch.object(fleet_control, "db", fake_db), \
             patch.object(fleet_control, "kill_switch", fake_ks), \
             patch.object(fleet_control, "HOST", "Mac-2.local"):
            self.assertEqual(fleet_control.process_controls(), 1)

        # soft-pauses THIS host only (not global), and does not restart/exit.
        fake_ks.pause.assert_called_once()
        kwargs = fake_ks.pause.call_args.kwargs
        self.assertEqual(kwargs.get("scope"), "host")
        self.assertEqual(kwargs.get("project"), "Mac-2.local")
        self.assertEqual(kwargs.get("reason"), "cost spike")
        # single-host target -> row closes immediately after this host acks.
        update_patch = fake_db.update.call_args.args[2]
        self.assertEqual(update_patch["handled_by"], ["Mac-2.local"])
        self.assertTrue(update_patch["done"])

    def test_resume_action_lifts_host_pause(self):
        fake_db = MagicMock()
        fake_db.select.return_value = [{
            "id": "ctrl-r",
            "target": "Mac-2.local",
            "action": "resume",
            "handled_by": [],
            "params": {},
        }]
        fake_ks = MagicMock()

        with patch.object(fleet_control, "db", fake_db), \
             patch.object(fleet_control, "kill_switch", fake_ks), \
             patch.object(fleet_control, "HOST", "Mac-2.local"):
            self.assertEqual(fleet_control.process_controls(), 1)

        fake_ks.resume.assert_called_once()
        self.assertEqual(fake_ks.resume.call_args.kwargs.get("scope"), "host")
        self.assertEqual(fake_ks.resume.call_args.kwargs.get("project"), "Mac-2.local")
        fake_ks.pause.assert_not_called()

    def test_dirty_worktree_ignores_untracked_files(self):
        # untracked files (git would print them under plain --porcelain) must NOT count as dirty,
        # or a single stray cache/log permanently blocks auto-pull. The guard must ask git to
        # exclude untracked, and an untracked-only tree reports clean.
        calls = {}

        def fake_git(*args, **kw):
            calls["args"] = args
            r = MagicMock()
            # with --untracked-files=no, git prints nothing for an untracked-only worktree
            r.stdout = "" if "--untracked-files=no" in args else "?? runner/stray.py\n"
            return r

        with patch.object(fleet_control, "_git", side_effect=fake_git):
            self.assertFalse(fleet_control._dirty_worktree())
        self.assertIn("--untracked-files=no", calls["args"])

    def test_dirty_worktree_still_flags_tracked_modifications(self):
        def fake_git(*args, **kw):
            r = MagicMock(); r.stdout = " M runner/runner.py\n"; return r  # tracked edit survives the flag
        with patch.object(fleet_control, "_git", side_effect=fake_git):
            self.assertTrue(fleet_control._dirty_worktree())


if __name__ == "__main__":
    unittest.main()
