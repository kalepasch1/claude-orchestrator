#!/usr/bin/env python3
"""Audit addendum §B (already-fixed manifest) + §G (canonical git identity)."""
import os
import re
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER = os.path.join(REPO, "runner")
sys.path.insert(0, RUNNER)

import git_identity as gi  # noqa: E402
import verified_firing as vf  # noqa: E402


class IdentityValueTests(unittest.TestCase):
    def test_the_canonical_identity_matches_claude_md(self):
        text = open(os.path.join(REPO, "CLAUDE.md"), errors="replace").read()
        self.assertIn(gi.CANONICAL_NAME, text)
        self.assertIn(gi.CANONICAL_EMAIL, text)

    def test_env_overrides_follow_the_documented_precedence(self):
        saved = {k: os.environ.get(k) for k in ("ORCH_GIT_USER_NAME", "FLEET_GIT_AUTHOR_NAME")}
        try:
            os.environ["FLEET_GIT_AUTHOR_NAME"] = "legacy"
            self.assertEqual(gi.name(), "legacy")
            os.environ["ORCH_GIT_USER_NAME"] = "preferred"
            self.assertEqual(gi.name(), "preferred", "ORCH_ must outrank FLEET_")
        finally:
            for key, value in saved.items():
                os.environ.pop(key, None)
                if value is not None:
                    os.environ[key] = value

    def test_a_blank_override_does_not_erase_the_identity(self):
        saved = os.environ.get("ORCH_GIT_USER_NAME")
        try:
            os.environ["ORCH_GIT_USER_NAME"] = "   "
            self.assertEqual(gi.name(), gi.CANONICAL_NAME)
        finally:
            os.environ.pop("ORCH_GIT_USER_NAME", None)
            if saved is not None:
                os.environ["ORCH_GIT_USER_NAME"] = saved

    def test_config_args_are_a_one_shot_git_c_pair(self):
        args = gi.config_args()
        self.assertEqual(args[0], "-c")
        self.assertIn(f"user.name={gi.CANONICAL_NAME}", args)
        self.assertIn(f"user.email={gi.CANONICAL_EMAIL}", args)

    def test_env_sets_both_author_and_committer(self):
        environ = gi.env()
        for key in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL",
                    "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
            self.assertIn(key, environ)
        self.assertEqual(environ["GIT_COMMITTER_EMAIL"], gi.CANONICAL_EMAIL)

    def test_env_does_not_clobber_a_caller_supplied_base(self):
        self.assertEqual(gi.env({"FOO": "bar"})["FOO"], "bar")


class IdentityRepoTests(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="identity-")
        subprocess.run(["git", "init", "-q", "-b", "master"], cwd=self.repo)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.repo, ignore_errors=True)

    def test_ensure_writes_the_canonical_identity(self):
        self.assertTrue(gi.ensure(self.repo))
        self.assertEqual(gi.current(self.repo), (gi.CANONICAL_NAME, gi.CANONICAL_EMAIL))

    def test_ensure_is_fail_soft_on_a_missing_repo(self):
        self.assertFalse(gi.ensure("/nonexistent/repo"))
        self.assertFalse(gi.ensure(None))

    def test_current_is_fail_soft(self):
        self.assertEqual(gi.current("/nonexistent/repo"), ("", ""))

    def test_a_commit_made_with_config_args_carries_the_right_author(self):
        gi.ensure(self.repo)
        open(os.path.join(self.repo, "f.txt"), "w").write("x")
        subprocess.run(["git", "add", "-A"], cwd=self.repo)
        subprocess.run(["git"] + gi.config_args() + ["commit", "-qm", "t"], cwd=self.repo)
        out = subprocess.run(["git", "log", "-1", "--format=%an <%ae>"], cwd=self.repo,
                             capture_output=True, text=True).stdout.strip()
        self.assertEqual(out, f"{gi.CANONICAL_NAME} <{gi.CANONICAL_EMAIL}>")


