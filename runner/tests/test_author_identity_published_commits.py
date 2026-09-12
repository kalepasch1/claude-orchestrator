#!/usr/bin/env python3
"""A commit already on the remote is not introduced by the next push.

REPRODUCES, 2026-08-24. Ten commits were ready to push from apparently onto
`orchestrator/dev` and the guard refused all of them over one: `6cd4d679`, an
automated corpus harvest authored `corpus@apparently.cc`.

That commit was already on `origin/master` and 302 other remote branches.
Refusing the push therefore prevented nothing — the commit was on the remote
and Vercel had already seen it — while the remedy the guard printed
(`git rebase --exec 'git commit --amend --reset-author'`) would not have
corrected it. On published history that forks the commit: the original stays
reachable from 303 refs and a divergent duplicate lands on the branch pushed.

The guard already reasoned correctly for a brand-new branch, excluding
`--remotes` so only locally-introduced commits are judged. The
`remote_sha..local_sha` form used for an existing branch did not, and reported
every commit missing from THAT BRANCH rather than from the repository.

These tests build real git repositories, because the bug lives in a rev range —
a mocked `git log` would have agreed with whatever the range said.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import author_identity_guard as guard  # noqa: E402

OWNER = ("kalepasch1", "kalepasch@gmail.com")
ALIAS = ("kalepasch1", "102100311+kalepasch1@users.noreply.github.com")
BOT = ("corpus", "corpus@apparently.cc")
ZERO = guard.ZERO_SHA


def _run(cwd, *args):
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(" ".join(args) + " -> " + proc.stderr.strip())
    return proc.stdout.strip()


def _commit(repo, filename, author, message):
    with open(os.path.join(repo, filename), "a") as fh:
        fh.write(message + "\n")
    _run(repo, "add", "-A")
    _run(repo, "-c", f"user.name={author[0]}", "-c", f"user.email={author[1]}",
         "commit", "-m", message)
    return _run(repo, "rev-parse", "HEAD")


class PublishedCommitTest(unittest.TestCase):
    """A local clone whose `master` carries a bot commit, pushing a dev branch."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.origin = os.path.join(self.tmp, "origin.git")
        self.work = os.path.join(self.tmp, "work")

        _run(self.tmp, "init", "--bare", "-b", "master", self.origin)
        _run(self.tmp, "clone", self.origin, self.work)
        _run(self.work, "config", "user.name", OWNER[0])
        _run(self.work, "config", "user.email", OWNER[1])

        _commit(self.work, "README.md", OWNER, "base")
        # The corpus bot's commit, published to master exactly as it was on
        # apparently — this is the commit the guard kept refusing.
        self.bot_sha = _commit(self.work, "corpus.txt", BOT,
                               "corpus: authority harvest")
        _run(self.work, "push", "-u", "origin", "master")

        # A dev branch that does NOT yet contain the bot commit on the remote,
        # branched from before it, then merged forward — the apparently shape.
        _run(self.work, "checkout", "-b", "dev", "HEAD~1")
        _commit(self.work, "dev.txt", OWNER, "dev work")
        _run(self.work, "push", "-u", "origin", "dev")
        self.dev_remote = _run(self.work, "rev-parse", "origin/dev")

        # Now consolidate master into dev, dragging the bot commit along.
        _run(self.work, "-c", f"user.name={OWNER[0]}", "-c",
             f"user.email={OWNER[1]}", "merge", "--no-ff", "-m",
             "merge: consolidate master into dev", "master")
        _commit(self.work, "dev.txt", ALIAS, "chore: merged via the GitHub button")
        self.dev_local = _run(self.work, "rev-parse", "HEAD")
        _run(self.work, "fetch", "origin")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _push_line(self):
        return [f"refs/heads/dev {self.dev_local} refs/heads/dev {self.dev_remote}"]

    def test_the_published_bot_commit_is_not_inspected(self):
        authors = guard.commit_authors(self.work, self.dev_local, self.dev_remote)
        emails = {e for _s, _n, e in authors}
        self.assertNotIn(BOT[1], emails,
                         "a commit already on origin/master is not added by this push")

    def test_the_push_is_allowed(self):
        # THE REGRESSION: this returned 1 and printed a rewrite recommendation.
        self.assertEqual(guard.check(self.work, self._push_line()), 0)

    def test_the_owners_github_alias_is_still_fine(self):
        authors = guard.commit_authors(self.work, self.dev_local, self.dev_remote)
        blocked, _drift = guard.classify(authors)
        self.assertEqual(blocked, [])

    def test_a_genuinely_new_bad_commit_is_still_refused(self):
        """The gate must still do its job for anything not yet published."""
        _commit(self.work, "leak.txt", ("someone", "stranger@example.com"),
                "unreviewed change")
        head = _run(self.work, "rev-parse", "HEAD")
        line = [f"refs/heads/dev {head} refs/heads/dev {self.dev_remote}"]
        self.assertEqual(guard.check(self.work, line), 1)

    def test_a_new_bad_commit_is_named_in_the_report(self):
        bad = _commit(self.work, "leak.txt", ("someone", "stranger@example.com"),
                      "unreviewed change")
        head = _run(self.work, "rev-parse", "HEAD")
        authors = guard.commit_authors(self.work, head, self.dev_remote)
        blocked, _ = guard.classify(authors)
        self.assertEqual([s for s, _n, _e in blocked], [bad])

    def test_first_push_of_a_new_branch_still_excludes_remotes(self):
        _run(self.work, "checkout", "-b", "feature")
        new = _commit(self.work, "feature.txt", OWNER, "feature work")
        line = [f"refs/heads/feature {new} refs/heads/feature {ZERO}"]
        self.assertEqual(guard.check(self.work, line), 0)
        authors = guard.commit_authors(self.work, new, ZERO)
        self.assertNotIn(BOT[1], {e for _s, _n, e in authors})


class FailSoftTest(unittest.TestCase):
    """A guard that wedges pushes on its own bug is worse than the drift."""

    def test_a_non_repository_allows_the_push(self):
        tmp = tempfile.mkdtemp()
        try:
            line = [f"refs/heads/x {'a' * 40} refs/heads/x {'b' * 40}"]
            self.assertEqual(guard.check(tmp, line), 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_unparseable_stdin_is_ignored(self):
        self.assertEqual(guard.pushed_ranges(["nonsense", "", "a b c"]), [])

    def test_a_deletion_pushes_nothing(self):
        self.assertEqual(
            guard.pushed_ranges([f"refs/heads/x {ZERO} refs/heads/x {'b' * 40}"]), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
