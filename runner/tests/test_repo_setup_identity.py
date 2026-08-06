#!/usr/bin/env python3
"""
test_repo_setup_identity.py - the git-identity section of the two-session audit
addendum (dropbox-beethoven-audit-addendum-two-session-recon-slice-2).

The addendum records that both recovery sessions committed as
kalepasch@gmail.com "the identity Vercel requires". The gap this proves closed:
repo_setup_repair treated PRESENCE of user.name/user.email as health, so a
checkout carrying a bot/secondary identity (mandyjustinepasch@gmail.com,
kale@heretomorrow.us) was reported healthy and went on producing commits Vercel
puts in BLOCKED state, which never deploy.

Every test drives a real temp git repo -- the bug lived in what `git config`
actually returned, so mocking it would prove nothing.
"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import repo_setup_repair


_SAVED_ENV = {}


def setUpModule():
    """Cut the tests off from this machine's ~/.gitconfig.

    `git config user.email` in a fresh repo does NOT return empty -- it falls
    through to global/system config. Without this isolation the "unset" cases
    silently read the developer's own identity and the suite passes or fails
    depending on whose laptop it runs on.
    """
    for var in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"):
        _SAVED_ENV[var] = os.environ.get(var)
        os.environ[var] = os.devnull


def tearDownModule():
    for var, old in _SAVED_ENV.items():
        if old is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = old


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def _repo(name=None, email=None):
    """Temp repo with LOCAL identity set (or deliberately unset)."""
    d = tempfile.mkdtemp()
    _git(d, "init", "-q")
    _git(d, "config", "--unset-all", "user.name")
    _git(d, "config", "--unset-all", "user.email")
    if name is not None:
        _git(d, "config", "user.name", name)
    if email is not None:
        _git(d, "config", "user.email", email)
    return d


OWNER_NAME = repo_setup_repair.GIT_IDENTITY_NAME
OWNER_EMAIL = repo_setup_repair.GIT_IDENTITY_EMAIL


class TestCheckGitIdentity(unittest.TestCase):
    def test_owner_identity_is_clean(self):
        d = _repo(OWNER_NAME, OWNER_EMAIL)
        self.assertEqual(repo_setup_repair.check_git_identity(d), [])

    def test_wrong_email_is_a_mismatch(self):
        d = _repo(OWNER_NAME, "mandyjustinepasch@gmail.com")
        found = repo_setup_repair.check_git_identity(d)
        self.assertEqual(len(found), 1)
        self.assertIn("user.email", found[0])
        self.assertIn("mandyjustinepasch@gmail.com", found[0])

    def test_second_non_owner_email_also_caught(self):
        d = _repo(OWNER_NAME, "kale@heretomorrow.us")
        self.assertTrue(any("kale@heretomorrow.us" in m
                            for m in repo_setup_repair.check_git_identity(d)))

    def test_email_comparison_is_case_insensitive(self):
        d = _repo(OWNER_NAME, OWNER_EMAIL.upper())
        self.assertEqual(repo_setup_repair.check_git_identity(d), [])

    def test_unset_is_not_reported_as_mismatch(self):
        # Absence belongs to check_git_config; check_git_identity must not
        # double-report it, or diagnose() emits the same fault twice.
        d = _repo(None, None)
        self.assertEqual(repo_setup_repair.check_git_identity(d), [])
        self.assertIn("user.email", repo_setup_repair.check_git_config(d))

    def test_missing_repo_is_fail_soft(self):
        self.assertEqual(
            repo_setup_repair.check_git_identity("/nonexistent/path/xyz999"), [])


class TestPresenceIsNotHealth(unittest.TestCase):
    """The regression itself: a bot identity satisfies the presence check."""

    def test_bot_identity_passes_presence_but_fails_identity(self):
        d = _repo("some-bot", "bot@example.com")
        self.assertEqual(repo_setup_repair.check_git_config(d), [],
                         "presence check should see nothing missing")
        self.assertNotEqual(repo_setup_repair.check_git_identity(d), [],
                            "identity check must still flag the non-owner author")


class TestRepairGitConfig(unittest.TestCase):
    def test_repairs_wrong_email_to_owner(self):
        d = _repo(OWNER_NAME, "mandyjustinepasch@gmail.com")
        repaired = repo_setup_repair.repair_git_config(d)
        self.assertTrue(any("user.email" in r for r in repaired))
        self.assertEqual(_git(d, "config", "user.email").stdout.strip(), OWNER_EMAIL)
        self.assertEqual(repo_setup_repair.check_git_identity(d), [])

    def test_repair_note_names_the_displaced_value(self):
        # An operator reading the report needs to know WHICH identity was
        # overwritten, not just that something changed.
        d = _repo(OWNER_NAME, "kale@heretomorrow.us")
        repaired = repo_setup_repair.repair_git_config(d)
        self.assertTrue(any("kale@heretomorrow.us" in r for r in repaired))

    def test_still_repairs_unset_config(self):
        d = _repo(None, None)
        repo_setup_repair.repair_git_config(d)
        self.assertEqual(_git(d, "config", "user.email").stdout.strip(), OWNER_EMAIL)
        self.assertEqual(_git(d, "config", "user.name").stdout.strip(), OWNER_NAME)

    def test_owner_identity_is_left_alone(self):
        d = _repo(OWNER_NAME, OWNER_EMAIL)
        self.assertEqual(repo_setup_repair.repair_git_config(d), [])

    def test_repair_writes_local_not_global(self):
        d = _repo(OWNER_NAME, "bot@example.com")
        before = _git(d, "config", "--global", "user.email").stdout.strip()
        repo_setup_repair.repair_git_config(d)
        after = _git(d, "config", "--global", "user.email").stdout.strip()
        self.assertEqual(before, after, "repair must never touch --global config")
        self.assertEqual(
            _git(d, "config", "--local", "user.email").stdout.strip(), OWNER_EMAIL)


class TestDiagnoseSurfacesIdentity(unittest.TestCase):
    def test_diagnose_flags_non_owner_identity(self):
        d = _repo(OWNER_NAME, "bot@example.com")
        report = repo_setup_repair.diagnose(d)
        self.assertFalse(report["identity_ok"])
        self.assertTrue(any("non-owner git identity" in i for i in report["issues"]))

    def test_diagnose_clean_for_owner(self):
        d = _repo(OWNER_NAME, OWNER_EMAIL)
        report = repo_setup_repair.diagnose(d)
        self.assertTrue(report["identity_ok"])

    def test_repair_makes_diagnose_clean(self):
        d = _repo(OWNER_NAME, "bot@example.com")
        report = repo_setup_repair.repair(d)
        self.assertTrue(any("user.email" in r for r in report["repairs"]))
        self.assertFalse(any("non-owner git identity" in i
                             for i in report["post_repair_issues"]))

    def test_commit_after_repair_carries_owner_email(self):
        # End-to-end: the point of the repair is the AUTHOR line Vercel reads.
        d = _repo(OWNER_NAME, "bot@example.com")
        repo_setup_repair.repair_git_config(d)
        open(os.path.join(d, "f.txt"), "w").write("x")
        _git(d, "add", "-A")
        _git(d, "commit", "-q", "--no-verify", "-m", "t")
        author = _git(d, "log", "-1", "--format=%ae").stdout.strip()
        self.assertEqual(author, OWNER_EMAIL)


if __name__ == "__main__":
    unittest.main()
