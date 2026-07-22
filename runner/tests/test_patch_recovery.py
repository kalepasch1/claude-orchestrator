#!/usr/bin/env python3
"""Tests for branch-detection and regeneration utilities in patch_recovery.py."""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import patch_recovery as pr

REPO = "/fake/repo"
SLUG = "fix-widget-border"
BRANCH = f"agent/{SLUG}"
BASE = "master"


def _proc(returncode=0, stdout="", stderr=""):
    p = MagicMock()
    p.returncode = returncode
    p.stdout = stdout
    p.stderr = stderr
    return p


# ---------------------------------------------------------------------------
# detect_branch
# ---------------------------------------------------------------------------

class DetectBranchLocalTest(unittest.TestCase):
    def test_found_locally(self):
        with patch.object(pr, "_git") as g:
            g.side_effect = [
                _proc(0, f"  {BRANCH}\n"),  # branch --list
            ]
            result = pr.detect_branch(REPO, SLUG)
        self.assertTrue(result["found"])
        self.assertEqual(result["location"], "local")
        self.assertEqual(result["branch"], BRANCH)
        self.assertIsNone(result["path"])

    def test_not_found_locally_falls_through_to_worktree(self):
        wt_output = (
            f"worktree /fake/repo-wt/other\n"
            f"HEAD abc123\n"
            f"branch refs/heads/other-branch\n"
            f"\n"
        )
        with patch.object(pr, "_git") as g:
            g.side_effect = [
                _proc(0, ""),        # branch --list: empty
                _proc(0, wt_output), # worktree list --porcelain
            ]
            result = pr.detect_branch(REPO, SLUG)
        self.assertFalse(result["found"])
        self.assertIsNone(result["location"])

    def test_not_found_anywhere(self):
        with patch.object(pr, "_git") as g:
            g.side_effect = [
                _proc(0, ""),  # branch --list: empty
                _proc(0, ""),  # worktree list: empty
            ]
            result = pr.detect_branch(REPO, SLUG)
        self.assertFalse(result["found"])
        self.assertIsNone(result["location"])
        self.assertIsNone(result["path"])
        self.assertEqual(result["branch"], BRANCH)


class DetectBranchWorktreeTest(unittest.TestCase):
    def _wt_output(self, branch_name, wt_path="/fake/wt/fix-widget-border"):
        return (
            f"worktree {wt_path}\n"
            f"HEAD def456\n"
            f"branch refs/heads/{branch_name}\n"
            f"\n"
        )

    def test_found_in_worktree(self):
        wt_path = f"/fake/wt/{SLUG}"
        with patch.object(pr, "_git") as g:
            g.side_effect = [
                _proc(0, ""),                              # branch --list: empty
                _proc(0, self._wt_output(BRANCH, wt_path)),
            ]
            result = pr.detect_branch(REPO, SLUG)
        self.assertTrue(result["found"])
        self.assertEqual(result["location"], "worktree")
        self.assertEqual(result["path"], wt_path)

    def test_worktree_with_multiple_entries_picks_correct_one(self):
        wt_output = (
            "worktree /fake/wt/other\n"
            "HEAD aaa\n"
            "branch refs/heads/agent/other-task\n"
            "\n"
            f"worktree /fake/wt/{SLUG}\n"
            "HEAD bbb\n"
            f"branch refs/heads/{BRANCH}\n"
            "\n"
        )
        with patch.object(pr, "_git") as g:
            g.side_effect = [
                _proc(0, ""),
                _proc(0, wt_output),
            ]
            result = pr.detect_branch(REPO, SLUG)
        self.assertTrue(result["found"])
        self.assertEqual(result["location"], "worktree")
        self.assertEqual(result["path"], f"/fake/wt/{SLUG}")

    def test_worktree_list_failure_returns_not_found(self):
        with patch.object(pr, "_git") as g:
            g.side_effect = [
                _proc(0, ""),   # branch --list: empty
                _proc(1, ""),   # worktree list: fails
            ]
            result = pr.detect_branch(REPO, SLUG)
        self.assertFalse(result["found"])

    def test_branch_list_failure_still_checks_worktrees(self):
        wt_path = f"/fake/wt/{SLUG}"
        with patch.object(pr, "_git") as g:
            g.side_effect = [
                _proc(1, ""),  # branch --list: fails
                _proc(0, f"worktree {wt_path}\nHEAD abc\nbranch refs/heads/{BRANCH}\n\n"),
            ]
            result = pr.detect_branch(REPO, SLUG)
        self.assertTrue(result["found"])
        self.assertEqual(result["location"], "worktree")


