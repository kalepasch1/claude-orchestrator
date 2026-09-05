import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import blocker_quarantine
import agentic_repair
import quarantine_triage


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
        # run() calls repair_misclassified and dedupe_replacements before the
        # candidate scan, and both now page through db.select_all rather than
        # db.select. select is stubbed with a POSITIONAL side_effect list, so the
        # two leading [] that used to absorb those scans have been dropped and
        # select_all returns [] here -- otherwise the candidate scan consumed the
        # wrong entry and the task under test was never seen.
        fake_db.select_all.return_value = []
        fake_db.select.side_effect = [[task], []]

        with patch.object(blocker_quarantine, "db", fake_db), \
             patch.dict(os.environ, {"ORCH_QUARANTINE_CODER": "ollama"}, clear=False):
            out = blocker_quarantine.run(limit=1)

        self.assertEqual(out["created"], 1)
        inserted = fake_db.insert.call_args_list[0].args[1]
        self.assertEqual(inserted["state"], "QUEUED")
        self.assertEqual(inserted["force_coder"], "ollama")
        # 2026-07-10: legal is now unconditionally "confidential" (checked before the
        # ORCH_QUARANTINE_LOCAL_ONLY env var), not "crown_jewel" -- provider_terms.py treats
        # them identically (both local-only), so this is a same-behavior literal update, not a
        # loosening of the safety guarantee. See _sensitivity()'s docstring.
        self.assertEqual(inserted["sensitivity"], "confidential")
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
        # run() calls repair_misclassified and dedupe_replacements before the
        # candidate scan, and both now page through db.select_all rather than
        # db.select. select is stubbed with a POSITIONAL side_effect list, so the
        # two leading [] that used to absorb those scans have been dropped and
        # select_all returns [] here -- otherwise the candidate scan consumed the
        # wrong entry and the task under test was never seen.
        fake_db.select_all.return_value = []
        fake_db.select.side_effect = [[task], []]

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
        # run() calls repair_misclassified and dedupe_replacements before the
        # candidate scan, and both now page through db.select_all rather than
        # db.select. select is stubbed with a POSITIONAL side_effect list, so the
        # two leading [] that used to absorb those scans have been dropped and
        # select_all returns [] here -- otherwise the candidate scan consumed the
        # wrong entry and the task under test was never seen.
        fake_db.select_all.return_value = []
        fake_db.select.side_effect = [[task], [{"id": "already", "state": "QUEUED"}]]

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
        # run() calls repair_misclassified and dedupe_replacements before the
        # candidate scan, and both now page through db.select_all rather than
        # db.select. select is stubbed with a POSITIONAL side_effect list, so the
        # two leading [] that used to absorb those scans have been dropped and
        # select_all returns [] here -- otherwise the candidate scan consumed the
        # wrong entry and the task under test was never seen.
        fake_db.select_all.return_value = []
        fake_db.select.side_effect = [[task], []]

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

    def test_sensitive_categories_are_always_confidential_regardless_of_local_only_flag(self):
        """secret/security/legal must stay local-only (confidential) no matter how
        ORCH_QUARANTINE_LOCAL_ONLY is set -- this is the safety-preserving half of the fix."""
        task = {"id": "t20", "slug": "x", "note": "", "log_tail": "", "prompt": "", "kind": "build"}
        for category in ("secret", "security", "legal"):
            for env_val in ("true", "false"):
                with patch.dict(os.environ, {"ORCH_QUARANTINE_LOCAL_ONLY": env_val}, clear=False):
                    self.assertEqual(blocker_quarantine._sensitivity(task, category), "confidential")

    def test_nonsensitive_category_forced_local_only_when_env_true(self):
        task = {"id": "t21", "slug": "x", "note": "", "log_tail": "", "prompt": "", "kind": "build"}
        with patch.dict(os.environ, {"ORCH_QUARANTINE_LOCAL_ONLY": "true"}, clear=False):
            self.assertEqual(blocker_quarantine._sensitivity(task, "buildfail"), "crown_jewel")
            self.assertEqual(blocker_quarantine._sensitivity(task, "testfail"), "crown_jewel")
            self.assertEqual(blocker_quarantine._sensitivity(task, "rework"), "crown_jewel")

    def test_nonsensitive_category_uses_dynamic_privacy_check_when_env_false(self):
        """2026-07-10 fix: with ORCH_QUARANTINE_LOCAL_ONLY=false, non-sensitive categories must
        NOT be force-routed to the single-threaded local model lock -- they fall through to the
        same dynamic privacy.sensitivity() check ordinary (non-quarantine) tasks use, freeing
        them to use the full concurrent coder pool."""
        task = {"id": "t22", "slug": "ordinary-build-fix", "note": "cannot find module",
                "log_tail": "", "prompt": "fix the build", "kind": "build"}
        with patch.dict(os.environ, {"ORCH_QUARANTINE_LOCAL_ONLY": "false"}, clear=False), \
             patch.object(blocker_quarantine.privacy, "sensitivity", return_value="standard") as mock_priv:
            result = blocker_quarantine._sensitivity(task, "buildfail")
        self.assertEqual(result, "standard")
        mock_priv.assert_called_once()

    def test_distant_token_and_detected_in_long_build_log_is_not_secret(self):
        """Production bug (2026-07-11): _is_secret() checked _SECRET_TERM (matches bare "token")
        and _SECRET_VIOLATION_CONTEXT (matches generic words like "detected") independently
        against the WHOLE evidence blob. A long `nuxt build` failure log can easily contain
        "token" in one unrelated stack frame (e.g. a CSRF/session-token module) and "detected"
        in another (e.g. a dependency scanner's routine output), hundreds of characters apart
        with zero relation to each other -- yet both regexes would match, producing a false
        'secret' classification. Observed repeatedly on rework-secret-* branches failing on
        plain `nuxt: command not found` build errors. The two terms must be near each other to
        count as a real signal."""
        far_apart_log = (
            "sh: nuxt: command not found\n"
            + ("x" * 200)
            + "\nsome/path/auth/token/refresh.ts: import session token helper\n"
            + ("y" * 200)
            + "\n3 outdated dependencies detected during npm audit\n"
        )
        task = {
            "id": "t12",
            "slug": "rework-secret-relfix-beethoven-07081450-c8ff549",
            "state": "TESTFAIL",
            "kind": "build",
            "prompt": "Rework: fix the build.",
            "note": "train: tests failed on rebased agent/rework-secret-relfix-beethoven-07081450-c8ff549: > build\n> nuxt build",
            "log_tail": far_apart_log,
        }
        self.assertEqual(blocker_quarantine.classify(task), "buildfail")

    def test_close_proximity_token_and_violation_context_still_secret(self):
        """The proximity tightening must not weaken genuine detection: a real violation phrase
        near the term should still classify as secret even without an explicit-pattern match."""
        task = {
            "id": "t13",
            "slug": "some-feature",
            "state": "BLOCKED",
            "kind": "build",
            "prompt": "x",
            "note": "checked-in API key token found in commit diff",
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
        # run() calls repair_misclassified and dedupe_replacements before the
        # candidate scan, and both now page through db.select_all rather than
        # db.select. select is stubbed with a POSITIONAL side_effect list, so the
        # two leading [] that used to absorb those scans have been dropped and
        # select_all returns [] here -- otherwise the candidate scan consumed the
        # wrong entry and the task under test was never seen.
        fake_db.select_all.return_value = []
        fake_db.select.side_effect = [[task], []]

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


    def test_rework_prefix_slug_does_not_self_trigger_secret_reclassification(self):
        # A rework- slug embeds the previous category name; it must not re-classify the task
        # as "secret" on subsequent repair attempts, which would loop forever.
        task = {
            "id": "t6",
            "slug": "rework-secret-ext-passport-bureau-api-abc1234",
            "state": "TESTFAIL",
            "kind": "bugfix",
            "prompt": "Fix the failing tests in the passport bureau integration.",
            "note": "train: tests failed on rebased agent/rework-secret-ext-passport-bureau-api-abc1234",
            "log_tail": "12 failed | 88 passed",
        }
        self.assertNotEqual(blocker_quarantine.classify(task), "secret")
        self.assertEqual(blocker_quarantine.classify(task), "testfail")

    def test_testfail_state_is_evidence_not_identity(self):
        """A TESTFAIL state must not make classify() treat "testfail" as a self-referential
        verdict.

        _identity_only_category() re-runs the classifier with the failure evidence blanked to
        ask "did this category come only from the task's NAME?". It blanked note and log_tail
        but left `state` in place, and _classify_raw() has a literal `state == "TESTFAIL"`
        branch — so the answer was "yes, identity-only" for every testfail in the fleet, and
        every one of them was downgraded to generic "rework", throwing away the testfail repair
        directive. The runner sets state from what the run DID; that is evidence.
        """
        task = {
            "id": "t-state-evidence",
            "slug": "ordinary-feature-slug",
            "state": "TESTFAIL",
            "kind": "bugfix",
            "prompt": "Add pagination to the ledger view.",
            "note": "train: tests failed on rebased agent/ordinary-feature-slug",
            "log_tail": "7 failed | 210 passed",
        }
        self.assertEqual(blocker_quarantine.classify(task), "testfail")

    def test_identity_only_guard_still_downgrades_a_name_only_verdict(self):
        """Guard against overcorrecting: with no evidence at all, a category reached purely
        from the slug must still be refused. Only `state` moved to the evidence side."""
        task = {
            "id": "t-identity-only",
            "slug": "recover-missing-branch-widget-sync",
            "state": "BLOCKED",
            "kind": "build",
            "prompt": "Recover the missing branch for widget-sync.",
            "note": "",
            "log_tail": "",
        }
        self.assertNotEqual(blocker_quarantine.classify(task), "missing-branch")


class QuarantineTriageInfraPatternTest(unittest.TestCase):
    """The tier-2 infra matcher must not fire on the letters "oom" inside ordinary words."""

    def test_groomed_note_is_not_an_oom_infra_failure(self):
        """Regression: `OOM|oom-kill` was unanchored under re.I, so it matched "groomed".

        queue_groom.py parks duplicate slugs with the note "groomed: duplicate queued slug",
        and blocker_quarantine.run() hands note+log_tail to triage() BEFORE it ever calls
        classify(). Every groomed task therefore came back tier-2 "infra failure: oom" and was
        reset to QUEUED with a runner-restart recommendation instead of being classified —
        after which it groomed again on the next pass.
        """
        infra, detail = quarantine_triage.is_infra_failure("groomed: duplicate queued slug")
        self.assertFalse(infra, f"matched on {detail!r}")

    def test_ordinary_words_containing_oom_are_not_infra_failures(self):
        """room/zoom/bloom/boom/broom/mushroom all appear in real build and test output."""
        for text in ("the room fixture timed out of scope",
                     "zoom integration test assertion failed",
                     "bloom filter returned a false positive",
                     "boom: expected 3 got 4",
                     "mushroom-cli exited 1"):
            with self.subTest(text=text):
                infra, detail = quarantine_triage.is_infra_failure(text)
                self.assertFalse(infra, f"matched on {detail!r}")

    def test_real_oom_output_is_still_an_infra_failure(self):
        """Guard against overcorrecting: the genuine forms must all still match."""
        for text in ("Out of memory: Killed process 4211",
                     "OOM killed the worker",
                     "oom-killed after 12s",
                     "oom_kill event on cgroup",
                     "cannot allocate memory"):
            with self.subTest(text=text):
                infra, _detail = quarantine_triage.is_infra_failure(text)
                self.assertTrue(infra)

    def test_groomed_task_is_not_triaged_into_a_restart_retry(self):
        """End-to-end through triage(): the groomed note must not produce restart+retry.

        db is stubbed out because triage()'s tier-1 flake check reads and writes the hash
        history in fleet_config; this test is about tier 2, not about the flake ledger.
        """
        fake_db = MagicMock()
        fake_db.select.return_value = []
        task = {"id": "t-groomed", "note": "groomed: duplicate queued slug",
                "remediation_count": 0}
        with patch.object(quarantine_triage, "db", fake_db):
            verdict = quarantine_triage.triage(task, "groomed: duplicate queued slug")

        self.assertNotEqual(verdict["category"], "infra")
        self.assertNotEqual(verdict["action"], "restart+retry")


class StripReworkNoiseTest(unittest.TestCase):

    def test_trailing_bare_rework_prefix_is_stripped(self):
        """The last hop of a rework chain has no category segment ("…-rework-<hash>")."""
        self.assertEqual(
            blocker_quarantine._strip_rework_noise("rework-legal-rework-0d98862"),
            "0d98862",
        )

    def test_slug_without_a_rework_prefix_is_untouched(self):
        self.assertEqual(
            blocker_quarantine._strip_rework_noise("reworked-payments-api"),
            "reworked-payments-api",
        )


if __name__ == "__main__":
    unittest.main()
