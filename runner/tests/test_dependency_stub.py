#!/usr/bin/env python3
"""dependency_stub had no test file at all.

279 lines that create, mark and **delete git branches** (`git branch -D`) on the
operator's real checkouts, with zero tests and — per a repo-wide grep — zero
production callers. Untested code that runs destructive git commands is the worst
combination in this repo: nothing proves the TTL arithmetic, nothing proves the
cleanup filter, and the first thing to exercise it would do so on a live repo.

These are the basic tests. They run against throwaway `git init` repos so the
branch creation and deletion paths are exercised for real rather than mocked into
agreement with themselves — a mocked `git branch -D` proves nothing about whether
the right branch was chosen.

Two behaviours are pinned deliberately because they are the destructive ones:
  * `cleanup_stubs` deletes ONLY `stub/` branches, never `agent/` ones
  * a stub is deleted when superseded or past its TTL, and not otherwise

Run: python3 -m unittest runner.tests.test_dependency_stub -v
"""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ORCH_DB_URL", "")
os.environ.setdefault("ORCH_DB_ENABLED", "false")

import dependency_stub as ds


def _run(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=60)


class _Repo:
    """A throwaway git repo with one commit on `main`."""

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        repo = self.tmp.name
        _run(repo, "init", "-q", "-b", "main")
        _run(repo, "config", "user.name", "test")
        _run(repo, "config", "user.email", "test@example.com")
        with open(os.path.join(repo, "f.txt"), "w") as fh:
            fh.write("x\n")
        _run(repo, "add", "-A")
        _run(repo, "commit", "-q", "-m", "init")
        return repo

    def __exit__(self, *exc):
        self.tmp.cleanup()


def _branches(repo):
    out = _run(repo, "branch", "--format=%(refname:short)").stdout
    return sorted(b.strip() for b in out.splitlines() if b.strip())


class NamingTest(unittest.TestCase):
    def test_stub_branches_live_in_their_own_namespace(self):
        self.assertEqual(ds._stub_branch_name("my-dep"), "stub/my-dep")

    def test_stub_namespace_cannot_collide_with_agent(self):
        self.assertFalse(ds._stub_branch_name("x").startswith("agent/"))


class BranchExistsTest(unittest.TestCase):
    def test_existing_branch_is_found(self):
        with _Repo() as repo:
            self.assertTrue(ds._branch_exists(repo, "main"))

    def test_missing_branch_is_not_found(self):
        with _Repo() as repo:
            self.assertFalse(ds._branch_exists(repo, "agent/nope"))


class MarkAndAgeTest(unittest.TestCase):
    def test_a_marked_branch_is_a_stub(self):
        with _Repo() as repo:
            _run(repo, "branch", "stub/dep-a", "main")
            ds._mark_stub(repo, "stub/dep-a", "identity")
            self.assertTrue(ds.is_stub(repo, "stub/dep-a"))

    def test_an_unmarked_branch_is_not_a_stub(self):
        with _Repo() as repo:
            _run(repo, "branch", "agent/real", "main")
            self.assertFalse(ds.is_stub(repo, "agent/real"))

    def test_a_missing_branch_is_not_a_stub(self):
        with _Repo() as repo:
            self.assertFalse(ds.is_stub(repo, "stub/absent"))

    def test_a_fresh_stub_has_a_small_age(self):
        with _Repo() as repo:
            _run(repo, "branch", "stub/dep-a", "main")
            ds._mark_stub(repo, "stub/dep-a", "identity")
            self.assertLess(ds._stub_age(repo, "stub/dep-a"), 5)

    def test_age_of_a_non_stub_is_none(self):
        with _Repo() as repo:
            _run(repo, "branch", "agent/real", "main")
            self.assertIsNone(ds._stub_age(repo, "agent/real"))

    def test_the_marker_records_its_source(self):
        with _Repo() as repo:
            _run(repo, "branch", "stub/dep-a", "main")
            ds._mark_stub(repo, "stub/dep-a", "reflog-recovery")
            desc = _run(repo, "config", "branch.stub/dep-a.description").stdout
            self.assertIn("source=reflog-recovery", desc)


class SynthesizeTest(unittest.TestCase):
    def test_identity_stub_is_created_from_base(self):
        with _Repo() as repo:
            result = ds.synthesize_stub(repo, "dep-a", "main")
        # No remote, no reflog for a branch that never existed, no template.
        self.assertIsNotNone(result)
        self.assertEqual(result["source"], "identity")
        self.assertEqual(result["stub_branch"], "stub/dep-a")

    def test_no_stub_when_the_real_branch_exists(self):
        with _Repo() as repo:
            _run(repo, "branch", "agent/dep-a", "main")
            self.assertIsNone(ds.synthesize_stub(repo, "dep-a", "main"))

    def test_a_fresh_stub_is_reused_not_recreated(self):
        with _Repo() as repo:
            first = ds.synthesize_stub(repo, "dep-a", "main")
            second = ds.synthesize_stub(repo, "dep-a", "main")
        self.assertEqual(second["source"], "cached")
        self.assertEqual(second["commit"], first["commit"])

    def test_disabled_synthesizes_nothing(self):
        with _Repo() as repo:
            with patch.object(ds, "_ENABLED", False):
                self.assertIsNone(ds.synthesize_stub(repo, "dep-a", "main"))
            self.assertNotIn("stub/dep-a", _branches(repo))

    def test_missing_repo_is_fail_soft(self):
        self.assertIsNone(ds.synthesize_stub("/nope/not/here", "dep-a", "main"))
        self.assertIsNone(ds.synthesize_stub(None, "dep-a", "main"))

    def test_a_synthesized_stub_is_marked_as_one(self):
        with _Repo() as repo:
            ds.synthesize_stub(repo, "dep-a", "main")
            self.assertTrue(ds.is_stub(repo, "stub/dep-a"))