# ---------------------------------------------------------------------------
# query_cache_hints
# ---------------------------------------------------------------------------

class QueryCacheHintsArtifactTest(unittest.TestCase):
    def test_exact_artifact_hit_returns_similarity_one(self):
        art = {"patch_diff": "diff --git a/foo.py b/foo.py\n+x = 1\n", "slug": SLUG}
        ta = MagicMock()
        ta.get_artifacts.return_value = art
        with patch.dict(sys.modules, {"task_artifacts": ta}), \
             patch.object(pr, "db") as mdb:
            mdb.select.return_value = []
            hints = pr.query_cache_hints(SLUG)
        self.assertEqual(len(hints), 1)
        self.assertEqual(hints[0]["source"], "task_artifacts")
        self.assertEqual(hints[0]["similarity"], 1.0)
        self.assertIn("diff --git", hints[0]["patch_diff"])

    def test_empty_artifact_diff_skipped(self):
        ta = MagicMock()
        ta.get_artifacts.return_value = {"patch_diff": "   "}
        with patch.dict(sys.modules, {"task_artifacts": ta}), \
             patch.object(pr, "db") as mdb:
            mdb.select.return_value = []
            hints = pr.query_cache_hints(SLUG)
        self.assertEqual(hints, [])

    def test_missing_artifact_returns_empty(self):
        ta = MagicMock()
        ta.get_artifacts.return_value = None
        with patch.dict(sys.modules, {"task_artifacts": ta}), \
             patch.object(pr, "db") as mdb:
            mdb.select.return_value = []
            hints = pr.query_cache_hints(SLUG)
        self.assertEqual(hints, [])

    def test_artifact_exception_degrades_gracefully(self):
        ta = MagicMock()
        ta.get_artifacts.side_effect = RuntimeError("db down")
        with patch.dict(sys.modules, {"task_artifacts": ta}), \
             patch.object(pr, "db") as mdb:
            mdb.select.return_value = []
            hints = pr.query_cache_hints(SLUG)
        self.assertEqual(hints, [])


class QueryCacheHintsMergedDiffTest(unittest.TestCase):
    def test_merged_diff_hit_included(self):
        mdl = MagicMock()
        mdl.find.return_value = [{
            "slug": "similar-task", "similarity": 0.72,
            "diff": "diff --git a/bar.py\n+y = 2\n",
            "summary": "fix widget border radius",
        }]
        ta = MagicMock()
        ta.get_artifacts.return_value = None
        with patch.dict(sys.modules, {"task_artifacts": ta, "merged_diff_library": mdl}), \
             patch.object(pr, "db") as mdb:
            mdb.select.return_value = []
            hints = pr.query_cache_hints(SLUG, intent_words=["widget", "border"])
        merged = [h for h in hints if h["source"] == "merged_diff"]
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["slug"], "similar-task")
        self.assertAlmostEqual(merged[0]["similarity"], 0.72)

    def test_no_intent_words_skips_merged_diff(self):
        mdl = MagicMock()
        ta = MagicMock()
        ta.get_artifacts.return_value = None
        with patch.dict(sys.modules, {"task_artifacts": ta, "merged_diff_library": mdl}), \
             patch.object(pr, "db") as mdb:
            mdb.select.return_value = []
            pr.query_cache_hints(SLUG)
        mdl.find.assert_not_called()

    def test_merged_diff_exception_degrades_gracefully(self):
        mdl = MagicMock()
        mdl.find.side_effect = RuntimeError("network error")
        ta = MagicMock()
        ta.get_artifacts.return_value = None
        with patch.dict(sys.modules, {"task_artifacts": ta, "merged_diff_library": mdl}), \
             patch.object(pr, "db") as mdb:
            mdb.select.return_value = []
            hints = pr.query_cache_hints(SLUG, intent_words=["widget"])
        self.assertEqual(hints, [])


