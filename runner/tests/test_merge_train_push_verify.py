#!/usr/bin/env python3
"""Push-verify must accept benign advancement and still refuse every real failure.

`_verify_push` demanded local == origin/base exactly. Under fleet concurrency another
train or auto-sync routinely commits on top between our push and our read-back, so a
push that HAD landed was reported as VERIFY:sha-mismatch. Nothing was ever overwritten —
the guard worked — but each event cost a full retry cycle, and the rate was climbing:
64 -> 72 -> 81 over 2026-08-07 alone.

The right question is "is my commit on the remote branch", not "is my commit the tip".
These tests pin both halves of that: the benign interleave passes, and each way a push
can genuinely fail still fails. Real git repos, no mocks — the behaviour under test is
git's reachability, and a mocked `merge-base` would prove nothing.
"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import merge_train


def _run(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60)


def _commit(cwd, name, message):
    with open(os.path.join(cwd, name), "w", encoding="utf-8") as fh:
        fh.write(message)
    _run(cwd, "add", "-A")
    _run(cwd, "-c", "user.name=T", "-c", "user.email=t@t.t", "commit", "-m", message)
    return _run(cwd, "rev-parse", "HEAD").stdout.strip()


class PushVerifyBase(unittest.TestCase):
    """A bare 'origin' plus a clone, so origin can be advanced independently."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.origin = os.path.join(self.tmp, "origin.git")
        self.clone = os.path.join(self.tmp, "clone")
        self.other = os.path.join(self.tmp, "other")

        _run(self.tmp, "init", "--bare", "-b", "main", self.origin)
        seed = os.path.join(self.tmp, "seed")
        os.makedirs(seed)
        _run(seed, "init", "-b", "main")
        _commit(seed, "README", "seed")
        _run(seed, "remote", "add", "origin", self.origin)
        _run(seed, "push", "origin", "main")

        _run(self.tmp, "clone", self.origin, self.clone)
        _run(self.tmp, "clone", self.origin, self.other)


class TestBenignAdvancementPasses(PushVerifyBase):
    def test_someone_committed_on_top_of_our_push(self):
        # We push, THEN another train lands a commit on top. Our work is safely on the
        # remote; the old exact-match check called this a mismatch and forced a retry.
        _commit(self.clone, "ours.txt", "our work")
        _run(self.clone, "push", "origin", "main")

        _run(self.other, "fetch", "origin", "main")
        _run(self.other, "checkout", "main")
        _run(self.other, "reset", "--hard", "origin/main")
        _commit(self.other, "theirs.txt", "their work")
        _run(self.other, "push", "origin", "main")

        self.assertEqual(merge_train._verify_push(self.clone, "main"), "")

    def test_exact_match_still_passes(self):
        _commit(self.clone, "ours.txt", "our work")
        _run(self.clone, "push", "origin", "main")
        self.assertEqual(merge_train._verify_push(self.clone, "main"), "")

    def test_many_commits_on_top_still_passes(self):
        _commit(self.clone, "ours.txt", "our work")
        _run(self.clone, "push", "origin", "main")
        _run(self.other, "fetch", "origin", "main")
        _run(self.other, "checkout", "main")
        _run(self.other, "reset", "--hard", "origin/main")
        for i in range(5):
            _commit(self.other, f"t{i}.txt", f"their work {i}")
        _run(self.other, "push", "origin", "main")
        self.assertEqual(merge_train._verify_push(self.clone, "main"), "")


