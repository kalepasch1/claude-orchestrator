"""Unit tests for the rescue-ref reconciler.

Run: python3 -m pytest tools/tests/test_reconcile_rescue_refs.py

Builds a throwaway git repo per test so the assertions exercise real git
plumbing. The classifier's entire job is reading git state correctly; a mock
would happily agree with a wrong command, which is how a reconciler ends up
emitting a confident ledger about a repository it never actually read.
"""

import os
import subprocess
import sys
import tempfile
import unittest

# The module under test lives one directory up, beside the rest of tools/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import reconcile_rescue_refs as r  # noqa: E402


def run(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True,
                   capture_output=True, text=True)


def out(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def write(repo, rel, body):
    path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(path) or repo, exist_ok=True)
    with open(path, "w") as fh:
        fh.write(body)


def commit(repo, message):
    run(repo, "add", "-A")
    run(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", message)
    return out(repo, "rev-parse", "HEAD")


class RepoTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        run(self.repo, "init", "-q", "-b", "main")
        write(self.repo, "src/app.py", "X = 1\n")
        self.base_sha = commit(self.repo, "base")

        self._saved_repo = r.REPO
        r.REPO = self.repo
        r.reset_caches()

        def restore():
            r.REPO = self._saved_repo
            r.reset_caches()

        self.addCleanup(restore)
        self.addCleanup(self.tmp.cleanup)

    def rescue_ref(self, name, sha):
        """Park `sha` under refs/orch-rescue/ exactly as the sweeper does."""
        run(self.repo, "update-ref", "refs/orch-rescue/" + name, sha)

    def item(self, name, sha, created_at=0):
        return r.Item(ref="refs/orch-rescue/" + name, sha=sha,
                      subject="orch-rescue: periodic sweep",
                      created_at=created_at)


class TestResolveBase(RepoTestCase):
    """An unresolvable base must stop the run, not quietly poison it."""

    def test_existing_base_resolves_to_a_sha(self):
        self.assertEqual(r.resolve_base("main"), self.base_sha)

    def test_missing_base_raises(self):
        with self.assertRaises(r.BaseRefError):
            r.resolve_base("origin/does-not-exist")

    def test_tree_ish_that_is_not_a_commit_raises(self):
        tree = out(self.repo, "rev-parse", "main^{tree}")
        with self.assertRaises(r.BaseRefError):
            r.resolve_base(tree)

    def test_error_names_the_offending_base(self):
        with self.assertRaises(r.BaseRefError) as ctx:
            r.resolve_base("origin/typo-branch")
        self.assertIn("origin/typo-branch", str(ctx.exception))

    def test_main_exits_nonzero_on_missing_base(self):
        ledger = os.path.join(self.repo, "out.json")
        argv = ["reconcile_rescue_refs.py", "--base", "origin/nope",
                "--fingerprint", "deadbeef", "--repo", self.repo,
                "--out", ledger]
        saved = sys.argv
        sys.argv = argv
        try:
            self.assertEqual(r.main(), 2)
        finally:
            sys.argv = saved
        # And crucially: no ledger file was produced to be mistaken for a real one.
        self.assertFalse(os.path.exists(ledger))


class TestClassification(RepoTestCase):
    def test_commit_reachable_from_base_is_already_present(self):
        it = self.item("merged", self.base_sha)
        r.classify(it, "main", set())
        self.assertEqual(it.classification, "ALREADY_PRESENT")
        self.assertIn("reachable", it.disposition)

    def test_unreachable_commit_that_still_applies_is_recoverable(self):
        run(self.repo, "checkout", "-q", "-b", "side")
        write(self.repo, "src/new_module.py", "Y = 2\n")
        sha = commit(self.repo, "add new module")
        run(self.repo, "checkout", "-q", "main")
        run(self.repo, "branch", "-q", "-D", "side")
        self.rescue_ref("side", sha)

        it = self.item("side", sha)
        r.classify(it, "main", set())
        self.assertEqual(it.classification, "RECOVERABLE_VALUE")
        self.assertIn("src/new_module.py", it.files)

    def test_every_touched_path_rewritten_after_the_ref_is_superseded(self):
        run(self.repo, "checkout", "-q", "-b", "side")
        write(self.repo, "src/app.py", "X = 2\n")
        sha = commit(self.repo, "side edit")
        run(self.repo, "checkout", "-q", "main")
        run(self.repo, "branch", "-q", "-D", "side")

        write(self.repo, "src/app.py", "X = 99  # newest wins\n")
        commit(self.repo, "base rewrites the same path")

        # Ref predates the base rewrite.
        it = self.item("side", sha, created_at=1)
        r.classify(it, "main", set())
        self.assertEqual(it.classification, "SUPERSEDED_BY_NEWER")

    def test_empty_sweep_commit_carries_no_value(self):
        sha = out(self.repo, "commit-tree", "main^{tree}", "-p", self.base_sha,
                  "-m", "orch-rescue: periodic sweep")
        self.rescue_ref("empty", sha)
        it = self.item("empty", sha)
        r.classify(it, "main", set())
        self.assertEqual(it.classification, "ALREADY_PRESENT")
        self.assertEqual(it.evidence, "empty diff")

    def test_classification_never_leaves_unknown(self):
        run(self.repo, "checkout", "-q", "-b", "side")
        write(self.repo, "src/other.py", "Z = 3\n")
        sha = commit(self.repo, "other")
        run(self.repo, "checkout", "-q", "main")
        for name, target in (("a", self.base_sha), ("b", sha)):
            it = self.item(name, target)
            r.classify(it, "main", set())
            self.assertNotEqual(it.classification, "UNKNOWN")


class TestMemoization(RepoTestCase):
    """Caches must speed the run up without ever answering for the wrong key."""

    def test_newest_touch_is_cached_per_base_and_path(self):
        calls = []
        real_git = r.git

        def counting_git(*args, **kwargs):
            calls.append(args)
            return real_git(*args, **kwargs)

        r.git = counting_git
        self.addCleanup(lambda: setattr(r, "git", real_git))

        first = r.newest_touch("main", "src/app.py")
        before = len(calls)
        second = r.newest_touch("main", "src/app.py")
        self.assertEqual(first, second)
        self.assertEqual(len(calls), before, "second lookup should hit the cache")

        # A different path is a different question and must not reuse the entry.
        r.newest_touch("main", "src/other.py")
        self.assertGreater(len(calls), before)

    def test_cache_is_keyed_on_base_not_just_path(self):
        run(self.repo, "checkout", "-q", "-b", "later")
        write(self.repo, "src/app.py", "X = 5\n")
        commit(self.repo, "later touches app.py")
        run(self.repo, "checkout", "-q", "main")

        on_main = r.newest_touch("main", "src/app.py")
        on_later = r.newest_touch("later", "src/app.py")

        # Two distinct cache entries, not one answer reused across bases.
        self.assertIn(("main", "src/app.py"), r._NEWEST_TOUCH_CACHE)
        self.assertIn(("later", "src/app.py"), r._NEWEST_TOUCH_CACHE)
        self.assertEqual(r._NEWEST_TOUCH_CACHE[("main", "src/app.py")], on_main)
        self.assertEqual(r._NEWEST_TOUCH_CACHE[("later", "src/app.py")], on_later)
        # `later` rewrote the path after main's last touch, so it is not older.
        self.assertGreaterEqual(on_later, on_main)

    def test_reset_caches_clears_both_maps(self):
        r.newest_touch("main", "src/app.py")
        r.agent_branches_containing(self.base_sha)
        self.assertTrue(r._NEWEST_TOUCH_CACHE)
        self.assertTrue(r._CONTAINS_CACHE)
        r.reset_caches()
        self.assertFalse(r._NEWEST_TOUCH_CACHE)
        self.assertFalse(r._CONTAINS_CACHE)

    def test_contains_lookup_is_cached_per_sha(self):
        r.agent_branches_containing(self.base_sha)
        self.assertIn(self.base_sha, r._CONTAINS_CACHE)


if __name__ == "__main__":
    unittest.main()
