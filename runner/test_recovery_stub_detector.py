#!/usr/bin/env python3
"""Tests for runner/recovery_stub_detector.py."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import recovery_stub_detector as rsd

SLUG = "recover-missing-branch-toolchain-repair-6096aa2b-fix-node-modules-install-slice-2"
MARKER = f".recovery-intent-{SLUG}.txt"
MARKER_BODY = (
    f"recovery-intent: {SLUG}\n"
    "template: 59371fe244f5\n"
    "intent: 056af630dd5f 07062319 acceptance adapt agent branch build cache\n"
    "base: master\n"
)
# The commit actually observed on racefeed at c4ecfd53ca7b.
OBSERVED_COMMIT = {"subject": f"recovery-intent-stub: {SLUG}", "files": [MARKER], "body": MARKER_BODY}


class TestStubPath(unittest.TestCase):
    def test_matches_marker_files(self):
        self.assertTrue(rsd.is_stub_path(MARKER))
        self.assertTrue(rsd.is_stub_path(f"sub/dir/{MARKER}"))
        self.assertTrue(rsd.is_stub_path(".recovery-intent.canary.txt"))

    def test_rejects_ordinary_paths(self):
        for p in ("package.json", "runner/db.py", "docs/recovery-intent.md",
                  "recovery-intent-notes.txt", ".recovery-intent-x.py"):
            self.assertFalse(rsd.is_stub_path(p), p)

    def test_fail_soft(self):
        for bad in (None, "", 0, b"", []):
            self.assertFalse(rsd.is_stub_path(bad))


class TestStubSubject(unittest.TestCase):
    def test_matches(self):
        self.assertTrue(rsd.is_stub_subject(f"recovery-intent-stub: {SLUG}"))
        self.assertTrue(rsd.is_stub_subject("  Recovery-Intent-Stub:  x"))

    def test_rejects_real_subjects(self):
        self.assertFalse(rsd.is_stub_subject("fix(build): repair node_modules install"))
        self.assertFalse(rsd.is_stub_subject("agent: some-slug"))
        self.assertFalse(rsd.is_stub_subject(None))


class TestStubBody(unittest.TestCase):
    def test_matches_marker_payload(self):
        self.assertTrue(rsd.is_stub_body(MARKER_BODY))

    def test_requires_two_keys(self):
        self.assertFalse(rsd.is_stub_body("recovery-intent: only-this-key\n"))
        self.assertFalse(rsd.is_stub_body("intent: build cache\nbase: master\n"))

    def test_ordinary_prose_is_not_a_stub(self):
        self.assertFalse(rsd.is_stub_body("We recorded the intent: ship the fix. base: master."))
        self.assertFalse(rsd.is_stub_body(""))
        self.assertFalse(rsd.is_stub_body(None))


class TestClassifyFiles(unittest.TestCase):
    def test_splits_markers_from_work(self):
        markers, real = rsd.classify_files([MARKER, "package.json", "runner/db.py"])
        self.assertEqual(markers, [MARKER])
        self.assertEqual(real, ["package.json", "runner/db.py"])

    def test_drops_blank_entries(self):
        self.assertEqual(rsd.classify_files(["", "  ", None]), ([], []))


class TestAnalyzeCommit(unittest.TestCase):
    def test_observed_racefeed_commit_is_a_stub(self):
        r = rsd.analyze_commit(**OBSERVED_COMMIT)
        self.assertEqual(r["verdict"], rsd.VERDICT_STUB)
        self.assertTrue(r["stub_subject"])
        self.assertTrue(r["stub_body"])
        self.assertEqual(r["substantive_files"], [])

    def test_real_commit(self):
        r = rsd.analyze_commit("fix: repair install", ["package.json", "package-lock.json"])
        self.assertEqual(r["verdict"], rsd.VERDICT_REAL)
        self.assertIn("2 substantive file(s) changed", r["reasons"][0])

    def test_mixed_commit(self):
        r = rsd.analyze_commit("agent: slug", [MARKER, "package.json"])
        self.assertEqual(r["verdict"], rsd.VERDICT_MIXED)

    def test_stub_subject_without_files(self):
        self.assertEqual(rsd.analyze_commit(f"recovery-intent-stub: {SLUG}", [])["verdict"],
                         rsd.VERDICT_STUB)

    def test_empty_commit(self):
        self.assertEqual(rsd.analyze_commit(None, None)["verdict"], rsd.VERDICT_EMPTY)

    def test_never_raises(self):
        for bad in (object(), 5, [], {}):
            self.assertIn("verdict", rsd.analyze_commit(bad, bad, bad))


class TestAnalyzeBranch(unittest.TestCase):
    def test_the_audited_branch_is_a_stub_branch(self):
        r = rsd.analyze_branch([OBSERVED_COMMIT])
        self.assertEqual(r["verdict"], rsd.VERDICT_STUB)
        self.assertEqual(r["commits"], 1)
        self.assertEqual(r["stub_commits"], 1)
        self.assertEqual(r["marker_files"], [MARKER])
        self.assertFalse(r["mergeable_as_work"])
        self.assertIn("no work was done", r["reason"])

    def test_real_branch(self):
        r = rsd.analyze_branch([
            {"subject": "fix: install", "files": ["package.json"]},
            {"subject": "test: cover install", "files": ["tests/install.test.ts"]},
        ])
        self.assertEqual(r["verdict"], rsd.VERDICT_REAL)
        self.assertTrue(r["mergeable_as_work"])

    def test_mixed_branch_is_mergeable_but_flagged(self):
        r = rsd.analyze_branch([
            {"subject": f"recovery-intent-stub: {SLUG}", "files": [MARKER]},
            {"subject": "fix: actually repair the install", "files": ["package.json"]},
        ])
        self.assertEqual(r["verdict"], rsd.VERDICT_MIXED)
        self.assertTrue(r["mergeable_as_work"])
        self.assertIn("strip the marker", r["reason"])

    def test_multiple_stub_commits_still_stub(self):
        r = rsd.analyze_branch([OBSERVED_COMMIT, OBSERVED_COMMIT])
        self.assertEqual(r["verdict"], rsd.VERDICT_STUB)
        self.assertEqual(r["stub_commits"], 2)

    def test_empty_and_bad_input(self):
        for bad in (None, [], [None], ["junk"], [{}]):
            r = rsd.analyze_branch(bad)
            self.assertEqual(r["verdict"], rsd.VERDICT_EMPTY)
            self.assertFalse(r["mergeable_as_work"])


class TestParseGitLog(unittest.TestCase):
    def test_sentinel_parsing_keeps_file_names(self):
        raw = f"\x00recovery-intent-stub: {SLUG}\n\n{MARKER}\n\x00fix: real\n\npackage.json\n"
        commits = rsd.parse_git_log(raw)
        self.assertEqual(len(commits), 2)
        self.assertEqual(commits[0]["files"], [MARKER])
        self.assertEqual(commits[1]["files"], ["package.json"])

    def test_end_to_end_on_the_audited_branch_shape(self):
        raw = f"\x00recovery-intent-stub: {SLUG}\n\n{MARKER}\n"
        result = rsd.analyze_branch(rsd.parse_git_log(raw))
        self.assertEqual(result["verdict"], rsd.VERDICT_STUB)
        self.assertEqual(result["marker_files"], [MARKER])

    def test_empty_stream(self):
        self.assertEqual(rsd.parse_git_log(""), [])
        self.assertEqual(rsd.parse_git_log(None), [])


class TestGateAndCleanup(unittest.TestCase):
    def test_gate_blocks_stub_branches(self):
        allow, reason = rsd.gate([OBSERVED_COMMIT])
        self.assertFalse(allow)
        self.assertIn("do not record this slug as MERGED", reason)

    def test_gate_allows_real_branches(self):
        allow, _reason = rsd.gate([{"subject": "fix", "files": ["package.json"]}])
        self.assertTrue(allow)

    def test_cleanup_paths_lists_only_markers(self):
        self.assertEqual(rsd.cleanup_paths([MARKER, "package.json"]), [MARKER])
        self.assertEqual(rsd.cleanup_paths(None), [])


if __name__ == "__main__":
    unittest.main()
