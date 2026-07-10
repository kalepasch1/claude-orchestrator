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

    def test_project_name_containing_secret_is_not_misclassified(self):
        """Production bug: a real project literally named 'santas-secret-workshop' had its
        ordinary build/test failures misclassified as 'secret' leaks because the old classifier
        scanned the raw slug. The failure evidence here is a plain build error -- no secret
        involved -- so classification should follow the evidence, not the app's name."""
        task = {
            "id": "t6",
            "slug": "relfix-santas-secret-workshop-070318-fix-build",
            "state": "BLOCKED",
            "kind": "build",
            "prompt": "Fix the production build for santas-secret-workshop.",
            "note": "production build red: cannot find module 'expo-router'",
            "log_tail": "npm error cannot find module 'expo-router'",
        }
        self.assertEqual(blocker_quarantine.classify(task), "buildfail")

    def test_rework_prefix_does_not_self_reclassify_as_secret(self):
        """Production bug: once quarantined as 'secret', a task is renamed to
        'rework-secret-<original>'. If THAT replacement later fails for an unrelated reason (a
        plain rebase conflict here), the old classifier re-matched 'secret' in its own slug and
        respawned another nested rework-secret-rework-secret-... task -- observed up to 5 deep
        in production. The new failure evidence (a rebase conflict) has nothing to do with
        secrets, so classification should reflect that."""
        task = {
            "id": "t7",
            "slug": "rework-secret-canary-ollama-5-c55a0b3",
            "state": "CONFLICT",
            "kind": "build",
            "prompt": "Rework: preserve the useful behavior while removing the unsafe mechanism.",
            "note": "train: rebase conflict on agent/rework-secret-canary-ollama-5-c55a0b3 against master",
            "log_tail": "CONFLICT (content): Merge conflict in runner/agentic_coders.py",
        }
        self.assertNotEqual(blocker_quarantine.classify(task), "secret")

    def test_strip_rework_noise_removes_nested_prefixes(self):
        self.assertEqual(
            blocker_quarantine._strip_rework_noise("rework-secret-canary-ollama-5-c55a0b3"),
            "canary-ollama-5-c55a0b3",
        )
        self.assertEqual(
            blocker_quarantine._strip_rework_noise(
                "rework-legal-rework-legal-rework-legal-rework-legal-rework-legal-rework-0d98862"
            ),
            "0d98862",
        )
        self.assertEqual(blocker_quarantine._strip_rework_noise("relfix-tomorrow-x"), "relfix-tomorrow-x")
        self.assertEqual(blocker_quarantine._strip_rework_noise(""), "")
        self.assertEqual(blocker_quarantine._strip_rework_noise(None), "")

    def test_rework_depth_counts_nested_occurrences(self):
        self.assertEqual(blocker_quarantine._rework_depth("plain-feature"), 0)
        self.assertEqual(blocker_quarantine._rework_depth("rework-secret-x"), 1)
        self.assertEqual(
            blocker_quarantine._rework_depth("rework-legal-rework-legal-rework-legal-x"), 3
        )

    def test_domain_vocab_token_credential_mention_is_not_secret(self):
        """Production bug: beethoven's own subject matter is API token/credential POOL
        MANAGEMENT, so a totally unrelated failure whose log/prompt happens to mention
        "token" or "credential" (ordinary domain vocabulary, not a leak) was misclassified
        as 'secret'. Observed in production: 'groomed: duplicate queued slug' and 'agent run
        failed after 3 error-retries' both got quarantined as secret. Classification must
        require actual violation-indicating language (hardcoded/exposed/leaked/committed),
        not bare presence of the word."""
        task = {
            "id": "t9",
            "slug": "cont-801b8665",
            "state": "BLOCKED",
            "kind": "build",
            "prompt": "Harden the credential pool's acquire() singleton against races.",
            "note": "groomed: duplicate queued slug",
            "log_tail": "token pool acquire() returned stale credential; retrying",
        }
        self.assertEqual(blocker_quarantine.classify(task), "rework")

    def test_licensing_topic_mention_is_not_legal(self):
        """Same false-positive pattern as secret/token: a fleet that routes across many AI
        model providers legitimately discusses provider 'licensing' and 'compliance'
        constantly. Bare topical mentions must not trigger the legal-blocker classifier --
        only actual 'legal review required'/regulatory-blocker language should."""
        task = {
            "id": "t10",
            "slug": "provider-parallel-rate-aware-routing",
            "state": "BLOCKED",
            "kind": "build",
            "prompt": "Add per-provider rate limits based on each model's licensing terms and compliance tier.",
            "note": "groomed: duplicate queued slug",
            "log_tail": "",
        }
        self.assertEqual(blocker_quarantine.classify(task), "rework")

    def test_genuine_secret_leak_still_classified_correctly(self):
        """Guard against overcorrecting: an actual hardcoded-secret finding must still route
        to the secret rework path."""
        task = {
            "id": "t11",
            "slug": "intake-provider-key",
            "state": "BLOCKED",
            "kind": "build",
            "prompt": "Wire up the new provider API key.",
            "note": "gitleaks: hardcoded API key detected in server/utils/provider.ts",
            "log_tail": "",
        }
        self.assertEqual(blocker_quarantine.classify(task), "secret")

    def test_deep_rework_chain_escalates_to_human_instead_of_respawning(self):
        """Depth-cap safety net: even if a classifier edge case still produces a secret/legal/
        security category on an already-deeply-reworked task, the pipeline must stop respawning
        and put a human in the loop instead of growing the chain further."""
        task = {
            "id": "t8",
            "slug": "rework-legal-rework-legal-old-work-abc123",
            "project_id": "p1",
            "state": "BLOCKED",
            "kind": "build",
            "prompt": "x",
            "note": "legal review required: tax/CPA workflow risk",
        }
        fake_db = MagicMock()
        fake_db.select.side_effect = [[], [], [task], []]

        with patch.object(blocker_quarantine, "db", fake_db), \
             patch.dict(os.environ, {"ORCH_QUARANTINE_MAX_REWORK_DEPTH": "2"}, clear=False):
            out = blocker_quarantine.run(limit=1)

        self.assertEqual(out["created"], 0)
        self.assertEqual(out["escalated"], 1)
        state_patch = fake_db.update.call_args.args[2]
        self.assertEqual(state_patch["state"], "BLOCKED")
        # run() also does a trailing db.insert("controls", summary, upsert=True) after the loop,
        # so don't assume the approvals insert is the LAST call -- find it by table name.
        approval_calls = [c for c in fake_db.insert.call_args_list if c.args[0] == "approvals"]
        self.assertEqual(len(approval_calls), 1)
        approval = approval_calls[0].args[1]
        self.assertEqual(approval["kind"], "quarantine_escalation")
        self.assertEqual(approval["status"], "pending")


if __name__ == "__main__":
    unittest.main()
