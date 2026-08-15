"""Integration tests for the group-13 frontmatter ingestion pipeline."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))

from frontmatter_ingest import parse_frontmatter_and_body, process_directory_of_files  # noqa: E402


class ParseTest(unittest.TestCase):
    def test_valid_frontmatter_and_body(self):
        out = parse_frontmatter_and_body("---\ntitle: X\ntags: [a, b]\n---\nkey: value\n")
        self.assertEqual(out["frontmatter"], {"title": "X", "tags": ["a", "b"]})
        self.assertEqual(out["body"], {"key": "value"})

    def test_missing_frontmatter_treats_all_as_body(self):
        out = parse_frontmatter_and_body("just: body\n")
        self.assertIsNone(out["frontmatter"])
        self.assertEqual(out["body"], {"just": "body"})

    def test_invalid_yaml_raises_value_error(self):
        with self.assertRaises(ValueError):
            parse_frontmatter_and_body("---\n{bad: [unclosed\n---\nbody\n")
        with self.assertRaises(ValueError):
            parse_frontmatter_and_body(None)  # type: ignore[arg-type]


class DirectoryPipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "good.md").write_text("---\ntitle: Good\n---\nbody: yes\n")
        (root / "plain.txt").write_text("plain: body\n")
        (root / "bad.yaml").write_text("---\n{broken: [\n---\nbody\n")
        (root / "binary.md").write_bytes(b"\xff\xfe\x00\x01 not utf8 \xff")
        (root / "ignored.py").write_text("print('not whitelisted')\n")
        sub = root / "sub"
        sub.mkdir()
        (sub / "nested.yml").write_text("---\nkind: nested\n---\nn: 1\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_full_pipeline(self):
        out = process_directory_of_files(self.tmp.name)
        self.assertEqual(out["good.md"]["frontmatter"], {"title": "Good"})
        self.assertEqual(out["plain.txt"], {"frontmatter": None, "body": {"plain": "body"}})
        self.assertIn("error", out["bad.yaml"])       # logged, not omitted
        self.assertIn("error", out["binary.md"])      # decode failure recorded
        self.assertNotIn("ignored.py", out)           # extension whitelist
        self.assertEqual(out[os.path.join("sub", "nested.yml")]["frontmatter"], {"kind": "nested"})
        self.assertEqual(out["metadata"], {"succeeded": 3, "failed": 2, "skipped": 1})

    def test_missing_directory_fails_soft(self):
        out = process_directory_of_files("/nonexistent/dir/xyz")
        self.assertEqual(out["metadata"], {"succeeded": 0, "failed": 0, "skipped": 0})


if __name__ == "__main__":
    unittest.main()