class AuthorAuditTests(unittest.TestCase):
    def test_the_observed_drift_is_reported_by_name(self):
        """The real shape: 374 canonical, 22 'Kale Aaron Pasch', 4 'madeus-agent'."""
        log = ("kalepasch1 <kalepasch@gmail.com>\n" * 3
               + "Kale Aaron Pasch <kalepasch@gmail.com>\n"
               + "madeus-agent <kalepasch@gmail.com>\n")
        report = gi.audit_authors(log)
        self.assertEqual(report["total"], 5)
        self.assertEqual(report["canonical"], 3)
        self.assertEqual(report["drift"]["Kale Aaron Pasch <kalepasch@gmail.com>"], 1)
        self.assertFalse(report["clean"])

    def test_a_blocked_email_is_separated_from_cosmetic_drift(self):
        """Cosmetic name drift is harmless; a wrong email is a BLOCKED Vercel deploy."""
        report = gi.audit_authors("someone <mandyjustinepasch@gmail.com>\n")
        self.assertEqual(sum(report["blocked"].values()), 1)
        self.assertEqual(report["drift"], {})

    def test_a_clean_history_reports_clean(self):
        report = gi.audit_authors("kalepasch1 <kalepasch@gmail.com>\n" * 4)
        self.assertTrue(report["clean"])
        self.assertEqual(report["canonical"], 4)

    def test_malformed_lines_are_skipped_not_counted(self):
        self.assertEqual(gi.audit_authors("not an author line\n\n")["total"], 0)

    def test_audit_is_fail_soft(self):
        self.assertTrue(gi.audit_authors(None)["clean"])
        self.assertTrue(gi.audit_repo("/nonexistent/repo")["clean"])
        self.assertIsInstance(gi.render(gi.audit_authors("")), str)


class NoHardcodedIdentityTests(unittest.TestCase):
    """§G enforcement: the drift happened because the value lived in a dozen places."""

    # `\\?` tolerates a backslash-escaped quote, which is how a nested f-string writes
    # the shell hint `git config user.name \"{canonical_name()}\"`. Without it the regex
    # captured the lone backslash and reported it as a hardcoded name — a false positive
    # that made slice-3 and slice-4 un-co-mergeable while each passed in isolation.
    NAME_LITERAL = re.compile(r"""user\.name["'\s=]+\\?["']?([^"'\s,\]\\]+)""")

    # git_identity.py is where the value is allowed to be written down; everywhere else must
    # ask it. Excluding it is the whole point, not a carve-out.
    OWNER_MODULE = "git_identity.py"

    def _runner_sources(self):
        for entry in sorted(os.listdir(RUNNER)):
            if entry.endswith(".py") and not entry.startswith("test_") and entry != self.OWNER_MODULE:
                yield os.path.join(RUNNER, entry)

    def test_no_runner_module_hardcodes_a_divergent_author_name(self):
        offenders = []
        for path in self._runner_sources():
            try:
                text = open(path, errors="replace").read()
            except OSError:
                continue
            for found in self.NAME_LITERAL.findall(text):
                raw = found.strip("\"'")
                # An interpolation (`{_IDENTITY_NAME}`, `${{ ... }}`, `%s`) is a reference,
                # which is exactly what this test wants to see — only LITERALS are offenders.
                if not raw or raw[0] in "${%" or raw.startswith("f"):
                    continue
                cleaned = raw.strip("{}()")
                if cleaned in (gi.CANONICAL_NAME, "user", "name"):
                    continue
                offenders.append(f"{os.path.basename(path)}: {cleaned}")
        self.assertEqual(offenders, [], f"non-canonical author name hardcoded: {offenders}")

    # A module that must keep working on a checkout WITHOUT git_identity.py (the pre-push
    # hook is exactly that case — it has to fail closed if the owner module is missing, or
    # deleting one file silently disarms the guard) is allowed a documented fallback copy.
    # The §G defect is DIVERGENCE, not duplication, so the fallback is pinned by
    # FallbackIdentityDriftTests below instead of being banned outright.
    FALLBACK_MODULES = {"author_identity_guard.py"}

    def test_no_runner_module_hardcodes_a_blocked_email(self):
        offenders = []
        for path in self._runner_sources():
            name = os.path.basename(path)
            if name in self.FALLBACK_MODULES:
                continue
            try:
                text = open(path, errors="replace").read()
            except OSError:
                continue
            for blocked in gi.BLOCKED_EMAILS:
                if blocked in text:
                    offenders.append(f"{name}: {blocked}")
        self.assertEqual(offenders, [], f"blocked author email present: {offenders}")


