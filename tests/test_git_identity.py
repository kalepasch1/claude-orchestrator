#!/usr/bin/env python3
"""
Guard for audit addendum §G — git identity.

`runner/git_identity.py` says in its own docstring that "tests/test_git_identity.py fails
the build if any file hardcodes a name that is not the canonical one". That file did not
exist. The module centralised the identity but nothing stopped a new call site from
hardcoding a different name, which is the exact failure mode §G was raised about.

§G, verbatim from the operator's addendum (2026-07-30):

    Both sessions used email `kalepasch@gmail.com` (the identity Vercel requires). Name has
    varied (`kalepasch1` vs `Kale Aaron Pasch`) — harmless, but standardize on the repo
    CLAUDE.md value (`kalepasch1`) going forward.

The email is the load-bearing half: Vercel puts a production deploy into BLOCKED state when
the commit author is anyone else, so a wrong email is a silent deploy outage. The name is
cosmetic, which is precisely why it drifts unless something checks it.
"""
from __future__ import annotations

import os
import re
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER_DIR = os.path.join(REPO_ROOT, "runner")
if RUNNER_DIR not in sys.path:
    sys.path.insert(0, RUNNER_DIR)

import git_identity  # noqa: E402  — path set up above

# Directories worth scanning for hardcoded identities. Tests are excluded: fixtures
# legitimately commit as "Test"/"t" to build throwaway repos.
SCAN_DIRS = ("runner", "scripts", "tools")
SKIP_PATH_MARKERS = ("/test_", "/tests/", "node_modules", "__pycache__", "/.git/")

# `-c user.name=X`, `user.name=X`, `"user.name", "X"` and `'user.name', 'X'` all appear in
# this repo, so match the value however it is quoted or separated.
NAME_LITERAL = re.compile(
    r"""user\.name["']?\s*[,=]\s*["']([^"']+)["']""")
EMAIL_LITERAL = re.compile(
    r"""user\.email["']?\s*[,=]\s*["']([^"']+)["']""")


def _is_identity_literal(value: str) -> bool:
    """True when a captured value is a real author name, not scanning noise.

    Two shapes are matched by the pattern but are not identities: the git config KEY in a
    key list — `for key in ("user.name", "user.email")` captures `user.email` — and
    f-string interpolations like `user.name={name()}`, which are the correct usage.
    """
    text = str(value or "")
    if not text or text.startswith("user."):
        return False
    return "{" not in text and "%" not in text


def _scannable_files():
    for directory in SCAN_DIRS:
        root_dir = os.path.join(REPO_ROOT, directory)
        if not os.path.isdir(root_dir):
            continue
        for dirpath, _dirnames, filenames in os.walk(root_dir):
            for filename in filenames:
                if not filename.endswith((".py", ".sh", ".mjs", ".js")):
                    continue
                path = os.path.join(dirpath, filename)
                rel = os.path.relpath(path, REPO_ROOT).replace(os.sep, "/")
                if any(marker in f"/{rel}" for marker in SKIP_PATH_MARKERS):
                    continue
                yield rel, path


class CanonicalIdentityTest(unittest.TestCase):
    """The values themselves, straight from CLAUDE.md."""

    def test_canonical_name_matches_claude_md(self):
        self.assertEqual(git_identity.CANONICAL_NAME, "kalepasch1")

    def test_canonical_email_is_the_one_vercel_requires(self):
        self.assertEqual(git_identity.CANONICAL_EMAIL, "kalepasch@gmail.com")

    def test_config_args_carry_both_halves(self):
        args = git_identity.config_args()
        self.assertIn("user.name=kalepasch1", args)
        self.assertIn("user.email=kalepasch@gmail.com", args)

    def test_env_sets_author_and_committer(self):
        env = git_identity.env()
        for key in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
            self.assertEqual(env[key], "kalepasch1")
        for key in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
            self.assertEqual(env[key], "kalepasch@gmail.com")

    def test_helpers_never_raise(self):
        """CLAUDE.md requires fail-soft: an identity helper that raises blocks a commit."""
        for call in (git_identity.name, git_identity.email, git_identity.config_args,
                     git_identity.env):
            with self.subTest(call=getattr(call, "__name__", str(call))):
                try:
                    call()
                except Exception as exc:  # noqa: BLE001 — the assertion IS "no exception"
                    self.fail(f"{call.__name__} raised {type(exc).__name__}: {exc}")


