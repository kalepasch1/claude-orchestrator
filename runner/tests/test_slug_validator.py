#!/usr/bin/env python3
"""Tests for slug_validator — ensures no duplicate-slug errors."""
import os, sys, unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import slug_validator


class TestEnsureUnique(unittest.TestCase):
    @patch("slug_validator._existing_slugs", return_value=set())
    def test_fresh_slug_unchanged(self, _):
        self.assertEqual(slug_validator.ensure_unique("my-task", "proj1"), "my-task")

    @patch("slug_validator._existing_slugs", return_value={"my-task"})
    def test_collision_appends_suffix(self, _):
        self.assertEqual(slug_validator.ensure_unique("my-task", "proj1"), "my-task-2")

    @patch("slug_validator._existing_slugs", return_value={"my-task", "my-task-2", "my-task-3"})
    def test_skips_taken_suffixes(self, _):
        self.assertEqual(slug_validator.ensure_unique("my-task", "proj1"), "my-task-4")

    def test_empty_slug_raises(self):
        with self.assertRaises(ValueError):
            slug_validator.ensure_unique("", "proj1")

    def test_none_slug_raises(self):
        with self.assertRaises(ValueError):
            slug_validator.ensure_unique(None, "proj1")


class TestValidateNoDuplicates(unittest.TestCase):
    def test_no_dupes(self):
        tasks = [{"slug": "a"}, {"slug": "b"}, {"slug": "c"}]
        self.assertEqual(slug_validator.validate_no_duplicates(tasks), [])

    def test_finds_dupes(self):
        tasks = [{"slug": "a"}, {"slug": "b"}, {"slug": "a"}]
        dupes = slug_validator.validate_no_duplicates(tasks)
        self.assertEqual(len(dupes), 1)
        self.assertEqual(dupes[0][0], "a")
        self.assertEqual(dupes[0][1], [0, 2])

    def test_empty_list(self):
        self.assertEqual(slug_validator.validate_no_duplicates([]), [])

    def test_none_input(self):
        self.assertEqual(slug_validator.validate_no_duplicates(None), [])


class TestDeduplicateBatch(unittest.TestCase):
    @patch("slug_validator._existing_slugs", return_value=set())
    def test_internal_dedup(self, _):
        tasks = [{"slug": "x"}, {"slug": "x"}, {"slug": "x"}]
        slug_validator.deduplicate_batch(tasks, "proj1")
        slugs = [t["slug"] for t in tasks]
        self.assertEqual(len(set(slugs)), 3)
        self.assertIn("x", slugs)

    @patch("slug_validator._existing_slugs", return_value=set())
    def test_preserves_unique(self, _):
        tasks = [{"slug": "a"}, {"slug": "b"}]
        slug_validator.deduplicate_batch(tasks, "proj1")
        self.assertEqual([t["slug"] for t in tasks], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
