#!/usr/bin/env python3
"""Canary ollama-3-17 slice 1: patch_template_apply — apply patch template bf2a3f19ec30.

Covers the template-apply helper end-to-end (real git repos) plus fail-soft
edge cases, and regression-guards the patch_recovery method-3 wiring: the
found similar diff must be applied, not the missing task's own stored patch.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import patch_template_apply as pta

SLUG = "canary-ollama-3-17-slice-1"
BASE = "main"

_GIT_ENV = {
    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    "HOME": os.environ.get("HOME", ""),
    "GIT_AUTHOR_NAME": "kalepasch1",
    "GIT_AUTHOR_EMAIL": "kalepasch@gmail.com",
    "GIT_COMMITTER_NAME": "kalepasch1",
    "GIT_COMMITTER_EMAIL": "kalepasch@gmail.com",
}


def _run(args, cwd, **kw):
    return subprocess.run(args, cwd=cwd, env=_GIT_ENV, capture_output=True,
                          text=True, **kw)


def _make_repo(parent):
    """Create a real git repo with one commit on `main`."""
    repo = os.path.join(parent, "repo")
    os.makedirs(repo)
    _run(["git", "init"], repo)
    with open(os.path.join(repo, "hello.txt"), "w") as f:
        f.write("line one\nline two\nline three\n")
    _run(["git", "add", "-A"], repo)
    _run(["git", "commit", "--no-verify", "-m", "initial"], repo)
    _run(["git", "branch", "-M", BASE], repo)
    return repo


def _diff_from_edit(repo, relpath, new_content):
    """Produce a real unified diff by editing a tracked file, then reverting."""
    path = os.path.join(repo, relpath)
    with open(path, "w") as f:
        f.write(new_content)
    diff = _run(["git", "diff"], repo).stdout
    _run(["git", "checkout", "--", relpath], repo)
    return diff


def _diff_new_file(repo, relpath, content):
    """Produce a real diff that adds a new file, then revert the index."""
    path = os.path.join(repo, relpath)
    with open(path, "w") as f:
        f.write(content)
    _run(["git", "add", relpath], repo)
    diff = _run(["git", "diff", "--cached"], repo).stdout
    _run(["git", "reset", "HEAD", relpath], repo)
    os.remove(path)
    return diff


def _branch_exists(repo, branch):
    return _run(["git", "rev-parse", "--verify", branch], repo).returncode == 0


class _RepoTest(unittest.TestCase):
    """Base: fresh tmp repo per test, stats reset."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pta-test-")
        self.repo = _make_repo(self.tmp)
        pta.reset_stats()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


# ── looks_like_diff ──────────────────────────────────────────────────────────

class LooksLikeDiffTest(unittest.TestCase):
    def test_git_diff_header_accepted(self):
        self.assertTrue(pta.looks_like_diff(
            "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b\n"))

    def test_unified_header_accepted(self):
        self.assertTrue(pta.looks_like_diff(
            "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b\n"))

    def test_prose_rejected(self):
        self.assertFalse(pta.looks_like_diff(
            "please change line two of hello.txt to say line 2 instead"))

    def test_none_rejected(self):
        self.assertFalse(pta.looks_like_diff(None))

    def test_empty_rejected(self):
        self.assertFalse(pta.looks_like_diff(""))

    def test_too_short_rejected(self):
        self.assertFalse(pta.looks_like_diff("@@ -1 "))

    def test_non_string_rejected(self):
        self.assertFalse(pta.looks_like_diff(b"diff --git a/x b/x"))
        self.assertFalse(pta.looks_like_diff({"diff": "x"}))


# ── fail-soft input validation (no git repo needed) ──────────────────────────

