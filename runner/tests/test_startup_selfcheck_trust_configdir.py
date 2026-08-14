#!/usr/bin/env python3
"""Regression tests for the workspace-trust root cause behind missing agent branches.

Claude Code reads $CLAUDE_CONFIG_DIR/.claude.json. The selfcheck used to hardcode
~/.claude/.claude.json, so every account_pool login profile (e.g. ~/.claude-heretomorrow)
stayed untrusted: Claude Code ignored .claude/settings.local.json, printed
"this workspace has not been trusted", and stalled before creating agent/<slug>.

These tests also pin the security posture of the fix: trust acceptance writes exactly
one boolean and never a credential or a permissions.allow list.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import startup_selfcheck


class DefaultCfgPathTest(unittest.TestCase):

    def test_honours_claude_config_dir_env(self):
        with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": "/tmp/.claude-heretomorrow"}):
            self.assertEqual(
                startup_selfcheck._default_claude_cfg(),
                "/tmp/.claude-heretomorrow/.claude.json",
            )

    def test_falls_back_to_home_claude(self):
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(
                startup_selfcheck._default_claude_cfg(),
                os.path.join(os.path.expanduser("~/.claude"), ".claude.json"),
            )


class TrustPathTest(unittest.TestCase):

    def test_includes_worktree_root(self):
        paths = startup_selfcheck._trust_repo_paths("/repo/proj")
        self.assertIn("/repo/proj", paths)
        self.assertIn("/repo/proj-wt", paths)

    def test_cfg_paths_skip_unprovisioned_dirs(self):
        with tempfile.TemporaryDirectory() as d:
            missing = os.path.join(d, "nope", ".claude.json")
            with patch.object(startup_selfcheck, "_CLAUDE_CFG", missing), \
                 patch.object(startup_selfcheck, "_default_claude_cfg", lambda: missing), \
                 patch.object(startup_selfcheck, "_account_cfg_paths", lambda: []):
                self.assertEqual(startup_selfcheck._trust_cfg_paths(), [])

    def test_cfg_paths_dedupe(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = os.path.join(d, ".claude.json")
            with patch.object(startup_selfcheck, "_CLAUDE_CFG", cfg), \
                 patch.object(startup_selfcheck, "_default_claude_cfg", lambda: cfg), \
                 patch.object(startup_selfcheck, "_account_cfg_paths", lambda: [cfg]):
                self.assertEqual(startup_selfcheck._trust_cfg_paths(), [cfg])


class AcceptTrustEverywhereTest(unittest.TestCase):

    def test_trusts_repo_and_worktree_in_every_profile(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as alt:
            main_cfg = os.path.join(home, ".claude.json")
            alt_cfg = os.path.join(alt, ".claude.json")
            with patch.object(startup_selfcheck, "_CLAUDE_CFG", main_cfg), \
                 patch.object(startup_selfcheck, "_default_claude_cfg", lambda: main_cfg), \
                 patch.object(startup_selfcheck, "_account_cfg_paths", lambda: [alt_cfg]):
                changed = startup_selfcheck.accept_trust_everywhere("/repo/proj")
            self.assertEqual(changed, 4)  # 2 config files x (repo + worktree root)
            for path in (main_cfg, alt_cfg):
                data = json.load(open(path))
                self.assertTrue(data["projects"]["/repo/proj"]["hasTrustDialogAccepted"])
                self.assertTrue(data["projects"]["/repo/proj-wt"]["hasTrustDialogAccepted"])

    def test_idempotent_second_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as home:
            cfg = os.path.join(home, ".claude.json")
            with patch.object(startup_selfcheck, "_CLAUDE_CFG", cfg), \
                 patch.object(startup_selfcheck, "_default_claude_cfg", lambda: cfg), \
                 patch.object(startup_selfcheck, "_account_cfg_paths", lambda: []):
                first = startup_selfcheck.accept_trust_everywhere("/repo/proj")
                second = startup_selfcheck.accept_trust_everywhere("/repo/proj")
            self.assertEqual(first, 2)
            self.assertEqual(second, 0)

    def test_account_cfg_paths_failsoft_without_account_pool(self):
        with patch.dict(sys.modules, {"account_pool": None}):
            self.assertEqual(startup_selfcheck._account_cfg_paths(), [])


class TrustWritesNoSecretsTest(unittest.TestCase):
    """The unsafe path that quarantined the original task must stay closed."""

    def test_only_trust_flag_is_written(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = os.path.join(d, ".claude.json")
            startup_selfcheck._accept_trust("/repo/proj", cfg_path=cfg)
            entry = json.load(open(cfg))["projects"]["/repo/proj"]
            self.assertEqual(entry, {"hasTrustDialogAccepted": True})

    def test_existing_secrets_are_not_duplicated_or_touched(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = os.path.join(d, ".claude.json")
            initial = {"oauthAccount": {"emailAddress": "kale@heretomorrow.us"},
                       "projects": {"/other": {"hasTrustDialogAccepted": True}}}
            with open(cfg, "w") as f:
                json.dump(initial, f)
            startup_selfcheck._accept_trust("/repo/proj", cfg_path=cfg)
            data = json.load(open(cfg))
            self.assertEqual(data["oauthAccount"], initial["oauthAccount"])
            self.assertTrue(data["projects"]["/other"]["hasTrustDialogAccepted"])
            self.assertEqual(data["projects"]["/repo/proj"], {"hasTrustDialogAccepted": True})

    def test_no_permissions_allow_list_is_ever_written(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = os.path.join(d, ".claude.json")
            startup_selfcheck._accept_trust("/repo/proj", cfg_path=cfg)
            raw = open(cfg).read()
            self.assertNotIn("permissions", raw)
            self.assertNotIn("allow", raw)
            self.assertNotIn("ANTHROPIC_API_KEY", raw)

    def test_corrupt_config_is_not_clobbered_with_a_credential_stub(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = os.path.join(d, ".claude.json")
            with open(cfg, "w") as f:
                f.write("not json {{{")
            startup_selfcheck._accept_trust("/repo/proj", cfg_path=cfg)
            data = json.load(open(cfg))
            self.assertEqual(list(data.keys()), ["projects"])


if __name__ == "__main__":
    unittest.main()
