#!/usr/bin/env python3
"""Audit addendum §E — sentinel's checkout_guard must COMMIT protected work, never stash it.

Root cause of record: `checkout_guard` used to `git stash` dirty files on the primary checkout
when a drift-restore was blocked. Nothing in this codebase ever pops a stash, so a stash IS a
loss — and it swallowed operator hotfixes twice in one night, including the fix for the
merge-resolver bug that was actively wiping improvements.

The fix commits protected paths (`runner/`, `scripts/`, `web/server/`, any `.py`/`.sh`) to
`hotfix/sentinel-rescue-<ts>` instead. These tests hold that fix in place END TO END against a
real git repository: a dirty protected file is driven through a *forced, blocked* drift-restore
and must come out the other side as a reachable commit, with no stash entry created.

Non-protected dirt still falls back to the stash path — that behaviour is pinned too, so a
future "simplification" cannot quietly widen or narrow the protected set.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
sys.path.insert(0, RUNNER)

import sentinel  # noqa: E402


def _run(repo, *args):
    return subprocess.run(list(args), cwd=repo, capture_output=True, text=True, timeout=60)


class CheckoutGuardRescueTests(unittest.TestCase):
    """Drive the real checkout_guard against a real repo whose checkout is genuinely blocked."""

    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="sentinel-rescue-")
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)

        _run(self.repo, "git", "init", "-q", "-b", "master")
        _run(self.repo, "git", "config", "user.name", "kalepasch1")
        _run(self.repo, "git", "config", "user.email", "kalepasch@gmail.com")
        _run(self.repo, "git", "config", "commit.gpgsign", "false")
        os.makedirs(os.path.join(self.repo, "runner"), exist_ok=True)
        os.makedirs(os.path.join(self.repo, "docs"), exist_ok=True)

        self._write("runner/critical.py", "VERSION = 'master'\n")
        self._write("docs/notes.md", "master notes\n")
        _run(self.repo, "git", "add", "-A")
        _run(self.repo, "git", "commit", "-qm", "base")

        # A drifted agent branch that CHANGES the same files, so returning to master with a
        # dirty tree is genuinely refused by git — the exact condition that triggered the
        # old stash path.
        _run(self.repo, "git", "checkout", "-q", "-b", "agent/drifted")
        self._write("runner/critical.py", "VERSION = 'agent'\n")
        self._write("docs/notes.md", "agent notes\n")
        _run(self.repo, "git", "add", "-A")
        _run(self.repo, "git", "commit", "-qm", "agent work")

        # Point sentinel at this repo. `sh` binds cwd=REPO as a default argument at import
        # time, so the git shim must be replaced rather than the REPO constant alone.
        self._orig = (sentinel.REPO, sentinel.git, sentinel.emit, sentinel.log,
                      sentinel.BASE_BRANCH)
        sentinel.REPO = self.repo
        sentinel.BASE_BRANCH = "master"
        sentinel.git = lambda *a, **k: _run(self.repo, "git", *a)
        self.events = []
        sentinel.emit = lambda kind, **f: self.events.append((kind, f))
        sentinel.log = lambda action, detail="": None

    def tearDown(self):
        (sentinel.REPO, sentinel.git, sentinel.emit, sentinel.log,
         sentinel.BASE_BRANCH) = self._orig

    # ── helpers ──────────────────────────────────────────────────────────────
    def _write(self, rel, text):
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def _stash_entries(self):
        return [l for l in _run(self.repo, "git", "stash", "list").stdout.splitlines() if l.strip()]

    def _rescue_branches(self):
        out = _run(self.repo, "git", "branch", "--list", "hotfix/sentinel-rescue-*").stdout
        return [b.strip().lstrip("* ") for b in out.splitlines() if b.strip()]

    def _blob_on(self, ref, rel):
        return _run(self.repo, "git", "show", f"{ref}:{rel}").stdout

    def _assert_checkout_is_blocked(self):
        r = _run(self.repo, "git", "checkout", "master")
        self.assertNotEqual(r.returncode, 0,
                            "test setup is wrong: the drift-restore must actually be blocked")

    # ── the §E assertion ─────────────────────────────────────────────────────
    def test_dirty_protected_file_survives_forced_restore_as_a_commit(self):
        self._write("runner/critical.py", "VERSION = 'operator hotfix — must not be lost'\n")
        self._assert_checkout_is_blocked()

        sentinel.checkout_guard({})

        branches = self._rescue_branches()
        self.assertEqual(len(branches), 1,
                         "protected dirt must be preserved on exactly one hotfix/sentinel-rescue-* branch")
        self.assertIn("operator hotfix — must not be lost",
                      self._blob_on(branches[0], "runner/critical.py"),
                      "the rescued commit must contain the operator's actual content")

    def test_no_stash_is_created_for_protected_dirt(self):
        """A stash is write-only in this codebase — creating one IS the loss."""
        self._write("runner/critical.py", "VERSION = 'hotfix'\n")
        self._assert_checkout_is_blocked()

        sentinel.checkout_guard({})

        self.assertEqual(self._stash_entries(), [],
                         "checkout_guard must leave no stash entry behind for protected paths")

    def test_rescued_work_is_reachable_from_a_named_ref(self):
        """Reachable means recoverable: visible in `git branch`, diffable, mergeable."""
        self._write("runner/critical.py", "VERSION = 'hotfix'\n")
        self._assert_checkout_is_blocked()

        sentinel.checkout_guard({})

        branch = self._rescue_branches()[0]
        sha = _run(self.repo, "git", "rev-parse", branch).stdout.strip()
        self.assertTrue(sha)
        reachable = _run(self.repo, "git", "branch", "--contains", sha).stdout
        self.assertIn(branch, reachable)

    def test_rescue_emits_an_operator_visible_event(self):
        self._write("runner/critical.py", "VERSION = 'hotfix'\n")
        self._assert_checkout_is_blocked()

        sentinel.checkout_guard({})

        kinds = [k for k, _ in self.events]
        self.assertIn("hotfix-rescued", kinds,
                      "a silent rescue is indistinguishable from a silent loss")
        fields = dict(self.events[kinds.index("hotfix-rescued")][1])
        self.assertTrue(str(fields.get("branch", "")).startswith("hotfix/sentinel-rescue-"))
        self.assertGreaterEqual(int(fields.get("files", 0)), 1)

    def test_shell_scripts_anywhere_count_as_protected(self):
        """Protected = runner/, scripts/, web/server/, or ANY .py/.sh — not just runner/."""
        _run(self.repo, "git", "checkout", "-q", "master")
        self._write("deploy.sh", "echo master\n")
        _run(self.repo, "git", "add", "-A")
        _run(self.repo, "git", "commit", "-qm", "add script")
        _run(self.repo, "git", "checkout", "-q", "agent/drifted")
        _run(self.repo, "git", "merge", "-q", "master", "-m", "merge")
        self._write("deploy.sh", "echo agent\n")
        _run(self.repo, "git", "add", "-A")
        _run(self.repo, "git", "commit", "-qm", "agent script")
        self._write("deploy.sh", "echo operator hotfix\n")
        self._assert_checkout_is_blocked()

        sentinel.checkout_guard({})

        self.assertEqual(self._stash_entries(), [])
        branch = self._rescue_branches()[0]
        self.assertIn("operator hotfix", self._blob_on(branch, "deploy.sh"))

    def test_non_protected_dirt_still_uses_the_stash_path(self):
        """Only protected paths are promoted to commits; docs dirt keeps the old behaviour."""
        self._write("docs/notes.md", "unimportant local scribble\n")
        self._assert_checkout_is_blocked()

        sentinel.checkout_guard({})

        self.assertEqual(self._rescue_branches(), [],
                         "non-protected dirt must not manufacture a hotfix branch")
        self.assertEqual(len(self._stash_entries()), 1)
        self.assertIn("sentinel-drift", self._stash_entries()[0])

    def test_clean_tree_restore_needs_no_rescue_at_all(self):
        sentinel.checkout_guard({})
        self.assertEqual(self._rescue_branches(), [])
        self.assertEqual(self._stash_entries(), [])
        self.assertEqual(
            _run(self.repo, "git", "branch", "--show-current").stdout.strip(), "master")

    def test_guard_never_stashes_untracked_files(self):
        """`git stash push -u` here destroyed 282 batches of queued work (2026-07-08..16)."""
        self._write("runner/critical.py", "VERSION = 'hotfix'\n")
        self._write("intake-drop-brand-new.md", "a queued operator drop\n")
        self._assert_checkout_is_blocked()

        sentinel.checkout_guard({})

        self.assertTrue(os.path.exists(os.path.join(self.repo, "intake-drop-brand-new.md")),
                        "an untracked intake drop must still be on disk after a drift-restore")


if __name__ == "__main__":
    unittest.main()