class FailSoftInputTest(unittest.TestCase):
    def setUp(self):
        pta.reset_stats()

    def test_none_patch_fails_soft(self):
        r = pta.apply_patch_template("/nonexistent", SLUG, BASE, None)
        self.assertFalse(r["ok"])

    def test_empty_patch_fails_soft(self):
        r = pta.apply_patch_template("/nonexistent", SLUG, BASE, "")
        self.assertFalse(r["ok"])

    def test_none_repo_fails_soft(self):
        r = pta.apply_patch_template(None, SLUG, BASE, "diff --git a/x b/x\n")
        self.assertFalse(r["ok"])
        self.assertIn("repo", r["reason"])

    def test_missing_repo_dir_fails_soft(self):
        r = pta.apply_patch_template("/no/such/dir", SLUG, BASE,
                                     "diff --git a/x b/x\n--- a/x\n+++ b/x\n")
        self.assertFalse(r["ok"])
        self.assertIn("repo", r["reason"])

    def test_no_slug_and_no_branch_fails_soft(self):
        r = pta.apply_patch_template("/tmp", "", BASE, "diff --git a/x b/x\n")
        self.assertFalse(r["ok"])
        self.assertIn("slug", r["reason"])

    def test_none_base_fails_soft(self):
        r = pta.apply_patch_template("/tmp", SLUG, None, "diff --git a/x b/x\n")
        self.assertFalse(r["ok"])
        self.assertIn("base", r["reason"])

    def test_result_shape_on_failure(self):
        r = pta.apply_patch_template(None, SLUG, BASE, None)
        self.assertIn("ok", r)
        self.assertIn("method", r)
        self.assertIn("branch", r)
        self.assertIn("reason", r)

    def test_reason_truncated(self):
        r = pta.apply_patch_template("/no/" + "x" * 600, SLUG, BASE,
                                     "diff --git a/x b/x\n--- a/x\n+++ b/x\n")
        self.assertLessEqual(len(r["reason"]), pta.REASON_MAX_CHARS)

    def test_never_raises_on_garbage(self):
        for bad in (None, "", 0, 3.14, [], {}, b"bytes", object()):
            pta.apply_patch_template(bad, bad, bad, bad)  # must not raise

    def test_default_branch_name_from_slug(self):
        r = pta.apply_patch_template(None, SLUG, BASE, None)
        self.assertEqual(r["branch"], f"agent/{SLUG}")

    def test_explicit_branch_honored_in_result(self):
        r = pta.apply_patch_template(None, SLUG, BASE, None, branch="custom/b")
        self.assertEqual(r["branch"], "custom/b")

    def test_method_label_propagated(self):
        r = pta.apply_patch_template(None, SLUG, BASE, None, method="cache_replay")
        self.assertEqual(r["method"], "cache_replay")


# ── stats ────────────────────────────────────────────────────────────────────

class StatsTest(unittest.TestCase):
    def setUp(self):
        pta.reset_stats()

    def test_failed_attempt_counted(self):
        pta.apply_patch_template(None, SLUG, BASE, None)
        s = pta.stats()
        self.assertEqual(s["attempted"], 1)
        self.assertEqual(s["failed"], 1)
        self.assertEqual(s["applied"], 0)

    def test_reset_stats_zeroes(self):
        pta.apply_patch_template(None, SLUG, BASE, None)
        pta.reset_stats()
        self.assertEqual(pta.stats(), {"attempted": 0, "applied": 0, "failed": 0})

    def test_stats_returns_copy(self):
        snap = pta.stats()
        snap["attempted"] = 999
        self.assertEqual(pta.stats()["attempted"], 0)


# ── real-git integration ─────────────────────────────────────────────────────

class ApplyHappyPathTest(_RepoTest):
    def test_valid_diff_applies_and_commits(self):
        diff = _diff_from_edit(self.repo, "hello.txt",
                               "line one\nline 2\nline three\n")
        r = pta.apply_patch_template(self.repo, SLUG, BASE, diff)
        self.assertTrue(r["ok"], r.get("reason"))
        self.assertEqual(r["branch"], f"agent/{SLUG}")
        self.assertTrue(_branch_exists(self.repo, f"agent/{SLUG}"))

    def test_branch_is_ahead_of_base(self):
        diff = _diff_from_edit(self.repo, "hello.txt",
                               "line one\nline 2\nline three\n")
        pta.apply_patch_template(self.repo, SLUG, BASE, diff)
        ahead = _run(["git", "rev-list", "--count", f"{BASE}..agent/{SLUG}"],
                     self.repo).stdout.strip()
        self.assertEqual(ahead, "1")

    def test_applied_content_on_branch(self):
        diff = _diff_from_edit(self.repo, "hello.txt",
                               "line one\nline 2\nline three\n")
        pta.apply_patch_template(self.repo, SLUG, BASE, diff)
        blob = _run(["git", "show", f"agent/{SLUG}:hello.txt"], self.repo).stdout
        self.assertIn("line 2", blob)

    def test_new_file_diff_applies(self):
        diff = _diff_new_file(self.repo, "added.txt", "new content\n")
        r = pta.apply_patch_template(self.repo, SLUG, BASE, diff)
        self.assertTrue(r["ok"], r.get("reason"))
        blob = _run(["git", "show", f"agent/{SLUG}:added.txt"], self.repo).stdout
        self.assertIn("new content", blob)

    def test_stale_branch_replaced(self):
        _run(["git", "branch", f"agent/{SLUG}", BASE], self.repo)
        diff = _diff_from_edit(self.repo, "hello.txt",
                               "line one\nline 2\nline three\n")
        r = pta.apply_patch_template(self.repo, SLUG, BASE, diff)
        self.assertTrue(r["ok"], r.get("reason"))
        ahead = _run(["git", "rev-list", "--count", f"{BASE}..agent/{SLUG}"],
                     self.repo).stdout.strip()
        self.assertEqual(ahead, "1")

    def test_success_counts_applied(self):
        diff = _diff_from_edit(self.repo, "hello.txt",
                               "line one\nline 2\nline three\n")
        pta.apply_patch_template(self.repo, SLUG, BASE, diff)
        self.assertEqual(pta.stats()["applied"], 1)

    def test_worktree_cleaned_up_after_success(self):
        diff = _diff_from_edit(self.repo, "hello.txt",
                               "line one\nline 2\nline three\n")
        pta.apply_patch_template(self.repo, SLUG, BASE, diff)
        wt_dir = os.path.join(self.tmp, "repo-wt")
        leftovers = os.listdir(wt_dir) if os.path.isdir(wt_dir) else []
        self.assertEqual(leftovers, [])


