#!/usr/bin/env python3
"""assemble_merge_summaries: the [{name, branch_name, files_changed, merge_date, summary}] shape.

The backlog batch this comes from is a collapsed list of merged-diff-memory bullets; the
one concrete deliverable repeated across them is this assembled return shape, which no
function in the module produced. These tests pin the shape exactly (keys, order, no
extras), the branch extraction across the three subject forms git writes, and the
fail-soft contract — a git failure must yield [] rather than raise, because every caller
reads this inside a broad except and a raise would silently become "no merges".
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import merged_diff_memory as mdm


def _fake_git(log_shas, per_sha):
    """Stand in for _safe_run: dispatch on the git subcommand and format."""
    def run(cmd, cwd=None):
        if "log" in cmd and "--format=%H" in cmd:
            if "--merges" in cmd and not log_shas.get("merges"):
                return ""
            return "\n".join(log_shas["merges"] if "--merges" in cmd
                             else log_shas.get("plain", []))
        sha = cmd[-1]
        data = per_sha.get(sha, {})
        if "--format=%s" in cmd:
            return data.get("subject", "")
        if "--format=%aI" in cmd:
            return data.get("date", "")
        if "diff-tree" in cmd:
            return "\n".join(data.get("files", []))
        return ""
    return run


class ShapeTest(unittest.TestCase):
    def setUp(self):
        self.per_sha = {
            "sha1": {"subject": "Merge branch 'agent/add-thing'",
                     "date": "2026-08-12T10:00:00Z",
                     "files": ["runner/a.py", "runner/tests/test_a.py"]},
            "sha2": {"subject": "Merge branch 'agent/other'",
                     "date": "2026-08-11T10:00:00Z",
                     "files": ["docs/x.md"]},
        }
        self.patch = mock.patch.object(
            mdm, "_safe_run",
            side_effect=_fake_git({"merges": ["sha1", "sha2"]}, self.per_sha))

    def test_exactly_the_specified_keys_in_order(self):
        with self.patch:
            out = mdm.assemble_merge_summaries(limit=5)
        self.assertEqual(len(out), 2)
        for rec in out:
            self.assertEqual(list(rec.keys()),
                             ["name", "branch_name", "files_changed",
                              "merge_date", "summary"])

    def test_fields_carry_the_extracted_values(self):
        with self.patch:
            first = mdm.assemble_merge_summaries(limit=5)[0]
        self.assertEqual(first["name"], "Merge branch 'agent/add-thing'")
        self.assertEqual(first["branch_name"], "agent/add-thing")
        self.assertEqual(first["files_changed"], ["runner/a.py", "runner/tests/test_a.py"])
        self.assertEqual(first["merge_date"], "2026-08-12T10:00:00Z")
        self.assertTrue(first["summary"])

    def test_newest_first_and_limit_is_respected(self):
        with self.patch:
            out = mdm.assemble_merge_summaries(limit=1)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["merge_date"], "2026-08-12T10:00:00Z")

    def test_a_limit_of_zero_or_less_returns_nothing(self):
        with self.patch:
            self.assertEqual(mdm.assemble_merge_summaries(limit=0), [])
            self.assertEqual(mdm.assemble_merge_summaries(limit=-4), [])

    def test_a_garbage_limit_falls_back_to_the_default(self):
        with self.patch:
            self.assertEqual(len(mdm.assemble_merge_summaries(limit="lots")), 2)


class BranchExtractionTest(unittest.TestCase):
    def test_the_three_subject_forms_git_writes(self):
        cases = {
            "Merge branch 'agent/foo'": "agent/foo",
            "Merge branch 'agent/foo' into orchestrator/dev": "agent/foo",
            "Merge remote-tracking branch 'origin/agent/foo'": "agent/foo",
            "Merge pull request #12 from kalepasch1/agent/foo": "kalepasch1/agent/foo",
            "Merge agent/foo": "agent/foo",
        }
        for subject, expected in cases.items():
            with self.subTest(subject=subject):
                self.assertEqual(mdm._branch_from_subject(subject), expected)

    def test_a_non_merge_subject_yields_no_branch(self):
        for subject in ("fix: tidy the parser", "", None):
            with self.subTest(subject=subject):
                self.assertEqual(mdm._branch_from_subject(subject), "")


class SummaryHeuristicTest(unittest.TestCase):
    def test_a_test_only_merge_says_so(self):
        s = mdm._summarise("Merge branch 'agent/x'", "agent/x",
                           ["runner/tests/test_a.py", "tests/test_b.py"])
        self.assertIn("tests only", s)

    def test_a_mixed_merge_counts_both_sides(self):
        s = mdm._summarise("subj", "b", ["runner/a.py", "runner/tests/test_a.py"])
        self.assertIn("1 source + 1 test file(s)", s)

    def test_a_source_only_merge_counts_files(self):
        self.assertIn("2 source file(s)",
                      mdm._summarise("subj", "b", ["a/x.py", "a/y.py"]))

    def test_an_empty_merge_is_described_not_crashed(self):
        self.assertIn("no files changed", mdm._summarise("subj", "b", []))
        self.assertIn("no files changed", mdm._summarise("subj", "b", None))

    def test_the_touched_areas_appear(self):
        self.assertIn("runner", mdm._summarise("s", "b", ["runner/a.py"]))

    def test_a_root_level_file_is_labelled(self):
        self.assertIn("(root)", mdm._summarise("s", "b", ["setup.py"]))

    def test_the_summary_is_deterministic(self):
        args = ("s", "b", ["runner/a.py", "docs/b.md"])
        self.assertEqual(mdm._summarise(*args), mdm._summarise(*args))


class FailSoftTest(unittest.TestCase):
    def test_no_commits_at_all_yields_an_empty_list(self):
        with mock.patch.object(mdm, "_safe_run", return_value=""):
            self.assertEqual(mdm.assemble_merge_summaries(), [])

    def test_a_raising_git_yields_an_empty_list_not_an_exception(self):
        with mock.patch.object(mdm, "_safe_run", side_effect=RuntimeError("git gone")):
            self.assertEqual(mdm.assemble_merge_summaries(), [])

    def test_it_falls_back_to_plain_commits_when_there_are_no_merges(self):
        per_sha = {"c1": {"subject": "feat: thing", "date": "2026-08-01T00:00:00Z",
                          "files": ["runner/a.py"]}}
        with mock.patch.object(mdm, "_safe_run",
                               side_effect=_fake_git({"merges": [], "plain": ["c1"]},
                                                     per_sha)):
            out = mdm.assemble_merge_summaries(limit=5)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["branch_name"], "")


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._dir, self._file = mdm.MEMORY_DIR, mdm.MERGED_DIFF_FILE
        mdm.MEMORY_DIR = Path(self.tmp.name)
        mdm.MERGED_DIFF_FILE = Path(self.tmp.name) / "merged_diff_memory.json"

    def tearDown(self):
        mdm.MEMORY_DIR, mdm.MERGED_DIFF_FILE = self._dir, self._file
        self.tmp.cleanup()

    def _patch(self):
        return mock.patch.object(
            mdm, "_safe_run",
            side_effect=_fake_git({"merges": ["sha1"]},
                                  {"sha1": {"subject": "Merge branch 'agent/x'",
                                            "date": "2026-08-12T10:00:00Z",
                                            "files": ["runner/a.py"]}}))

    def test_store_false_writes_nothing(self):
        with self._patch():
            mdm.assemble_merge_summaries(limit=5)
        self.assertEqual(mdm.get_recent_merges(limit=10), [])

    def test_store_true_persists_in_the_existing_memory_schema(self):
        with self._patch():
            mdm.assemble_merge_summaries(limit=5, store=True)
        stored = mdm.get_recent_merges(limit=10)
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["commit"], "sha1")
        self.assertEqual(stored[0]["branch"], "agent/x")
        self.assertEqual(stored[0]["files_affected"], ["runner/a.py"])

    def test_storing_twice_does_not_duplicate(self):
        with self._patch():
            mdm.assemble_merge_summaries(limit=5, store=True)
            mdm.assemble_merge_summaries(limit=5, store=True)
        self.assertEqual(len(mdm.get_recent_merges(limit=10)), 1)


if __name__ == "__main__":
    unittest.main()
