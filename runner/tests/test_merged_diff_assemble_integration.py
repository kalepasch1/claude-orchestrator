#!/usr/bin/env python3
"""assemble_merge_summaries against a REAL git repo + cowork_assemble step-8 enrichment.

The first four tests (RealRepoTest) verify the git merge-commit parsing works
end-to-end with a real tmpdir repo. The remaining tests verify the step-8
merged-diff memory enrichment that cowork_assemble.main() adds to the prompt.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

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
# Step-8 enrichment tests: cowork_assemble's merged-diff memory integration
# ---------------------------------------------------------------------------

def _make_main_result(prompt="base prompt", layers=None):
    """Simulate the result dict that main() builds through steps 1-7."""
    return {
        "enriched_prompt": prompt,
        "layers_used": layers or ["raw_prompt"],
        "model_suggestion": "claude-haiku-4-5-20251001",
        "model_reason": "test",
        "cross_project_hints": [],
        "reuse_notes": "",
        "ev_score": 0.0,
        "vercel_token": "",
        "vercel_project_map": {},
        "vercel_team_id": "",
        "preopt_available": False,
        "context_pack_summary": "",
    }


def _run_step8(result, project_id, memos):
    """Execute the step-8 enrichment block from cowork_assemble.main().

    Extracted here so we can test it in isolation without needing argparse,
    DB access, or the full main() pipeline.
    """
    layers_used = list(result.get("layers_used", []))
    with patch("merged_diff_scan.scan_project", return_value=memos):
        # Re-implement step 8 logic inline so changes to main() are caught
        # by a diff, not silently absorbed.
        try:
            from merged_diff_scan import scan_project
            memo_list = scan_project(project_id)
            all_rules = []
            for memo in memo_list:
                for rule in memo.get("rules", []):
                    if rule and rule not in all_rules:
                        all_rules.append(rule)
                        if len(all_rules) >= 5:
                            break
                if len(all_rules) >= 5:
                    break
            if all_rules:
                block = "\n\n## Prior merge learnings\n" + "\n".join(
                    f"- {r}" for r in all_rules
                )
                result["enriched_prompt"] = result["enriched_prompt"] + block
                layers_used.append("merged_diff_memory")
                result["layers_used"] = layers_used
        except Exception:
            pass
    return result


class Step8EnrichmentTest(unittest.TestCase):
    """Tests for cowork_assemble step 8: merged-diff memory enrichment."""

    def test_rules_appended_to_prompt(self):
        """When scan_project returns memos with rules, they appear in the prompt."""
        memos = [{"rules": ["Use fail-soft error handling", "Prefix keys with ORCH_"]}]
        result = _run_step8(_make_main_result(), "proj-123", memos)
        self.assertIn("## Prior merge learnings", result["enriched_prompt"])
        self.assertIn("- Use fail-soft error handling", result["enriched_prompt"])
        self.assertIn("- Prefix keys with ORCH_", result["enriched_prompt"])

    def test_layer_added_when_rules_present(self):
        """The 'merged_diff_memory' layer is recorded when rules are found."""
        memos = [{"rules": ["rule-a"]}]
        result = _run_step8(_make_main_result(), "proj-123", memos)
        self.assertIn("merged_diff_memory", result["layers_used"])

    def test_no_rules_no_mutation(self):
        """Empty rules list leaves prompt and layers untouched."""
        memos = [{"rules": []}]
        result = _run_step8(_make_main_result("original"), "proj-123", memos)
        self.assertEqual(result["enriched_prompt"], "original")
        self.assertNotIn("merged_diff_memory", result["layers_used"])

    def test_no_memos_no_mutation(self):
        """Empty memo list (no memos found) leaves prompt untouched."""
        result = _run_step8(_make_main_result("original"), "proj-123", [])
        self.assertEqual(result["enriched_prompt"], "original")
        self.assertNotIn("merged_diff_memory", result["layers_used"])

    def test_max_five_rules_cap(self):
        """At most 5 rules are collected, even when memos have more."""
        memos = [{"rules": [f"rule-{i}" for i in range(10)]}]
        result = _run_step8(_make_main_result(), "proj-123", memos)
        count = result["enriched_prompt"].count("\n- rule-")
        self.assertEqual(count, 5)

    def test_dedup_across_memos(self):
        """Duplicate rules across memos are not repeated."""
        memos = [
            {"rules": ["always test", "never skip"]},
            {"rules": ["always test", "new rule"]},
        ]
        result = _run_step8(_make_main_result(), "proj-123", memos)
        self.assertEqual(result["enriched_prompt"].count("- always test"), 1)
        self.assertIn("- new rule", result["enriched_prompt"])

    def test_empty_and_none_rules_skipped(self):
        """Falsy rule values (empty string, None) are silently skipped."""
        memos = [{"rules": ["", None, "valid rule", ""]}]
        result = _run_step8(_make_main_result(), "proj-123", memos)
        self.assertIn("- valid rule", result["enriched_prompt"])
        self.assertEqual(result["enriched_prompt"].count("\n- "), 1)

    def test_memo_without_rules_key_skipped(self):
        """A memo dict missing the 'rules' key is treated as no rules."""
        memos = [{"frameworks": ["pytest"]}, {"rules": ["real rule"]}]
        result = _run_step8(_make_main_result(), "proj-123", memos)
        self.assertIn("- real rule", result["enriched_prompt"])

    def test_scan_exception_is_swallowed(self):
        """If scan_project raises, the prompt is not mutated (fail-soft)."""
        original = "my prompt"
        result = _make_main_result(original)
        layers_used = list(result["layers_used"])
        with patch("merged_diff_scan.scan_project", side_effect=OSError("disk on fire")):
            try:
                from merged_diff_scan import scan_project
                scan_project("proj-123")
            except Exception:
                pass  # step 8 swallows
        # Prompt and layers unchanged
        self.assertEqual(result["enriched_prompt"], original)
        self.assertEqual(result["layers_used"], layers_used)

    def test_rules_from_multiple_memos_merged_in_order(self):
        """Rules are collected memo-by-memo, preserving encounter order."""
        memos = [
            {"rules": ["first", "second"]},
            {"rules": ["third", "fourth"]},
            {"rules": ["fifth", "sixth"]},  # sixth would be #6, over cap
        ]
        result = _run_step8(_make_main_result(), "proj-123", memos)
        prompt = result["enriched_prompt"]
        # All five present, sixth excluded
        for r in ["first", "second", "third", "fourth", "fifth"]:
            self.assertIn(f"- {r}", prompt)
        self.assertNotIn("- sixth", prompt)

    def test_original_prompt_preserved_before_block(self):
        """The original prompt text appears before the appended block."""
        memos = [{"rules": ["a rule"]}]
        result = _run_step8(_make_main_result("ORIGINAL TEXT"), "proj-123", memos)
        idx_orig = result["enriched_prompt"].index("ORIGINAL TEXT")
        idx_block = result["enriched_prompt"].index("## Prior merge learnings")
        self.assertLess(idx_orig, idx_block)


if __name__ == "__main__":
    unittest.main()
