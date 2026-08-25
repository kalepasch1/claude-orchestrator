#!/usr/bin/env python3
"""Pins git_auth: git stderr must never carry a credential back to a caller.

git_auth's docstring promised credentials stayed "out of process listings and
logs", and fetch_branch's comment claimed to "Log error safely (no credential
leaks)" — but run_git returned result.stderr verbatim and no redaction existed
anywhere in the module. git echoes the remote URL back on most auth failures, so
a remote of the form https://x-access-token:ghp_xxx@github.com/... put the secret
straight into the return value, into the log line, and from there into tasks.note.
That is the shape of the 2026-08-02 plaintext-credential incident.

Run: python3 -m pytest tests/test_git_auth_redaction.py -q
"""
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))
import git_auth  # noqa: E402


class Redact(unittest.TestCase):
    def test_url_userinfo_is_stripped_but_host_survives(self):
        out = git_auth.redact(
            "fatal: unable to access 'https://x-access-token:ghp_ABCDEFGHIJKLMNOPQRST@github.com/o/r.git/'")
        self.assertNotIn("ghp_ABCDEFGHIJKLMNOPQRST", out)
        self.assertNotIn("x-access-token", out)
        self.assertIn("github.com/o/r.git", out)
        self.assertIn(git_auth.REDACTED, out)

    def test_bare_provider_tokens_are_stripped(self):
        for secret in ("ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345",
                       "github_pat_11ABCDEFG0123456789abcdef",
                       "glpat-ABCDEFGHIJKLMNOPQRST"):
            out = git_auth.redact(f"remote: rejected using {secret} here")
            self.assertNotIn(secret, out, f"leaked {secret}")

    def test_credential_words_are_stripped(self):
        self.assertNotIn("token", git_auth.redact(
            "fatal: could not authenticate with token").lower())
        self.assertNotIn("hunter2", git_auth.redact("password=hunter2"))

    def test_configured_pat_is_stripped_even_in_an_odd_shape(self):
        with patch.object(git_auth, "_PAT", "s3cr3t-value-not-token-shaped"):
            out = git_auth.redact("remote: denied s3cr3t-value-not-token-shaped")
            self.assertNotIn("s3cr3t-value-not-token-shaped", out)

    def test_ordinary_output_is_untouched(self):
        msg = "fatal: couldn't find remote ref agent/some-branch"
        self.assertEqual(git_auth.redact(msg), msg)

    def test_empty_input_round_trips(self):
        self.assertEqual(git_auth.redact(""), "")
        self.assertIsNone(git_auth.redact(None))


class RunGitAppliesRedaction(unittest.TestCase):
    def test_stderr_is_redacted_and_stdout_is_not(self):
        completed = subprocess.CompletedProcess(
            ["git"], 128,
            "refs/heads/secret-fix\n",
            "fatal: unable to access 'https://u:ghp_ABCDEFGHIJKLMNOPQRST@github.com/o/r.git/'")
        with patch("git_auth.subprocess.run", return_value=completed):
            with patch("git_auth.os.path.isdir", return_value=True):
                rc, out, err = git_auth.run_git(["fetch"], "/tmp")

        self.assertEqual(rc, 128)
        # stdout is ref data callers parse — it must survive intact
        self.assertIn("secret-fix", out)
        self.assertNotIn("ghp_ABCDEFGHIJKLMNOPQRST", err)
        self.assertIn(git_auth.REDACTED, err)


if __name__ == "__main__":
    unittest.main()