class FallbackIdentityDriftTests(unittest.TestCase):
    """A sanctioned fallback copy is only safe while it still agrees with the owner.

    This is the test that would have caught the original incident: two copies of the
    identity constants that were allowed to disagree. Banning the second copy was the
    wrong lever — it broke a guard that legitimately needs to run standalone — so pin
    them together instead.
    """

    def _guard(self):
        import importlib

        return importlib.import_module("author_identity_guard")

    def test_guard_fallback_blocked_emails_match_the_owner(self):
        guard = self._guard()
        self.assertEqual(
            tuple(guard._FALLBACK_BLOCKED_EMAILS),
            tuple(gi.BLOCKED_EMAILS),
            "author_identity_guard fallback drifted from git_identity.BLOCKED_EMAILS",
        )

    def test_guard_fallback_name_and_email_match_the_owner(self):
        guard = self._guard()
        self.assertEqual(guard._FALLBACK_NAME, gi.CANONICAL_NAME)
        self.assertEqual(guard._FALLBACK_EMAIL, gi.CANONICAL_EMAIL)

    def test_guard_prefers_the_owner_module_when_present(self):
        """Fallbacks must be unreachable when git_identity.py is importable."""
        guard = self._guard()
        self.assertIsNotNone(
            guard._identity_module(),
            "guard did not resolve git_identity even though it is on the path",
        )


class VerifiedFiringTests(unittest.TestCase):
    def test_the_already_fixed_items_are_listed(self):
        for key in ("sentinel-hotfix-rescue", "sentinel-no-untracked-stash",
                    "wip-stash-rescue", "core-retry-rpcs"):
            self.assertTrue(vf.is_verified(key), key)
            self.assertTrue(vf.describe(key), key)

    def test_every_entry_is_still_present_in_the_tree(self):
        """The manifest must not be allowed to rot into a comforting lie."""
        gone = vf.regressions(repo=REPO)
        self.assertEqual(gone, [], f"a verified fix regressed: {gone}")

    def test_a_missing_marker_is_reported_as_a_regression_not_as_verified(self):
        saved = vf.VERIFIED["core-retry-rpcs"]
        vf.VERIFIED["core-retry-rpcs"] = (saved[0], saved[1], "THIS_MARKER_DOES_NOT_EXIST")
        try:
            result = vf.check("core-retry-rpcs", repo=REPO)
            self.assertFalse(result["present"])
            self.assertIn("regressed", result["reason"])
        finally:
            vf.VERIFIED["core-retry-rpcs"] = saved

    def test_an_unreadable_file_never_reports_as_verified(self):
        saved = vf.VERIFIED["core-retry-rpcs"]
        vf.VERIFIED["core-retry-rpcs"] = (saved[0], "runner/does_not_exist.py", "x")
        try:
            result = vf.check("core-retry-rpcs", repo=REPO)
            self.assertFalse(result["present"])
            self.assertIn("not found", result["reason"])
        finally:
            vf.VERIFIED["core-retry-rpcs"] = saved

    def test_audit_findings_naming_a_verified_fix_are_dropped(self):
        findings = ["sentinel-hotfix-rescue", "a-genuinely-new-gap", "core-retry-rpcs"]
        self.assertEqual(vf.filter_findings(findings), ["a-genuinely-new-gap"])

    def test_dict_findings_are_supported_too(self):
        findings = [{"key": "wip-stash-rescue"}, {"key": "something-new"}]
        self.assertEqual(vf.filter_findings(findings), [{"key": "something-new"}])

    def test_unknown_keys_and_junk_are_fail_soft(self):
        self.assertFalse(vf.is_verified("nope"))
        self.assertFalse(vf.is_verified(None))
        self.assertEqual(vf.describe(None), "")
        self.assertEqual(vf.check("nope")["reason"], "unknown key")
        self.assertEqual(vf.filter_findings(None), [])

    def test_render_states_that_a_gap_is_a_regression(self):
        text = vf.render([{"key": "k", "present": False, "path": "p", "marker": "m",
                           "reason": "gone"}])
        self.assertIn("REGRESSION", text)

    def test_the_generated_ci_workflow_commits_as_the_repo_owner(self):
        """§G: the workflow template used to commit as `orch-agent <orch-agent@noreply>`."""
        import ci_workflows
        generated = ci_workflows.generate("/tmp/repo")
        self.assertIn(gi.CANONICAL_NAME, generated)
        self.assertIn(gi.CANONICAL_EMAIL, generated)
        self.assertNotIn("orch-agent@noreply", generated)
        self.assertNotIn("user.name 'orch-agent'", generated)

    def test_every_verified_entry_names_a_real_file(self):
        for key, (_, rel_path, _) in vf.VERIFIED.items():
            self.assertTrue(os.path.isfile(os.path.join(REPO, rel_path)),
                            f"{key} points at a file that does not exist: {rel_path}")


if __name__ == "__main__":
    unittest.main()