class NoHardcodedForeignIdentityTest(unittest.TestCase):
    """The guard the module's docstring promised: no call site may hardcode another name."""

    def test_no_source_file_hardcodes_a_non_canonical_name(self):
        offenders = []
        for rel, path in _scannable_files():
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as handle:
                    text = handle.read()
            except OSError:
                continue
            for value in NAME_LITERAL.findall(text):
                if _is_identity_literal(value) and value != git_identity.CANONICAL_NAME:
                    offenders.append(f"{rel}: user.name={value!r}")
        self.assertEqual(
            offenders, [],
            "these files hardcode a git author name that is not "
            f"{git_identity.CANONICAL_NAME!r} (audit addendum §G):\n  "
            + "\n  ".join(offenders))

    def test_no_source_file_hardcodes_a_blocked_email(self):
        """A blocked author email is a production deploy outage, not a cosmetic issue."""
        offenders = []
        for rel, path in _scannable_files():
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as handle:
                    text = handle.read()
            except OSError:
                continue
            for value in EMAIL_LITERAL.findall(text):
                if value.lower() in git_identity.BLOCKED_EMAILS:
                    offenders.append(f"{rel}: user.email={value!r}")
        self.assertEqual(offenders, [],
                         "these files hardcode an email Vercel BLOCKS:\n  "
                         + "\n  ".join(offenders))


class AuthorDriftAuditTest(unittest.TestCase):
    """`audit_authors` has to separate the outage case from the cosmetic one."""

    def test_canonical_history_is_clean(self):
        report = git_identity.audit_authors(
            "kalepasch1 <kalepasch@gmail.com>\nkalepasch1 <kalepasch@gmail.com>\n")
        self.assertTrue(report["clean"])
        self.assertEqual(report["canonical"], 2)
        self.assertEqual(report["drift"], {})

    def test_wrong_name_is_drift_not_blocked(self):
        report = git_identity.audit_authors("Kale Pasch <kalepasch@gmail.com>\n")
        self.assertFalse(report["clean"])
        self.assertEqual(report["blocked"], {})
        self.assertEqual(report["drift"], {"Kale Pasch <kalepasch@gmail.com>": 1})

    def test_blocked_email_is_reported_as_blocked(self):
        report = git_identity.audit_authors("kalepasch1 <kale@heretomorrow.us>\n")
        self.assertFalse(report["clean"])
        self.assertEqual(report["drift"], {})
        self.assertEqual(len(report["blocked"]), 1)

    def test_every_known_drift_name_is_classified_as_drift(self):
        """Each listed drift name must actually be recognised, not silently pass."""
        for drift_name in git_identity.KNOWN_DRIFT_NAMES:
            with self.subTest(name=drift_name):
                report = git_identity.audit_authors(
                    f"{drift_name} <{git_identity.CANONICAL_EMAIL}>\n")
                self.assertFalse(report["clean"], f"{drift_name} not detected as drift")
                self.assertEqual(report["canonical"], 0)

    def test_the_executor_skill_name_is_a_known_drift_name(self):
        """Regression for the drift this slice was raised to close.

        "Kale Pasch" is what the cowork-executor skill passes to `git -c user.name=`, so it
        accumulates on every run. If it is not in the list, the audit reports it as an
        anonymous author and nobody traces it back to the skill.
        """
        self.assertIn("Kale Pasch", git_identity.KNOWN_DRIFT_NAMES)

    def test_audit_never_raises_on_garbage(self):
        for junk in (None, "", "not an author line", ["<>"], 12345):
            with self.subTest(junk=junk):
                report = git_identity.audit_authors(junk)
                self.assertIn("total", report)