class ApplyFailurePathTest(_RepoTest):
    def test_conflicting_diff_fails_soft(self):
        diff = ("diff --git a/hello.txt b/hello.txt\n"
                "index 0000000..1111111 100644\n"
                "--- a/hello.txt\n"
                "+++ b/hello.txt\n"
                "@@ -1,3 +1,3 @@\n"
                " totally different\n"
                "-context that does not exist\n"
                "+replacement\n"
                " also missing\n")
        r = pta.apply_patch_template(self.repo, SLUG, BASE, diff)
        self.assertFalse(r["ok"])

    def test_unknown_base_fails_soft(self):
        diff = _diff_from_edit(self.repo, "hello.txt",
                               "line one\nline 2\nline three\n")
        r = pta.apply_patch_template(self.repo, SLUG, "no-such-base", diff)
        self.assertFalse(r["ok"])
        self.assertIn("branch create failed", r["reason"])

    def test_worktree_cleaned_up_after_failure(self):
        r = pta.apply_patch_template(
            self.repo, SLUG, BASE,
            "diff --git a/nope.txt b/nope.txt\n--- a/nope.txt\n+++ b/nope.txt\n"
            "@@ -1 +1 @@\n-missing\n+still missing\n")
        self.assertFalse(r["ok"])
        wt_dir = os.path.join(self.tmp, "repo-wt")
        leftovers = os.listdir(wt_dir) if os.path.isdir(wt_dir) else []
        self.assertEqual(leftovers, [])

    def test_failure_does_not_raise_and_counts_failed(self):
        pta.apply_patch_template(self.repo, SLUG, BASE, "not a diff at all")
        self.assertEqual(pta.stats()["failed"], 1)


# ── patch_recovery method-3 wiring regression ────────────────────────────────

class PatchRecoveryWiringTest(unittest.TestCase):
    """Regression: _template_adaptation used to call a nonexistent
    _apply_patch_to_branch (NameError swallowed → method 3 was dead code)."""

    def test_apply_patch_to_branch_is_defined(self):
        import patch_recovery
        self.assertTrue(callable(getattr(patch_recovery, "_apply_patch_to_branch", None)))

    def test_delegates_found_template_to_apply(self):
        import patch_recovery
        with patch.object(pta, "apply_patch_template",
                          return_value={"ok": True, "method": "template",
                                        "branch": "agent/xyz"}) as ap:
            r = patch_recovery._apply_patch_to_branch(
                "/repo", "diff --git a/x b/x\n", "agent/xyz", BASE)
        self.assertTrue(r["ok"])
        args, kwargs = ap.call_args
        self.assertEqual(args[0], "/repo")
        self.assertEqual(args[1], "xyz")          # slug derived from branch
        self.assertEqual(args[2], BASE)
        self.assertEqual(args[3], "diff --git a/x b/x\n")  # the FOUND diff
        self.assertEqual(kwargs.get("branch"), "agent/xyz")

    def test_branch_without_slash_still_works(self):
        import patch_recovery
        with patch.object(pta, "apply_patch_template",
                          return_value={"ok": False, "method": "template",
                                        "branch": "bare", "reason": "x"}) as ap:
            patch_recovery._apply_patch_to_branch("/repo", "d", "bare", BASE)
        self.assertEqual(ap.call_args[0][1], "bare")


if __name__ == "__main__":
    unittest.main()
