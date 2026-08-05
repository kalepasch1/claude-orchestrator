#!/usr/bin/env python3
"""Audit addendum §A + §F.

§A — the do-not-touch manifest, and the terminal-slug gate that `remotegc` requires before
     it could ever be wired.
§F — credentials must never survive in a git remote URL or in anything we log.
"""
import os
import sys
import unittest

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
sys.path.insert(0, RUNNER)

import do_not_touch  # noqa: E402
import remote_url_guard as rug  # noqa: E402


class DoNotTouchTests(unittest.TestCase):
    def test_the_four_deliberate_jobs_are_listed(self):
        for job in ("mergetrain", "actionexec", "editorial", "remotegc"):
            self.assertTrue(do_not_touch.is_deliberately_unscheduled(job), job)
            self.assertTrue(do_not_touch.reason(job), job)

    def test_an_audit_of_unscheduled_jobs_reports_only_genuine_gaps(self):
        gaps = do_not_touch.filter_unscheduled(
            ["mergetrain", "actionexec", "editorial", "remotegc", "somethingreal"])
        self.assertEqual(gaps, ["somethingreal"])

    def test_remotegc_is_the_one_entry_with_a_hard_prerequisite(self):
        self.assertIn("terminal_slugs", do_not_touch.prerequisite("remotegc"))
        self.assertEqual(do_not_touch.prerequisite("mergetrain"), "")

    def test_remotegc_prerequisite_is_marked_satisfied_by_this_change(self):
        self.assertIn("remotegc", do_not_touch.PREREQUISITE_SATISFIED)
        self.assertEqual(do_not_touch.blocked_jobs(), [])

    def test_unknown_job_is_not_protected_and_never_raises(self):
        self.assertFalse(do_not_touch.is_deliberately_unscheduled("nope"))
        self.assertFalse(do_not_touch.is_deliberately_unscheduled(None))
        self.assertEqual(do_not_touch.reason(None), "")

    def test_render_names_the_irreversible_risk(self):
        text = do_not_touch.render()
        self.assertIn("remotegc", text)
        self.assertIn("Irreversible", text)


class RemoteGcTerminalGateTests(unittest.TestCase):
    """The §A prerequisite, enforced: age alone must never delete a remote branch."""

    def setUp(self):
        import workflow_guardrails
        self.wg = workflow_guardrails
        self.calls = []

        def fake_git(repo, *args, **kwargs):
            self.calls.append(args)
            if args[:2] == ("branch", "-r"):
                return (0, "  origin/agent/live-task\n  origin/agent/done-task\n", "")
            if args[:2] == ("log", "-1"):
                return (0, "1", "")   # epoch 1 == ancient
            return (0, "", "")

        self._real_git = workflow_guardrails._git
        workflow_guardrails._git = fake_git

    def tearDown(self):
        self.wg._git = self._real_git

    def _deleted_branches(self):
        return [a for a in self.calls if a[:3] == ("push", "origin", "--delete")]

    def test_non_terminal_branch_is_never_deleted(self):
        self.wg.gc_remote_branches("/tmp/repo", terminal={"done-task"})
        deleted = self._deleted_branches()
        self.assertNotIn(("push", "origin", "--delete", "agent/live-task"), deleted)

    def test_empty_terminal_set_deletes_nothing_at_all(self):
        result = self.wg.gc_remote_branches("/tmp/repo", terminal=set())
        self.assertEqual(result["deleted"], 0)
        self.assertIn("fail safe", result.get("reason", ""))
        self.assertEqual(self._deleted_branches(), [])

    def test_terminal_slugs_returns_empty_set_when_db_is_unavailable(self):
        """An empty set must mean 'delete nothing' — never 'nothing is protected'."""
        import db
        real_select = db.select
        db.select = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down"))
        try:
            self.assertEqual(self.wg.terminal_slugs("/tmp/repo"), set())
        finally:
            db.select = real_select

    def test_terminal_slugs_none_triggers_the_fail_safe_path(self):
        """gc_remote_branches(repo) with no explicit set must not delete on a DB outage."""
        real = self.wg.terminal_slugs
        self.wg.terminal_slugs = lambda *a, **k: set()
        try:
            result = self.wg.gc_remote_branches("/tmp/repo")
            self.assertEqual(result["deleted"], 0)
            self.assertEqual(self._deleted_branches(), [])
        finally:
            self.wg.terminal_slugs = real

    def test_terminal_branch_past_age_is_still_eligible(self):
        """The gate must narrow deletion, not disable GC entirely."""
        self.wg.gc_remote_branches("/tmp/repo", terminal={"done-task"})
        considered = [a for a in self.calls if a[:2] == ("log", "-1")]
        self.assertIn(("log", "-1", "--format=%ct", "origin/agent/done-task"), considered)
        self.assertNotIn(("log", "-1", "--format=%ct", "origin/agent/live-task"), considered)

    def test_gate_signature_matches_branch_gc_contract(self):
        import inspect
        import branch_gc
        self.assertIn("terminal_slugs", inspect.signature(branch_gc.collect_garbage).parameters)
        self.assertIn("terminal", inspect.signature(self.wg.gc_remote_branches).parameters)