class OwnerEmailTests(unittest.TestCase):
    """§G's allow-list has two members, not one — and exactly two.

    The owner commits from two addresses: `kalepasch@gmail.com` from a terminal, and
    `<id>+kalepasch1@users.noreply.github.com` whenever GitHub commits on their behalf
    (the "Merge pull request" button, web edits, squash merges). Recognising only the
    first is what wedged claude-orchestrator's release train on 2026-08-18: the 14
    commits on `master` were all reachable only through GitHub-authored merge commits,
    so the push that would have re-absorbed them into `orchestrator/dev` was refused.

    The second address is not a deploy hazard. A 400-deployment audit of the Vercel
    account on 2026-08-17 found it deploying to production successfully, against 18 of 18
    BLOCKED for genuinely-foreign authors.
    """

    ALIAS = "102100311+kalepasch1@users.noreply.github.com"

    def test_the_canonical_address_is_the_owner(self):
        self.assertTrue(git_identity.is_owner_email(git_identity.CANONICAL_EMAIL))

    def test_the_github_alias_is_the_owner(self):
        self.assertTrue(git_identity.is_owner_email(self.ALIAS))

    def test_the_pre_2017_alias_shape_is_the_owner(self):
        self.assertTrue(
            git_identity.is_owner_email(
                f"{git_identity.CANONICAL_LOGIN}@users.noreply.github.com"))

    def test_matching_ignores_case_and_surrounding_space(self):
        self.assertTrue(git_identity.is_owner_email(f"  {self.ALIAS.upper()}  "))

    def test_another_accounts_alias_is_not_the_owner(self):
        """Non-vacuity: the predicate must still be able to say no."""
        self.assertFalse(
            git_identity.is_owner_email("999+someoneelse@users.noreply.github.com"))

    def test_the_login_must_be_the_entire_local_part(self):
        """A substring test would accept every one of these."""
        for impostor in (
            f"attacker+{git_identity.CANONICAL_LOGIN}@users.noreply.github.com",
            f"x{git_identity.CANONICAL_LOGIN}@users.noreply.github.com",
            f"{git_identity.CANONICAL_LOGIN}@users.noreply.github.com.evil.example",
            f"{git_identity.CANONICAL_LOGIN}@evil.example.com",
        ):
            with self.subTest(impostor=impostor):
                self.assertFalse(git_identity.is_owner_email(impostor), impostor)

    def test_the_blocked_addresses_are_still_not_the_owner(self):
        for blocked in git_identity.BLOCKED_EMAILS:
            with self.subTest(blocked=blocked):
                self.assertFalse(git_identity.is_owner_email(blocked))

    def test_never_raises_on_junk(self):
        for junk in (None, "", "   ", 42, object(), ["a@b.c"]):
            with self.subTest(junk=junk):
                self.assertFalse(git_identity.is_owner_email(junk))

    def test_the_login_is_env_overridable_like_the_rest_of_the_identity(self):
        prior = os.environ.get("ORCH_GIT_USER_LOGIN")
        os.environ["ORCH_GIT_USER_LOGIN"] = "someoneelse"
        try:
            self.assertEqual(git_identity.login(), "someoneelse")
            self.assertTrue(
                git_identity.is_owner_email("7+someoneelse@users.noreply.github.com"))
            self.assertFalse(git_identity.is_owner_email(self.ALIAS))
        finally:
            if prior is None:
                os.environ.pop("ORCH_GIT_USER_LOGIN", None)
            else:
                os.environ["ORCH_GIT_USER_LOGIN"] = prior

    def test_an_override_login_with_regex_metacharacters_is_escaped(self):
        """A `.` in a login must not become a wildcard."""
        prior = os.environ.get("ORCH_GIT_USER_LOGIN")
        os.environ["ORCH_GIT_USER_LOGIN"] = "a.c"
        try:
            self.assertTrue(git_identity.is_owner_email("a.c@users.noreply.github.com"))
            self.assertFalse(git_identity.is_owner_email("abc@users.noreply.github.com"))
        finally:
            if prior is None:
                os.environ.pop("ORCH_GIT_USER_LOGIN", None)
            else:
                os.environ["ORCH_GIT_USER_LOGIN"] = prior

    def test_the_audit_counts_owner_merge_commits_as_canonical_not_drift(self):
        report = git_identity.audit_authors(
            f"{git_identity.CANONICAL_NAME} <{git_identity.CANONICAL_EMAIL}>\n"
            f"{git_identity.CANONICAL_NAME} <{self.ALIAS}>\n")
        self.assertEqual(report["total"], 2)
        self.assertEqual(report["canonical"], 2)
        self.assertTrue(report["clean"])

    def test_the_audit_still_reports_a_foreign_alias_as_drift(self):
        report = git_identity.audit_authors(
            "someoneelse <999+someoneelse@users.noreply.github.com>\n")
        self.assertEqual(report["canonical"], 0)
        self.assertFalse(report["clean"])


if __name__ == "__main__":
    unittest.main()
