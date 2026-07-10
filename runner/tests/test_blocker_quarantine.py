import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import blocker_quarantine
import agentic_repair


class BlockerQuarantineTest(unittest.TestCase):

    def test_legal_blocker_creates_safe_local_rework_and_parks_original(self):
        task = {
            "id": "t1",
            "slug": "tax-return-optimization",
            "project_id": "p1",
            "state": "BLOCKED",
            "kind": "build",
            "prompt": "Build tax return optimization automation.",
            "note": "legal review required: tax/CPA workflow risk",
            "base_branch": "main",
        }
        fake_db = MagicMock()
        fake_db.select.side_effect = [[], [], [task], []]

        with patch.object(blocker_quarantine, "db", fake_db), \
             patch.dict(os.environ, {"ORCH_QUARANTINE_CODER": "ollama"}, clear=False):
            out = blocker_quarantine.run(limit=1)

        self.assertEqual(out["created"], 1)
        inserted = fake_db.insert.call_args_list[0].args[1]
        self.assertEqual(inserted["state"], "QUEUED")
        self.assertEqual(inserted["force_coder"], "ollama")
        self.assertEqual(inserted["sensitivity"], "crown_jewel")
        self.assertIn("non-regulated safe variant", inserted["prompt"])
        self.assertIn("licensed-professional or owner approval gate", inserted["prompt"])
        patch_row = fake_db.update.call_args.args[2]
        self.assertEqual(patch_row["state"], "QUARANTINED")
        self.assertIn("replacement queued", patch_row["note"])

    def test_secret_blocker_preserves_behavior_without_committing_credentials(self):
        task = {
            "id": "t2",
            "slug": "ext-passport-bureau-api",
            "project_id": "p1",
            "state": "BLOCKED",
            "kind": "build",
            "prompt": "Integrate passport bureau API.",
            "note": "CRON_SECRET exposure in committed config",
            "base_branch": "main",
        }
        fake_db = MagicMock()
        fake_db.select.side_effect = [[], [], [task], []]

        with patch.object(blocker_quarantine, "db", fake_db):
            out = blocker_quarantine.run(limit=1)

        self.assertEqual(out["categories"], {"secret": 1})
        inserted = fake_db.insert.call_args_list[0].args[1]
        self.assertIn("Do not commit secrets", inserted["prompt"])
        self.assertIn("environment-variable placeholders", inserted["prompt"])
        self.assertEqual(inserted["force_coder"], "ollama")

    def test_existing_technical_rework_repairs_original(self):
        task = {
            "id": "t3",
            "slug": "qafix-tomorrow-07062319",
            "project_id": "p1",
            "state": "TESTFAIL",
            "kind": "bugfix",
            "prompt": "Fix QA failure.",
            "note": "QA failed",
            "base_branch": "main",
        }
        fake_db = MagicMock()
        fake_db.select.side_effect = [[], [], [task], [{"id": "already", "state": "QUEUED"}]]

        with patch.object(blocker_quarantine, "db", fake_db):
            out = blocker_quarantine.run(limit=1)

        self.assertEqual(out["created"], 0)
        self.assertEqual(out["parked"], 0)
        self.assertEqual(out["repaired_original"], 1)
        self.assertEqual(fake_db.insert.call_count, 1)  # controls summary only
        self.assertEqual(fake_db.update.call_args.args[2]["state"], "QUEUED")
        self.assertIn(agentic_repair.MARKER, fake_db.update.call_args.args[2]["prompt"])

    def test_test_failure_is_not_secret_just_because_prompt_mentions_secret_app(self):
        task = {
            "id": "t4",
            "slug": "qafix-tomorrow-07062319",
            "state": "TESTFAIL",
            "kind": "bugfix",
            "prompt": "Fix QA for santas-secret-workshop release train.",
            "note": "train: tests failed on rebased agent/qafix-tomorrow",
            "log_tail": "44 failed | 245 passed",
        }

        self.assertEqual(blocker_quarantine.classify(task), "testfail")

    def test_slack_token_in_log_tail_classified_as_secret(self):
        """A task whose log_tail contains a Slack bot token hint must be classified 'secret'."""
        task = {
            "id": "t-slack",
            "slug": "cont-801b8665",
            "state": "BLOCKED",
            "kind": "build",
            "prompt": "Configure Slack integration for approvals.",
            "note": "groomed: duplicate queued slug",
            "log_tail": "Await user-supplied Slack credentials (Bot Token xoxb-…, Signing Secret)",
        }
        self.assertEqual(blocker_quarantine.classify(task), "secret")

    def test_slack_secret_replacement_uses_env_var_placeholders(self):
        """Replacement prompt for a Slack-token blocker must direct to env-var config, not commit secrets."""
        task = {
            "id": "t-slack2",
            "slug": "cont-801b8665",
            "project_id": "p1",
            "state": "BLOCKED",
            "kind": "build",
            "prompt": "Configure Slack integration for approvals.",
            "note": "groomed: duplicate queued slug",
            "log_tail": "Signing Secret token credential exposure",
            "base_branch": "main",
        }
        fake_db = MagicMock()
        fake_db.select.side_effect = [[], [], [task], []]

        with patch.object(blocker_quarantine, "db", fake_db):
            out = blocker_quarantine.run(limit=1)

        self.assertEqual(out["categories"].get("secret"), 1)
        inserted = fake_db.insert.call_args_list[0].args[1]
        self.assertIn("environment-variable placeholders", inserted["prompt"])
        self.assertNotIn("xoxb-", inserted["prompt"])

    def test_slack_interactions_signing_secret_is_fail_secure(self):
        """slack-interactions edge function must reject requests when SLACK_SIGNING_SECRET is unset."""
        import os, pathlib
        ts_path = pathlib.Path(__file__).parent.parent.parent / "supabase" / "functions" / "slack-interactions" / "index.ts"
        src = ts_path.read_text()
        self.assertNotIn("!SIGNING) return true", src,
                         "fail-open fallback must not exist: configure SLACK_SIGNING_SECRET instead")
        self.assertIn("!SIGNING) return false", src,
                      "verify() must fail-secure when signing secret is unset")
        self.assertIn("503", src,
                      "handler must return 503 when SLACK_SIGNING_SECRET is not configured")

    def test_slack_notify_bot_token_is_fail_secure(self):
        """slack-notify edge function must return 503 when SLACK_BOT_TOKEN is unset."""
        import pathlib
        ts_path = pathlib.Path(__file__).parent.parent.parent / "supabase" / "functions" / "slack-notify" / "index.ts"
        src = ts_path.read_text()
        self.assertNotIn('Bearer ${Deno.env.get("SLACK_BOT_TOKEN")}', src,
                         "must not read token inline — use a module-level constant with a guard")
        self.assertIn("503", src,
                      "handler must return 503 when SLACK_BOT_TOKEN is not configured")
        self.assertNotIn("Bearer undefined", src,
                         "must not silently send 'Bearer undefined' when token is missing")

    def test_quarantine_wrapper_does_not_bias_repair_classification(self):
        task = {
            "id": "t5",
            "slug": "qafix-tomorrow-07062319",
            "state": "QUARANTINED",
            "kind": "bugfix",
            "prompt": "Fix QA for santas-secret-workshop release train.",
            "note": (
                "blocker-quarantine: quarantined as secret; replacement queued as x. "
                "Original blocker: train: tests failed on rebased agent/qafix-tomorrow"
            ),
            "log_tail": "44 failed | 245 passed",
        }

        self.assertEqual(blocker_quarantine.classify(task), "testfail")


if __name__ == "__main__":
    unittest.main()
