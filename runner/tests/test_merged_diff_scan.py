"""Tests for merged_diff_scan — the read-side of merged-diff memory memos.

Covers: frontmatter parsing, section extraction, memo parsing, scan_project,
collect_rules, collect_frameworks, stats, and fail-soft on bad input.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import merged_diff_scan as mds

SAMPLE_MEMO = """---
name: merged_diff_20260901
description: Rollup of 3 merges
metadata:
  date: 2026-09-01
  commits: abc1234, def5678
---

## Learned Conventions & Do/Avoid Rules
- Always validate input at boundaries
- Use fail-soft error handling
- (no new rules extracted today)

## Frameworks in Use
pytest, unittest, None

See also: [[some link]]
"""

MINIMAL_MEMO = """---
name: minimal
---
## Learned Conventions & Do/Avoid Rules
- Single rule here
"""


class TestParseFrontmatter(unittest.TestCase):
    def test_extracts_name(self):
        fm = mds._parse_frontmatter(SAMPLE_MEMO)
        self.assertEqual(fm["name"], "merged_diff_20260901")

    def test_extracts_nested_metadata(self):
        fm = mds._parse_frontmatter(SAMPLE_MEMO)
        self.assertIsInstance(fm.get("metadata"), dict)
        self.assertEqual(fm["metadata"]["date"], "2026-09-01")

    def test_extracts_commits_string(self):
        fm = mds._parse_frontmatter(SAMPLE_MEMO)
        self.assertIn("abc1234", fm["metadata"]["commits"])

    def test_empty_input(self):
        self.assertEqual(mds._parse_frontmatter(""), {})

    def test_none_input(self):
        self.assertEqual(mds._parse_frontmatter(None), {})

    def test_no_frontmatter(self):
        self.assertEqual(mds._parse_frontmatter("just text"), {})


class TestSection(unittest.TestCase):
    def test_rules_section(self):
        lines = mds._section(SAMPLE_MEMO, mds._RULES_HEADING)
        self.assertIn("- Always validate input at boundaries", lines)
        self.assertIn("- Use fail-soft error handling", lines)

    def test_placeholder_line_included_raw(self):
        lines = mds._section(SAMPLE_MEMO, mds._RULES_HEADING)
        # placeholder is in section but filtered by parse_memo
        self.assertTrue(any("no new rules" in ln for ln in lines))

    def test_frameworks_section(self):
        lines = mds._section(SAMPLE_MEMO, mds._FRAMEWORKS_HEADING)
        self.assertTrue(len(lines) > 0)

    def test_trailer_stops_section(self):
        lines = mds._section(SAMPLE_MEMO, mds._FRAMEWORKS_HEADING)
        self.assertFalse(any("See also" in ln for ln in lines))

    def test_missing_heading(self):
        self.assertEqual(mds._section(SAMPLE_MEMO, "## Nonexistent"), [])


class TestParseMemo(unittest.TestCase):
    def _write_memo(self, content, name="merged_diff_test.md"):
        d = tempfile.mkdtemp()
        p = Path(d) / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_parses_rules(self):
        p = self._write_memo(SAMPLE_MEMO)
        m = mds.parse_memo(p)
        self.assertIsNotNone(m)
        self.assertIn("Always validate input at boundaries", m["rules"])
        # placeholder line should be filtered out
        self.assertFalse(any("no new rules" in r for r in m["rules"]))

    def test_parses_frameworks(self):
        p = self._write_memo(SAMPLE_MEMO)
        m = mds.parse_memo(p)
        self.assertIn("pytest", m["frameworks"])
        self.assertIn("unittest", m["frameworks"])
        # "None" should be filtered out
        self.assertNotIn("None", m["frameworks"])
        self.assertNotIn("none", m["frameworks"])

    def test_parses_commits(self):
        p = self._write_memo(SAMPLE_MEMO)
        m = mds.parse_memo(p)
        self.assertIn("abc1234", m["commits"])
        self.assertIn("def5678", m["commits"])

    def test_minimal_memo(self):
        p = self._write_memo(MINIMAL_MEMO)
        m = mds.parse_memo(p)
        self.assertIsNotNone(m)
        self.assertEqual(m["rules"], ["Single rule here"])

    def test_nonexistent_file(self):
        self.assertIsNone(mds.parse_memo("/nonexistent/path.md"))

    def test_empty_file(self):
        p = self._write_memo("")
        m = mds.parse_memo(p)
        self.assertIsNotNone(m)
        self.assertEqual(m["rules"], [])


class TestScanProject(unittest.TestCase):
    def test_empty_project_id(self):
        self.assertEqual(mds.scan_project(""), [])

    def test_none_project_id(self):
        self.assertEqual(mds.scan_project(None), [])

    def test_nonexistent_project(self):
        self.assertEqual(mds.scan_project("nonexistent-project-xyz"), [])


class TestCollectAndStats(unittest.TestCase):
    def test_collect_rules_nonexistent(self):
        rules = mds.collect_rules("nonexistent-project-xyz")
        self.assertEqual(rules, [])

    def test_collect_frameworks_nonexistent(self):
        fws = mds.collect_frameworks("nonexistent-project-xyz")
        self.assertEqual(fws, [])

    def test_stats_nonexistent(self):
        s = mds.stats("nonexistent-project-xyz")
        self.assertEqual(s["memos"], 0)
        self.assertEqual(s["rules"], 0)


if __name__ == "__main__":
    unittest.main()