class CleanupTest(unittest.TestCase):
    """The destructive path: what gets `git branch -D`, and what must not."""

    def test_superseded_stub_is_removed(self):
        with _Repo() as repo:
            ds.synthesize_stub(repo, "dep-a", "main")
            _run(repo, "branch", "agent/dep-a", "main")      # the real branch lands
            removed = ds.cleanup_stubs(repo)
        self.assertEqual(removed, [("stub/dep-a", "superseded")])

    def test_the_real_branch_is_never_deleted(self):
        with _Repo() as repo:
            ds.synthesize_stub(repo, "dep-a", "main")
            _run(repo, "branch", "agent/dep-a", "main")
            ds.cleanup_stubs(repo)
            self.assertIn("agent/dep-a", _branches(repo))
            self.assertNotIn("stub/dep-a", _branches(repo))

    def test_stale_stub_is_removed(self):
        with _Repo() as repo:
            _run(repo, "branch", "stub/dep-a", "main")
            _run(repo, "config", "branch.stub/dep-a.description",
                 f"{ds._STUB_MARKER} source=identity created={int(time.time()) - 999999}")
            removed = ds.cleanup_stubs(repo)
        self.assertEqual(removed, [("stub/dep-a", "stale")])

    def test_fresh_unsuperseded_stub_is_kept(self):
        with _Repo() as repo:
            ds.synthesize_stub(repo, "dep-a", "main")
            removed = ds.cleanup_stubs(repo)
            self.assertEqual(removed, [])
            self.assertIn("stub/dep-a", _branches(repo))

    def test_non_stub_branches_are_never_touched(self):
        with _Repo() as repo:
            _run(repo, "branch", "agent/other", "main")
            _run(repo, "branch", "hotfix/thing", "main")
            ds.cleanup_stubs(repo)
        # main is the checked-out branch and cannot be deleted anyway; assert the rest.
            self.assertIn("agent/other", _branches(repo))
            self.assertIn("hotfix/thing", _branches(repo))

    def test_cleanup_on_a_bad_repo_is_fail_soft(self):
        self.assertEqual(ds.cleanup_stubs("/nope/not/here"), [])


class ResolveDepsTest(unittest.TestCase):
    def test_no_deps_is_a_no_op(self):
        with _Repo() as repo:
            out = ds.resolve_deps_with_stubs(repo, {"deps": []}, "main")
        self.assertEqual(out, {"resolved": [], "failed": [], "stubs_created": []})

    def test_missing_deps_key_is_a_no_op(self):
        with _Repo() as repo:
            out = ds.resolve_deps_with_stubs(repo, {}, "main")
        self.assertEqual(out["resolved"], [])

    def test_an_existing_dep_needs_no_stub(self):
        with _Repo() as repo:
            _run(repo, "branch", "agent/dep-a", "main")
            out = ds.resolve_deps_with_stubs(repo, {"deps": ["dep-a"]}, "main")
        self.assertEqual(out["resolved"], ["dep-a"])
        self.assertEqual(out["stubs_created"], [])

    def test_a_missing_dep_is_stubbed_and_counted_resolved(self):
        with _Repo() as repo:
            out = ds.resolve_deps_with_stubs(repo, {"deps": ["dep-a"]}, "main")
        self.assertEqual(out["resolved"], ["dep-a"])
        self.assertEqual(len(out["stubs_created"]), 1)
        self.assertEqual(out["stubs_created"][0]["dep"], "dep-a")

    def test_a_dep_that_cannot_be_stubbed_is_reported_failed(self):
        with _Repo() as repo:
            with patch.object(ds, "synthesize_stub", return_value=None):
                out = ds.resolve_deps_with_stubs(repo, {"deps": ["dep-a"]}, "main")
        self.assertEqual(out["failed"], ["dep-a"])
        self.assertEqual(out["resolved"], [])

    def test_mixed_deps_are_partitioned(self):
        with _Repo() as repo:
            _run(repo, "branch", "agent/have", "main")
            out = ds.resolve_deps_with_stubs(repo, {"deps": ["have", "missing"]}, "main")
        self.assertEqual(sorted(out["resolved"]), ["have", "missing"])
        self.assertEqual([s["dep"] for s in out["stubs_created"]], ["missing"])


class PatchTemplateGateTest(unittest.TestCase):
    """The hasattr gate that made source 3 dead code."""

    def test_patch_templates_is_importable(self):
        self.assertIsNotNone(ds.patch_templates)

    def test_no_template_means_no_commit(self):
        with _Repo() as repo:
            with patch.object(ds.patch_templates, "find_template", return_value={},
                              create=True):
                self.assertIsNone(ds._try_patch_template(repo, "dep-a", "main"))

    def test_a_template_without_a_diff_is_skipped(self):
        with _Repo() as repo:
            with patch.object(ds.patch_templates, "find_template",
                              return_value={"slug": "dep-a", "body": "scaffold"},
                              create=True):
                self.assertIsNone(ds._try_patch_template(repo, "dep-a", "main"))


class StatsTest(unittest.TestCase):
    def test_stats_reports_the_toggle_and_ttl(self):
        s = ds.stats()
        self.assertIn("enabled", s)
        self.assertIsInstance(s["ttl_s"], int)


if __name__ == "__main__":
    unittest.main(verbosity=2)