class QueryCacheHintsKnowledgeTest(unittest.TestCase):
    def test_knowledge_hit_scored_by_keyword_overlap(self):
        ta = MagicMock()
        ta.get_artifacts.return_value = None
        krow = {"title": "patch template fix-widget",
                "body": "fix widget border style",
                "keywords": ["widget", "border", "style"]}
        with patch.dict(sys.modules, {"task_artifacts": ta}), \
             patch.object(pr, "db") as mdb:
            mdb.select.return_value = [krow]
            hints = pr.query_cache_hints(SLUG, intent_words=["widget", "border", "style"])
        know = [h for h in hints if h["source"] == "knowledge"]
        self.assertTrue(len(know) >= 1)
        self.assertGreater(know[0]["similarity"], 0)

    def test_knowledge_no_overlap_excluded(self):
        ta = MagicMock()
        ta.get_artifacts.return_value = None
        krow = {"title": "patch template auth-flow",
                "body": "oauth token refresh",
                "keywords": ["oauth", "token", "refresh"]}
        with patch.dict(sys.modules, {"task_artifacts": ta}), \
             patch.object(pr, "db") as mdb:
            mdb.select.return_value = [krow]
            hints = pr.query_cache_hints(SLUG, intent_words=["widget", "border"])
        know = [h for h in hints if h["source"] == "knowledge"]
        self.assertEqual(know, [])

    def test_hints_sorted_by_similarity_descending(self):
        mdl = MagicMock()
        mdl.find.return_value = [
            {"slug": "low-sim", "similarity": 0.30, "diff": "diff\n+a", "summary": "low"},
            {"slug": "high-sim", "similarity": 0.85, "diff": "diff\n+b", "summary": "high"},
        ]
        ta = MagicMock()
        ta.get_artifacts.return_value = None
        with patch.dict(sys.modules, {"task_artifacts": ta, "merged_diff_library": mdl}), \
             patch.object(pr, "db") as mdb:
            mdb.select.return_value = []
            hints = pr.query_cache_hints(SLUG, intent_words=["widget"])
        sims = [h["similarity"] for h in hints]
        self.assertEqual(sims, sorted(sims, reverse=True))


# ---------------------------------------------------------------------------
# regenerate_from_intent
# ---------------------------------------------------------------------------