class RemoteUrlGuardTests(unittest.TestCase):
    PAT_URL = "https://ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA@github.com/kalepasch1/x.git"
    CLEAN_URL = "https://github.com/kalepasch1/x.git"

    def test_detects_embedded_pat(self):
        self.assertTrue(rug.has_credentials(self.PAT_URL))
        self.assertFalse(rug.has_credentials(self.CLEAN_URL))

    def test_clean_url_drops_the_credential_and_keeps_the_repo(self):
        self.assertEqual(rug.clean_url(self.PAT_URL), self.CLEAN_URL)

    def test_redaction_never_leaks_the_token(self):
        redacted = rug.redact(f"origin\t{self.PAT_URL} (fetch)")
        self.assertNotIn("ghp_AAAA", redacted)
        self.assertIn("***@github.com", redacted)

    def test_token_hint_names_the_shape_not_the_value(self):
        hint = rug.token_hint(self.PAT_URL)
        self.assertEqual(hint, "ghp_…")
        self.assertNotIn("AAAA", hint)

    def test_user_password_pair_is_also_caught(self):
        self.assertTrue(rug.has_credentials("https://kale:hunter2@example.com/r.git"))
        self.assertNotIn("hunter2", rug.redact("https://kale:hunter2@example.com/r.git"))

    def test_ssh_remote_is_not_a_finding(self):
        self.assertFalse(rug.has_credentials("git@github.com:kalepasch1/x.git"))

    def test_audit_report_is_safe_to_log(self):
        rug_list = rug.list_remotes
        rug.list_remotes = lambda repo: {"origin": self.PAT_URL}
        try:
            report = rug.audit("/tmp/repo")
            self.assertFalse(report["clean"])
            self.assertNotIn("ghp_AAAA", rug.render(report))
            self.assertIn("CREDENTIALS IN REMOTE URL", rug.render(report))
        finally:
            rug.list_remotes = rug_list

    def test_scrub_defaults_to_dry_run(self):
        rug_list = rug.list_remotes
        rug.list_remotes = lambda repo: {"origin": self.PAT_URL}
        try:
            report = rug.scrub("/tmp/repo")
            self.assertFalse(report["applied"])
            self.assertEqual(report["rewrote"], ["origin"])
        finally:
            rug.list_remotes = rug_list

    def test_clean_repo_reports_clean(self):
        rug_list = rug.list_remotes
        rug.list_remotes = lambda repo: {"origin": self.CLEAN_URL}
        try:
            report = rug.audit("/tmp/repo")
            self.assertTrue(report["clean"])
            self.assertIn("no embedded credentials", rug.render(report))
        finally:
            rug.list_remotes = rug_list

    def test_everything_is_fail_soft_on_junk(self):
        self.assertEqual(rug.redact(None), "")
        self.assertEqual(rug.clean_url(None), "")
        self.assertFalse(rug.has_credentials(None))
        self.assertEqual(rug.token_hint(None), "")
        self.assertTrue(rug.audit("/nonexistent/repo/path")["clean"])
        self.assertIsInstance(rug.render(None), str)


if __name__ == "__main__":
    unittest.main()
