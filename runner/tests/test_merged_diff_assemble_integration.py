#!/usr/bin/env python3
"""assemble_merge_summaries against a REAL git repo.

The mocked suite cannot catch the one thing that actually broke this shape: a plain
`git diff-tree -r <merge-sha>` prints NOTHING for a merge commit, so files_changed came
back empty for every record. Only a real merge commit exposes that, so this file builds
one in a tmpdir.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import merged_diff_memory as mdm


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _build_repo(path):
    _git("init", "-q", "-b", "main", cwd=path)
    _git("config", "user.email", "t@example.test", cwd=path)
    _git("config", "user.name", "T", cwd=path)
    open(os.path.join(path, "base.py"), "w").write("x = 1\n")
    _git("add", "-A", cwd=path)
    _git("commit", "-q", "-m", "base", cwd=path)

    _git("checkout", "-q", "-b", "agent/feature", cwd=path)
    os.makedirs(os.path.join(path, "runner"), exist_ok=True)
    open(os.path.join(path, "runner", "feature.py"), "w").write("y = 2\n")
    _git("add", "-A", cwd=path)
    _git("commit", "-q", "-m", "feat: add feature", cwd=path)

    _git("checkout", "-q", "main", cwd=path)
    _git("merge", "-q", "--no-ff", "-m", "Merge branch 'agent/feature'",
         "agent/feature", cwd=path)


class RealRepoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo = cls.tmp.name
        _build_repo(cls.repo)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_a_real_merge_commit_reports_the_files_it_brought_in(self):
        """The regression: this list was empty for every merge before -m --first-parent."""
        out = mdm.assemble_merge_summaries(limit=5, repo=self.repo)
        self.assertTrue(out, "no merges found in the fixture repo")
        merge = out[0]
        self.assertEqual(merge["branch_name"], "agent/feature")
        self.assertIn("runner/feature.py", merge["files_changed"])

    def test_the_summary_reflects_the_real_files(self):
        merge = mdm.assemble_merge_summaries(limit=5, repo=self.repo)[0]
        self.assertNotIn("no files changed", merge["summary"])
        self.assertIn("runner", merge["summary"])

    def test_the_shape_holds_against_a_real_repo(self):
        for rec in mdm.assemble_merge_summaries(limit=5, repo=self.repo):
            self.assertEqual(list(rec.keys()),
                             ["name", "branch_name", "files_changed",
                              "merge_date", "summary"])
            self.assertIsInstance(rec["files_changed"], list)
            self.assertTrue(rec["merge_date"])

    def test_a_directory_that_is_not_a_repo_returns_empty(self):
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(mdm.assemble_merge_summaries(limit=5, repo=empty), [])


# ---------------------------------------------------------------------------
# Step 8 of cowork_assemble: merged-diff memos read back into the prompt.
#
# These call cowork_assemble's own functions. An earlier version of this suite
# pasted a copy of the step-8 loop into the test file and asserted against the
# copy, so deleting the production block entirely would not have failed a
# single case.
# ---------------------------------------------------------------------------
import cowork_assemble as ca  # noqa: E402


def _memo(*rules):
    return {"rules": list(rules)}


class ClaudeProjectDirTest(unittest.TestCase):
    def test_repo_path_becomes_the_claude_projects_directory_name(self):
        self.assertEqual(
            ca._claude_project_dir("/Users/kpasch/Documents/beethoven/claude-orchestrator"),
            "-Users-kpasch-Documents-beethoven-claude-orchestrator",
        )

    def test_a_relative_path_is_absolutised_first(self):
        self.assertTrue(ca._claude_project_dir(".").startswith("-"))
        self.assertNotIn("/", ca._claude_project_dir("."))

    def test_a_missing_repo_path_yields_no_key(self):
        for value in ("", "   ", None):
            self.assertEqual(ca._claude_project_dir(value), "")


class MergedDiffLearningsTest(unittest.TestCase):
    """merged_diff_learnings() — which memos are read, and which rules survive."""

    def test_the_scan_is_keyed_off_the_repo_path_not_the_db_uuid(self):
        """Regression: --project-id is a DB UUID, but scan_project() takes a
        directory name under ~/.claude/projects. Keying off the UUID made the
        whole enrichment a silent no-op."""
        seen = []

        def fake_scan(key):
            seen.append(key)
            return [_memo("rule-a")]

        with patch("merged_diff_scan.scan_project", side_effect=fake_scan):
            rules = ca.merged_diff_learnings("/tmp/some/repo", "3f2b-uuid-9c1a")

        self.assertEqual(seen, ["-tmp-some-repo"])
        self.assertEqual(rules, ["rule-a"])

    def test_project_id_is_tried_when_the_repo_path_has_no_memos(self):
        with patch("merged_diff_scan.scan_project",
                   side_effect=lambda key: [_memo("fallback")] if key == "dir-name" else []):
            self.assertEqual(
                ca.merged_diff_learnings("/tmp/some/repo", "dir-name"), ["fallback"])

    def test_rules_are_capped_at_five(self):
        with patch("merged_diff_scan.scan_project",
                   return_value=[_memo(*[f"rule-{i}" for i in range(10)])]):
            self.assertEqual(len(ca.merged_diff_learnings("/tmp/repo")), 5)

    def test_duplicate_rules_across_memos_are_collapsed(self):
        memos = [_memo("always test", "never skip"), _memo("always test", "new rule")]
        with patch("merged_diff_scan.scan_project", return_value=memos):
            self.assertEqual(
                ca.merged_diff_learnings("/tmp/repo"),
                ["always test", "never skip", "new rule"],
            )

    def test_memo_order_is_preserved_and_the_overflow_is_dropped(self):
        memos = [_memo("first", "second"), _memo("third", "fourth"), _memo("fifth", "sixth")]
        with patch("merged_diff_scan.scan_project", return_value=memos):
            self.assertEqual(
                ca.merged_diff_learnings("/tmp/repo"),
                ["first", "second", "third", "fourth", "fifth"],
            )

    def test_falsy_rules_and_a_missing_rules_key_are_skipped(self):
        memos = [{"frameworks": ["pytest"]}, {"rules": ["", None, "valid rule"]}]
        with patch("merged_diff_scan.scan_project", return_value=memos):
            self.assertEqual(ca.merged_diff_learnings("/tmp/repo"), ["valid rule"])


class ApplyMergedDiffEnrichmentTest(unittest.TestCase):
    """apply_merged_diff_enrichment() — what it does to the result dict."""

    def _result(self, prompt="ORIGINAL TEXT"):
        return {"enriched_prompt": prompt, "layers_used": ["raw_prompt"]}

    def test_the_block_is_appended_after_the_original_prompt(self):
        result = self._result()
        with patch.object(ca, "merged_diff_learnings",
                          return_value=["Use fail-soft error handling", "Prefix keys with ORCH_"]):
            self.assertTrue(ca.apply_merged_diff_enrichment(result, "/tmp/repo"))

        prompt = result["enriched_prompt"]
        self.assertLess(prompt.index("ORIGINAL TEXT"), prompt.index(ca.MERGED_LEARNINGS_HEADING))
        self.assertIn("- Use fail-soft error handling", prompt)
        self.assertIn("- Prefix keys with ORCH_", prompt)

    def test_the_layer_is_recorded_once(self):
        result = self._result()
        with patch.object(ca, "merged_diff_learnings", return_value=["rule-a"]):
            ca.apply_merged_diff_enrichment(result, "/tmp/repo")
            ca.apply_merged_diff_enrichment(result, "/tmp/repo")
        self.assertEqual(result["layers_used"].count(ca.MERGED_LEARNINGS_LAYER), 1)
        self.assertIn("raw_prompt", result["layers_used"])

    def test_no_rules_leaves_the_result_untouched(self):
        result = self._result()
        with patch.object(ca, "merged_diff_learnings", return_value=[]):
            self.assertFalse(ca.apply_merged_diff_enrichment(result, "/tmp/repo"))
        self.assertEqual(result, self._result())

    def test_a_failing_scan_leaves_the_result_untouched(self):
        result = self._result()
        with patch.object(ca, "merged_diff_learnings", side_effect=OSError("disk on fire")):
            self.assertFalse(ca.apply_merged_diff_enrichment(result, "/tmp/repo"))
        self.assertEqual(result, self._result())

    def test_an_unimportable_scanner_leaves_the_result_untouched(self):
        result = self._result()
        with patch.dict(sys.modules, {"merged_diff_scan": None}):
            self.assertFalse(ca.apply_merged_diff_enrichment(result, "/tmp/repo"))
        self.assertEqual(result, self._result())


class Step8WiringTest(unittest.TestCase):
    """main() must actually call the enrichment — the wiring is the deliverable."""

    def test_main_applies_the_enrichment_with_the_repo_path(self):
        argv = ["cowork_assemble.py", "--task-id", "t-1", "--repo-path", "/tmp/repo",
                "--project-id", "uuid-1"]
        with patch.object(ca, "get_enriched_prompt", return_value=("BASE", ["raw_prompt"])), \
                patch.object(ca, "get_model_suggestion", return_value=("m", "r")), \
                patch.object(ca, "get_cross_project_hints", return_value=[]), \
                patch.object(ca, "get_reuse_notes", return_value=""), \
                patch.object(ca, "get_ev_score", return_value=0.0), \
                patch.object(ca, "get_vercel_config",
                             return_value={"token": "", "project_map": {}, "team_id": ""}), \
                patch.object(ca, "get_preopt_cache", return_value=(False, "")), \
                patch.object(ca, "merged_diff_learnings", return_value=["a rule"]) as learnings, \
                patch("sys.argv", argv), \
                patch("builtins.print") as printed:
            ca.main()

        learnings.assert_called_once_with("/tmp/repo", "uuid-1")
        emitted = json.loads(printed.call_args.args[0])
        self.assertIn("- a rule", emitted["enriched_prompt"])
        self.assertIn(ca.MERGED_LEARNINGS_LAYER, emitted["layers_used"])


if __name__ == "__main__":
    unittest.main()