class TestRealFailuresStillFail(PushVerifyBase):
    def test_push_never_landed(self):
        # The whole point of the guard: we committed locally and did NOT push. Local is
        # AHEAD of remote, so it is not an ancestor of it, and this must still fail.
        _commit(self.clone, "ours.txt", "our work")
        err = merge_train._verify_push(self.clone, "main")
        self.assertTrue(err.startswith("VERIFY:sha-mismatch"), err)

    def test_divergent_history_fails(self):
        # Someone force-pushed a different line; our commit is unreachable from the tip.
        _commit(self.clone, "ours.txt", "our work")
        _run(self.clone, "push", "origin", "main")

        _run(self.other, "fetch", "origin", "main")
        _run(self.other, "checkout", "main")
        _run(self.other, "reset", "--hard", "origin/main~1")
        _commit(self.other, "divergent.txt", "different line")
        _run(self.other, "push", "--force", "origin", "main")

        err = merge_train._verify_push(self.clone, "main")
        self.assertTrue(err.startswith("VERIFY:sha-mismatch"), err)

    def test_remote_rewound_below_our_commit_fails(self):
        _commit(self.clone, "ours.txt", "our work")
        _run(self.clone, "push", "origin", "main")
        _run(self.other, "fetch", "origin", "main")
        _run(self.other, "checkout", "main")
        _run(self.other, "reset", "--hard", "origin/main~1")
        _run(self.other, "push", "--force", "origin", "main")

        err = merge_train._verify_push(self.clone, "main")
        self.assertTrue(err.startswith("VERIFY:sha-mismatch"), err)

    def test_unknown_ref_is_reported_not_swallowed(self):
        self.assertEqual(merge_train._verify_push(self.clone, "no-such-branch"),
                         "VERIFY:rev-parse-failed")

    def test_verification_does_not_trust_the_stale_local_cache(self):
        """A push that never left the machine must not verify.

        `origin/<base>` is a local cache. The old code compared against it FIRST and only
        fetched when it disagreed — so whenever the cache happened to already match local,
        the function returned success having never contacted the remote. That is precisely
        the DB/GitHub desync this verifier exists to catch, and no amount of relaxing the
        sha comparison is safe while it is possible.

        Here the remote is advanced by someone else and our local ref is pointed at that
        same commit WITHOUT any push: local == cached origin/<base>, but the true remote
        has moved on to a commit we are not an ancestor of.
        """
        _run(self.other, "checkout", "main")
        divergent = _commit(self.other, "theirs.txt", "their work")
        _run(self.other, "push", "origin", "main")

        # Our clone's cache still points at the old tip; put local there too.
        cached = _run(self.clone, "rev-parse", "origin/main").stdout.strip()
        _run(self.clone, "checkout", "main")
        _run(self.clone, "reset", "--hard", cached)
        self.assertNotEqual(cached, divergent)
        self.assertEqual(_run(self.clone, "rev-parse", "main").stdout.strip(),
                         _run(self.clone, "rev-parse", "origin/main").stdout.strip())

        # Stale cache agrees; the real remote does not. Must NOT report success.
        # (Our local tip is behind the true remote, i.e. it IS an ancestor, so this
        # asserts only that the refresh happened — the ancestor rule then applies to
        # real remote state rather than to a cached lie.)
        merge_train._verify_push(self.clone, "main")
        self.assertEqual(_run(self.clone, "rev-parse", "origin/main").stdout.strip(),
                         divergent,
                         "verify must refresh origin/<base> instead of trusting the cache")


class TestIsAncestorFailsClosed(PushVerifyBase):
    def test_empty_shas_are_not_ancestors(self):
        self.assertFalse(merge_train._is_ancestor(self.clone, "", "HEAD"))
        self.assertFalse(merge_train._is_ancestor(self.clone, "HEAD", ""))

    def test_unknown_sha_is_not_an_ancestor(self):
        # An unanswerable question must read as divergence, never as "verified".
        self.assertFalse(merge_train._is_ancestor(self.clone, "0" * 40, "HEAD"))

    def test_commit_is_its_own_ancestor(self):
        head = _run(self.clone, "rev-parse", "HEAD").stdout.strip()
        self.assertTrue(merge_train._is_ancestor(self.clone, head, head))

    def test_direction_matters(self):
        parent = _run(self.clone, "rev-parse", "HEAD").stdout.strip()
        child = _commit(self.clone, "child.txt", "child")
        self.assertTrue(merge_train._is_ancestor(self.clone, parent, child))
        self.assertFalse(merge_train._is_ancestor(self.clone, child, parent))


if __name__ == "__main__":
    unittest.main(verbosity=2)
