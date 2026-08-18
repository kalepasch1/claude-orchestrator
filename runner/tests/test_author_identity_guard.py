"""author_identity_guard — the narrowest checks that prove §G is enforced.

Real git repositories, not mocks: the guard's whole job is to read what git
actually recorded, so a mocked `git log` would prove nothing.
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
import unittest

RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RUNNER_DIR not in sys.path:
    sys.path.insert(0, RUNNER_DIR)

import author_identity_guard as guard  # noqa: E402

ZERO = "0" * 40


def _run(repo, *args, env=None):
    full = dict(os.environ)
    full.update(env or {})
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True, env=full
    ).stdout.strip()


def _init_repo(path):
    _run(path, "init", "-q", "-b", "master")
    _run(path, "config", "commit.gpgsign", "false")
    return path


def _commit(repo, message, name, email, filename="f.txt"):
    with open(os.path.join(repo, filename), "a", encoding="utf-8") as fh:
        fh.write(message + "\n")
    _run(repo, "add", "-A")
    _run(
        repo,
        "-c",
        f"user.name={name}",
        "-c",
        f"user.email={email}",
        "commit",
        "--no-verify",
        "-q",
        "-m",
        message,
    )
    return _run(repo, "rev-parse", "HEAD")


class GuardTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = _init_repo(self._tmp.name)
        self._saved_mode = guard.ORCH_AUTHOR_IDENTITY_GUARD
        guard.ORCH_AUTHOR_IDENTITY_GUARD = "enforce"

    def tearDown(self):
        guard.ORCH_AUTHOR_IDENTITY_GUARD = self._saved_mode
        self._tmp.cleanup()

    def line(self, sha, remote=ZERO):
        return [f"refs/heads/master {sha} refs/heads/master {remote}"]


class TestStdinParsing(GuardTestCase):
    def test_parses_a_well_formed_update(self):
        self.assertEqual(
            guard.pushed_ranges(["refs/heads/x aaa refs/heads/x bbb"]), [("aaa", "bbb")]
        )

    def test_skips_deletions_and_garbage(self):
        self.assertEqual(guard.pushed_ranges([f"refs/heads/x {ZERO} refs/heads/x bbb"]), [])
        self.assertEqual(guard.pushed_ranges(["nonsense", "", "a b c"]), [])
        self.assertEqual(guard.pushed_ranges(None), [])


class TestClassification(GuardTestCase):
    def test_canonical_identity_is_clean(self):
        blocked, drifted = guard.classify(
            [("sha", guard.canonical_name(), guard.canonical_email())]
        )
        self.assertEqual(blocked, [])
        self.assertEqual(drifted, [])

    def test_known_vercel_blocking_email_is_blocked(self):
        blocked, _ = guard.classify([("sha", "kalepasch1", "mandyjustinepasch@gmail.com")])
        self.assertEqual(len(blocked), 1)

    def test_unknown_email_is_blocked_too_allowlist_not_denylist(self):
        blocked, _ = guard.classify([("sha", "kalepasch1", "someone@example.com")])
        self.assertEqual(len(blocked), 1, "the canonical email is an allow-list, not a deny-list")

    def test_email_comparison_is_case_insensitive(self):
        blocked, _ = guard.classify([("sha", "kalepasch1", guard.canonical_email().upper())])
        self.assertEqual(blocked, [])

    def test_name_drift_is_reported_separately_not_blocked(self):
        blocked, drifted = guard.classify(
            [("sha", "Kale Aaron Pasch", guard.canonical_email())]
        )
        self.assertEqual(blocked, [], "§G calls the name harmless — it must not block")
        self.assertEqual(len(drifted), 1)


class TestPushGate(GuardTestCase):
    def test_allows_a_push_of_canonically_authored_commits(self):
        sha = _commit(self.repo, "good", guard.canonical_name(), guard.canonical_email())
        out = io.StringIO()
        self.assertEqual(guard.check(self.repo, self.line(sha), out), 0)

    def test_refuses_a_push_containing_a_blocking_email(self):
        _commit(self.repo, "good", guard.canonical_name(), guard.canonical_email())
        bad = _commit(self.repo, "bad", "kalepasch1", "mandyjustinepasch@gmail.com")
        out = io.StringIO()
        self.assertEqual(guard.check(self.repo, self.line(bad), out), 1)
        text = out.getvalue()
        self.assertIn("BLOCKED-EMAIL", text)
        self.assertIn(bad[:12], text)
        # the message must tell the operator how to fix it
        self.assertIn("git config user.email", text)

    def test_name_drift_alone_still_allows_the_push(self):
        sha = _commit(self.repo, "drift", "Kale Aaron Pasch", guard.canonical_email())
        out = io.StringIO()
        self.assertEqual(guard.check(self.repo, self.line(sha), out), 0)
        self.assertIn("name drift", out.getvalue())

    def test_only_inspects_commits_the_push_would_add(self):
        already = _commit(self.repo, "bad-but-already-remote", "x", "someone@example.com")
        good = _commit(self.repo, "good", guard.canonical_name(), guard.canonical_email())
        out = io.StringIO()
        # remote already has the bad commit; this push adds only the good one
        self.assertEqual(guard.check(self.repo, self.line(good, remote=already), out), 0)

    def test_warn_mode_reports_without_refusing(self):
        bad = _commit(self.repo, "bad", "x", "someone@example.com")
        guard.ORCH_AUTHOR_IDENTITY_GUARD = "warn"
        out = io.StringIO()
        self.assertEqual(guard.check(self.repo, self.line(bad), out), 0)
        self.assertIn("BLOCKED-EMAIL", out.getvalue())

    def test_off_mode_is_silent(self):
        bad = _commit(self.repo, "bad", "x", "someone@example.com")
        guard.ORCH_AUTHOR_IDENTITY_GUARD = "off"
        out = io.StringIO()
        self.assertEqual(guard.check(self.repo, self.line(bad), out), 0)
        self.assertEqual(out.getvalue(), "")

    def test_a_deletion_push_is_allowed(self):
        out = io.StringIO()
        line = [f"refs/heads/master {ZERO} refs/heads/master abc123"]
        self.assertEqual(guard.check(self.repo, line, out), 0)


class TestFailSoft(GuardTestCase):
    def test_a_non_repo_path_allows_the_push(self):
        with tempfile.TemporaryDirectory() as empty:
            out = io.StringIO()
            self.assertEqual(guard.check(empty, self.line("deadbeef"), out), 0)

    def test_unreadable_stdin_allows_the_push(self):
        class Exploding:
            def __iter__(self):
                raise OSError("stdin went away")

        out = io.StringIO()
        self.assertEqual(guard.check(self.repo, Exploding(), out), 0)
        self.assertIn("allowing push", out.getvalue())

    def test_git_helper_returns_empty_rather_than_raising(self):
        self.assertEqual(guard._git("/nonexistent/path", "log"), "")


class TestAudit(GuardTestCase):
    def test_audit_counts_and_names_the_drift(self):
        _commit(self.repo, "a", guard.canonical_name(), guard.canonical_email())
        _commit(self.repo, "b", "Kale Aaron Pasch", guard.canonical_email())
        _commit(self.repo, "c", "madeus-agent", "noreply@github.com")
        out = io.StringIO()
        self.assertEqual(guard.audit(self.repo, 50, out), 0)
        text = out.getvalue()
        self.assertIn("3 commits inspected", text)
        self.assertIn("1 wrong-email", text)
        self.assertIn("1 name-drift", text)
        self.assertIn("madeus-agent", text)


class TestConfigSurface(GuardTestCase):
    def test_config_is_orch_prefixed_and_secret_free(self):
        names = [n for n in dir(guard) if n.startswith("ORCH_")]
        self.assertTrue(names)
        for name in names:
            self.assertNotRegex(name, r"PASSWORD|TOKEN|SECRET|KEY")

    def test_canonical_values_match_claude_md(self):
        self.assertEqual(guard.canonical_name(), "kalepasch1")
        self.assertEqual(guard.canonical_email(), "kalepasch@gmail.com")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