class RegenerateFromIntentCacheReplayTest(unittest.TestCase):
    def _art_hint(self):
        return {
            "source": "task_artifacts",
            "slug": SLUG,
            "similarity": 1.0,
            "patch_diff": "diff --git a/foo.py b/foo.py\n--- a/foo.py\n+++ b/foo.py\n+x = 1\n",
            "summary": "stored artifact",
        }

    def test_cache_replay_success(self):
        with patch.object(pr, "query_cache_hints", return_value=[self._art_hint()]), \
             patch.object(pr, "_apply_diff_to_branch",
                          return_value={"ok": True, "method": "cache_replay", "branch": BRANCH}):
            result = pr.regenerate_from_intent(REPO, SLUG, BASE, ["widget", "border"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["method"], "cache_replay")

    def test_cache_replay_failure_falls_back_to_stub(self):
        with patch.object(pr, "query_cache_hints", return_value=[self._art_hint()]), \
             patch.object(pr, "_apply_diff_to_branch",
                          return_value={"ok": False, "method": "cache_replay",
                                        "branch": BRANCH, "reason": "apply failed"}), \
             patch.object(pr, "_create_intent_stub",
                          return_value={"ok": True, "method": "intent_stub", "branch": BRANCH}) as stub:
            result = pr.regenerate_from_intent(REPO, SLUG, BASE, ["widget"])
        stub.assert_called_once()
        self.assertEqual(result["method"], "intent_stub")

    def test_no_hints_goes_straight_to_stub(self):
        with patch.object(pr, "query_cache_hints", return_value=[]), \
             patch.object(pr, "_create_intent_stub",
                          return_value={"ok": True, "method": "intent_stub", "branch": BRANCH}) as stub:
            result = pr.regenerate_from_intent(REPO, SLUG, BASE, [])
        stub.assert_called_once()
        self.assertTrue(result["ok"])

    def test_hints_with_empty_diff_skipped(self):
        empty_hint = {**self._art_hint(), "patch_diff": "   "}
        with patch.object(pr, "query_cache_hints", return_value=[empty_hint]), \
             patch.object(pr, "_create_intent_stub",
                          return_value={"ok": True, "method": "intent_stub", "branch": BRANCH}) as stub:
            pr.regenerate_from_intent(REPO, SLUG, BASE, ["widget"])
        stub.assert_called_once()

    def test_template_id_forwarded_to_stub(self):
        with patch.object(pr, "query_cache_hints", return_value=[]), \
             patch.object(pr, "_create_intent_stub",
                          return_value={"ok": True, "method": "intent_stub", "branch": BRANCH}) as stub:
            pr.regenerate_from_intent(REPO, SLUG, BASE, ["fix"], template_id="tmpl-abc")
        _, _, called_branch, called_base, _, tid = stub.call_args.args
        self.assertEqual(tid, "tmpl-abc")


class ApplyDiffToBranchTest(unittest.TestCase):
    DIFF = "diff --git a/foo.py b/foo.py\n--- a/foo.py\n+++ b/foo.py\n+x = 1\n"

    def _run_side_effect(self, git_apply_ok=True, commit_ok=True, ahead="1"):
        """Build a subprocess.run side-effect sequence for _apply_diff_to_branch.

        Calls in order: git apply, git add -A, git commit, git rev-list, git worktree remove.
        """
        return [
            _proc(0 if git_apply_ok else 1, stderr="apply err"),  # git apply
            _proc(0),                                               # git add -A
            _proc(0 if commit_ok else 1, stderr="commit err"),     # git commit
            _proc(0, stdout=ahead),                                 # git rev-list
            _proc(0),                                               # git worktree remove (finally)
        ]

    def test_success_path(self):
        with patch.object(pr, "_git", return_value=_proc(0)), \
             patch.object(pr, "_free_branch"), \
             patch("os.makedirs"), \
             patch("subprocess.run", side_effect=self._run_side_effect()):
            result = pr._apply_diff_to_branch(REPO, SLUG, BRANCH, BASE, self.DIFF, "task_artifacts")
        self.assertTrue(result["ok"])
        self.assertEqual(result["method"], "cache_replay")

    def test_worktree_add_failure(self):
        with patch.object(pr, "_git") as g, patch.object(pr, "_free_branch"), \
             patch("os.makedirs"), patch("subprocess.run", return_value=_proc(0)):
            g.side_effect = [
                _proc(0),  # branch -D
                _proc(0),  # branch <base>
                _proc(1, stderr="worktree fail"),  # worktree add
            ]
            result = pr._apply_diff_to_branch(REPO, SLUG, BRANCH, BASE, self.DIFF, "task_artifacts")
        self.assertFalse(result["ok"])
        self.assertIn("worktree setup failed", result["reason"])

    def test_diff_apply_failure(self):
        with patch.object(pr, "_git", return_value=_proc(0)), \
             patch.object(pr, "_free_branch"), \
             patch("os.makedirs"), \
             patch("subprocess.run", side_effect=[
                 _proc(1, stderr="patch rejected"),  # git apply
                 _proc(0),                            # worktree remove (finally)
             ]):
            result = pr._apply_diff_to_branch(REPO, SLUG, BRANCH, BASE, self.DIFF, "task_artifacts")
        self.assertFalse(result["ok"])
        self.assertIn("diff apply failed", result["reason"])

    def test_zero_ahead_commits_returns_failure(self):
        with patch.object(pr, "_git", return_value=_proc(0)), \
             patch.object(pr, "_free_branch"), \
             patch("os.makedirs"), \
             patch("subprocess.run", side_effect=[
                 _proc(0),          # git apply
                 _proc(0),          # git add -A
                 _proc(0),          # git commit
                 _proc(0, stdout="0\n"),  # rev-list count
                 _proc(0),          # worktree remove
             ]):
            result = pr._apply_diff_to_branch(REPO, SLUG, BRANCH, BASE, self.DIFF, "task_artifacts")
        self.assertFalse(result["ok"])
        self.assertIn("no commits", result["reason"])

    def test_worktree_always_removed_on_exception(self):
        rm_calls = []
        orig_run = __import__("subprocess").run

        def run_side(cmd, **kw):
            if isinstance(cmd, list) and cmd[:3] == ["git", "worktree", "remove"]:
                rm_calls.append(cmd)
                return _proc(0)
            raise RuntimeError("boom")

        with patch.object(pr, "_git", return_value=_proc(0)), \
             patch.object(pr, "_free_branch"), \
             patch("os.makedirs"), \
             patch("subprocess.run", side_effect=run_side):
            result = pr._apply_diff_to_branch(REPO, SLUG, BRANCH, BASE, self.DIFF, "task_artifacts")
        self.assertFalse(result["ok"])
        self.assertTrue(any("worktree" in str(c) for c in rm_calls))


class CreateIntentStubTest(unittest.TestCase):
    def test_success_creates_stub_branch(self):
        with patch.object(pr, "_free_branch"), \
             patch.object(pr, "_git", return_value=_proc(0)), \
             patch("os.path.join", wraps=os.path.join), \
             patch("builtins.open", unittest.mock.mock_open()), \
             patch("subprocess.run", return_value=_proc(0)):
            result = pr._create_intent_stub(REPO, SLUG, BRANCH, BASE,
                                            ["widget", "border"], template_id="t1")
        self.assertTrue(result["ok"])
        self.assertEqual(result["method"], "intent_stub")

    def test_commit_failure_returns_failed(self):
        with patch.object(pr, "_free_branch"), \
             patch.object(pr, "_git", return_value=_proc(0)), \
             patch("builtins.open", unittest.mock.mock_open()), \
             patch("subprocess.run", side_effect=[
                 _proc(0),  # git add
                 _proc(1, stderr="commit failed"),  # git commit
                 _proc(0),  # worktree remove (finally)
             ]):
            result = pr._create_intent_stub(REPO, SLUG, BRANCH, BASE, ["widget"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["method"], "failed")
        self.assertIn("stub commit failed", result["reason"])

    def test_worktree_add_failure_returns_failed(self):
        with patch.object(pr, "_free_branch"), \
             patch.object(pr, "_git") as g, \
             patch("subprocess.run", return_value=_proc(0)):
            g.side_effect = [
                _proc(0),  # branch -D
                _proc(0),  # branch <base>
                _proc(1, stderr="wt fail"),  # worktree add
            ]
            result = pr._create_intent_stub(REPO, SLUG, BRANCH, BASE, [])
        self.assertFalse(result["ok"])
        self.assertIn("worktree setup failed", result["reason"])

    def test_empty_intent_words_uses_slug_as_fallback(self):
        written = []

        def fake_open(path, mode="r", **kw):
            m = unittest.mock.mock_open()()
            m.write.side_effect = lambda s: written.append(s)
            return m

        with patch.object(pr, "_free_branch"), \
             patch.object(pr, "_git", return_value=_proc(0)), \
             patch("builtins.open", fake_open), \
             patch("subprocess.run", return_value=_proc(0)):
            pr._create_intent_stub(REPO, SLUG, BRANCH, BASE, [])
        intent_line = "".join(w for w in written if "intent:" in w)
        self.assertIn(SLUG, intent_line)


if __name__ == "__main__":
    unittest.main()
