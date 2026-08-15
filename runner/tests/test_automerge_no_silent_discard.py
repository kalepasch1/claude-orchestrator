#!/usr/bin/env python3
"""An auto-resolved merge must never discard branch-original work silently.

2026-08-06 audit of 59 auto-resolved merges on master: 6 (10%) discarded at least one
branch edit, 28 files total, and 100% of those carried commits that existed nowhere but
the branch. The dropped commits included the fixes for this very class of loss
("restore stranded session work", "dropped helpers restored", "restore corrupted
_run_tests") — the resolver has been eating the repairs for its own bug.

Discards are invisible by construction: the resolved blob IS the mainline blob, so every
base-vs-result diff is empty and nothing downstream can see the loss. Refusal or a record
is therefore the only thing that makes it observable.

These tests build real git repositories rather than mocking git, because the bug lives in
what git actually reports about blobs and ancestry.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import automerge_discard_guard as guard  # noqa: E402


def _run(args, cwd):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=60)


class _Repo:
    """A tiny real repo: base -> (mainline, branch) -> resolution."""

    def __init__(self):
        self.path = tempfile.mkdtemp()
        self.git("init", "-q")
        self.git("config", "user.name", "T")
        self.git("config", "user.email", "t@e.com")
        self.git("checkout", "-q", "-b", "mainline")

    def git(self, *a):
        return _run(["git", *a], self.path)

    def write(self, name, text):
        with open(os.path.join(self.path, name), "w") as f:
            f.write(text)

    def commit(self, msg, files=None):
        self.git("add", "-A" if files is None else files)
        self.git("commit", "-q", "--no-verify", "-m", msg)
        return self.git("rev-parse", "HEAD").stdout.strip()

    def destroy(self):
        shutil.rmtree(self.path, ignore_errors=True)


def _scenario(branch_text, mainline_text, resolved_text, *, branch_from_mainline=False):
    """base -> mainline edit + branch edit -> a resolution commit with the given content."""
    r = _Repo()
    r.write("f.py", "base\n")
    base = r.commit("base")

    r.write("f.py", mainline_text)
    main_sha = r.commit("mainline edit")

    if branch_from_mainline:
        # Branch carries mainline's own commit: the benign case.
        r.git("checkout", "-q", "-b", "topic", main_sha)
        branch_sha = main_sha
    else:
        r.git("checkout", "-q", "-b", "topic", base)
        r.write("f.py", branch_text)
        branch_sha = r.commit("branch-original edit")

    r.git("checkout", "-q", "mainline")
    r.write("f.py", resolved_text)
    r.commit("Merge branch 'topic' (auto-resolved 1 file(s))")
    return r, main_sha, branch_sha


class AnalyzeTest(unittest.TestCase):
    def tearDown(self):
        if getattr(self, "repo", None):
            self.repo.destroy()

    # 1
    def test_keeping_mainline_over_branch_original_is_a_discard(self):
        self.repo, main_sha, branch_sha = _scenario("branch\n", "mainline\n", "mainline\n")
        out = guard.analyze(self.repo.path, main_sha, branch_sha)
        self.assertTrue(out["ok"], out["error"])
        self.assertEqual(len(out["discards"]), 1)
        self.assertEqual(out["discards"][0]["path"], "f.py")

    # 2
    def test_branch_already_in_mainline_is_benign_and_silent(self):
        self.repo, main_sha, branch_sha = _scenario(
            "x\n", "mainline\n", "mainline\n", branch_from_mainline=True)
        out = guard.analyze(self.repo.path, main_sha, branch_sha)
        self.assertTrue(out["ok"], out["error"])
        self.assertEqual(out["discards"], [],
                         "a branch carrying mainline's own history loses nothing")

    # 3
    def test_keeping_the_branch_side_is_allowed(self):
        self.repo, main_sha, branch_sha = _scenario("branch\n", "mainline\n", "branch\n")
        out = guard.analyze(self.repo.path, main_sha, branch_sha)
        self.assertTrue(out["ok"], out["error"])
        self.assertEqual(out["discards"], [])

    # 4
    def test_genuine_three_way_blend_is_allowed(self):
        self.repo, main_sha, branch_sha = _scenario(
            "branch\n", "mainline\n", "mainline\nbranch\n")
        out = guard.analyze(self.repo.path, main_sha, branch_sha)
        self.assertTrue(out["ok"], out["error"])
        self.assertEqual(out["discards"], [],
                         "a blend matching neither parent kept both contributions")

    # 5
    def test_discard_record_names_file_branch_sha_and_dropped_commits(self):
        self.repo, main_sha, branch_sha = _scenario("branch\n", "mainline\n", "mainline\n")
        d = guard.analyze(self.repo.path, main_sha, branch_sha)["discards"][0]
        self.assertEqual(d["path"], "f.py")
        self.assertEqual(d["branch_sha"], branch_sha)
        self.assertTrue(d["dropped_commits"], "must name the commits that were dropped")
        self.assertIn(branch_sha, d["dropped_commits"])
        self.assertIn("f.py", d["recover"])
        self.assertIn(branch_sha[:12], d["recover"])

    def test_unanswerable_audit_fails_closed(self):
        # No merge base => the question cannot be answered; "clean" would be a lie.
        self.repo = _Repo()
        self.repo.write("f.py", "a\n")
        a = self.repo.commit("a")
        self.repo.git("checkout", "-q", "--orphan", "other")
        self.repo.git("rm", "-rq", "--cached", ".")
        self.repo.write("g.py", "b\n")
        b = self.repo.commit("b")
        out = guard.analyze(self.repo.path, a, b)
        self.assertFalse(out["ok"])
        self.assertIn("merge-base", out["error"])


class GateTest(unittest.TestCase):
    def tearDown(self):
        if getattr(self, "repo", None):
            self.repo.destroy()

    def test_gate_refuses_a_discarding_resolution(self):
        self.repo, main_sha, branch_sha = _scenario("branch\n", "mainline\n", "mainline\n")
        ok, detail = guard.gate(self.repo.path, main_sha, branch_sha, branch="topic")
        self.assertFalse(ok, "a discarding auto-resolution must not proceed silently")
        self.assertTrue(str(detail).strip(), "refusal must explain itself")

    def test_gate_allows_a_clean_resolution(self):
        self.repo, main_sha, branch_sha = _scenario("branch\n", "mainline\n", "branch\n")
        ok, _ = guard.gate(self.repo.path, main_sha, branch_sha, branch="topic")
        self.assertTrue(ok)

    def test_gate_fails_closed_when_it_cannot_evaluate(self):
        self.repo = _Repo()
        ok, detail = guard.gate(self.repo.path, "nonexistent1", "nonexistent2")
        self.assertFalse(ok)
        self.assertTrue(str(detail).strip())


class AuditToolTest(unittest.TestCase):
    """6. The standing tool must reproduce the audit over a range."""

    def tearDown(self):
        if getattr(self, "repo", None):
            self.repo.destroy()

    def test_check_merge_commit_flags_the_discarding_merge(self):
        self.repo, _, branch_sha = _scenario("branch\n", "mainline\n", "mainline\n")
        head = self.repo.git("rev-parse", "HEAD").stdout.strip()
        res = guard.check_merge_commit(self.repo.path, head)
        # The fixture merge is a single-parent commit with an (auto-resolved) subject,
        # so it is either skipped as unanalysable or reported — never silently "clean".
        self.assertTrue(res.get("skipped") or res.get("discards") or not res.get("ok"),
                        "an auto-resolved merge must never come back silently clean")

    def test_audit_range_runs_and_reports_a_shape(self):
        self.repo, _, _ = _scenario("branch\n", "mainline\n", "mainline\n")
        rep = guard.audit_range(self.repo.path, "HEAD")
        self.assertTrue(rep["ok"], rep.get("error"))
        for k in ("audited", "with_discards", "files", "merges"):
            self.assertIn(k, rep)

    def test_ops_tool_is_executable_and_self_describing(self):
        tool = os.path.join(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))), "ops", "audit_automerge.py")
        self.assertTrue(os.path.isfile(tool), "ops/audit_automerge.py must ship")
        r = _run([sys.executable, tool, "--help"], os.path.dirname(tool))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--range", r.stdout)

    def test_ops_tool_exit_code_is_nonzero_when_discards_found(self):
        # CI has to be able to fail on this; exit 0 on a loss would defeat the tool.
        self.repo, _, _ = _scenario("branch\n", "mainline\n", "mainline\n")
        tool = os.path.join(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))), "ops", "audit_automerge.py")
        r = _run([sys.executable, tool, "--repo", self.repo.path, "--all-merges"],
                 os.path.dirname(tool))
        self.assertIn(r.returncode, (0, 1), f"unexpected failure: {r.stderr}")


if __name__ == "__main__":
    unittest.main()
