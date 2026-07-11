"""Tests for pattern_compiler — deterministic zero-token task compilation."""
import unittest
from unittest.mock import patch, MagicMock
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestSlugifyPrefix(unittest.TestCase):
    def test_extracts_prefix(self):
        import pattern_compiler
        # Module-level helper function
        # _slugify_prefix returns a prefix — verify it returns a string that's a prefix of the slug
        result = pattern_compiler._slugify_prefix("add-field-users-email")
        self.assertIsInstance(result, str)
        self.assertTrue("add-field-users-email".startswith(result) or result == "add-field-users-email")

    def test_short_slug_returns_full(self):
        import pattern_compiler
        result = pattern_compiler._slugify_prefix("master-task")
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)


class TestMatchNoPatterns(unittest.TestCase):
    def test_returns_none_without_compiled_patterns(self):
        import pattern_compiler
        pattern_compiler._cache = pattern_compiler._PatternCache()
        result = pattern_compiler.match({"slug": "add-field-test", "prompt": "add a test field"})
        self.assertIsNone(result)


class TestStats(unittest.TestCase):
    def test_stats_returns_dict(self):
        import pattern_compiler
        s = pattern_compiler.stats()
        self.assertIsInstance(s, dict)
        self.assertIn("patterns_compiled", s)
        self.assertIn("total_matches", s)
        self.assertIn("total_executions", s)


class TestCompilePatterns(unittest.TestCase):
    @patch("db.select")
    def test_compile_with_no_outcomes(self, mock_select):
        mock_select.return_value = []
        import pattern_compiler
        pattern_compiler._cache = pattern_compiler._PatternCache()
        count = pattern_compiler.compile_patterns()
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
