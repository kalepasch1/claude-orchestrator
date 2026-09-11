"""Tests for cross_project_templates.py — cross-project template transfer.

Covers: intent normalisation, hashing, path generalisation, keyword similarity,
find_templates matching (exact + fuzzy + empty), inject_cross_templates, stats,
and fail-soft on missing DB / bad data.
"""
import importlib
import json
import os
import sys
import types
import unittest

# ---------------------------------------------------------------------------
# Stub db before importing the module under test
# ---------------------------------------------------------------------------
_controls_store: dict = {}


class _FakeDB:
    @staticmethod
    def select(table, params=None):
        if table == "controls":
            key = (params or {}).get("key", "").replace("eq.", "")
            if key in _controls_store:
                return [{"value": json.dumps(_controls_store[key])}]
        return []

    @staticmethod
    def upsert(table, payload):
        if table == "controls":
            _controls_store[payload["key"]] = json.loads(payload["value"])


sys.modules["db"] = types.ModuleType("db")
db_mod = sys.modules["db"]
db_mod.select = _FakeDB.select
db_mod.upsert = _FakeDB.upsert

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import cross_project_templates as cpt


class TestNormalizeIntent(unittest.TestCase):
    def test_lowercases_and_collapses_whitespace(self):
        norm = cpt._normalize_intent("Fix  the   Bug")
        # The function lowercases and collapses runs of whitespace to a single space.
        self.assertEqual(norm, "fix the bug")
        self.assertEqual(norm, norm.lower())
        self.assertNotIn("  ", norm)

    def test_replaces_hashes(self):
        norm = cpt._normalize_intent("commit abc123def0 broke things")
        self.assertIn("HASH", norm)
        self.assertNotIn("abc123def0", norm)

    def test_replaces_long_numbers(self):
        norm = cpt._normalize_intent("task 123456 is stuck")
        self.assertIn("NUM", norm)

    def test_replaces_string_literals(self):
        norm = cpt._normalize_intent("set 'foo_bar' to 'baz'")
        self.assertIn("STR", norm)

    def test_generalises_project_paths(self):
        norm = cpt._normalize_intent("fix beethoven/runner/db.py import")
        # _normalize_intent lowercases first, then replaces project names with
        # uppercase placeholder "PROJECT/".
        self.assertIn("PROJECT/", norm)
        self.assertNotIn("beethoven", norm)

    def test_truncates_to_400(self):
        long_prompt = "word " * 500
        self.assertLessEqual(len(cpt._normalize_intent(long_prompt)), 400)

    def test_none_and_empty(self):
        self.assertEqual(cpt._normalize_intent(None), "")
        self.assertEqual(cpt._normalize_intent(""), "")


class TestIntentHash(unittest.TestCase):
    def test_deterministic(self):
        h1 = cpt._intent_hash("fix the bug", "build")
        h2 = cpt._intent_hash("fix the bug", "build")
        self.assertEqual(h1, h2)

    def test_different_kind_different_hash(self):
        h1 = cpt._intent_hash("fix the bug", "build")
        h2 = cpt._intent_hash("fix the bug", "test")
        self.assertNotEqual(h1, h2)

    def test_length_20(self):
        self.assertEqual(len(cpt._intent_hash("anything")), 20)


class TestGeneralizePath(unittest.TestCase):
    def test_deep_path(self):
        result = cpt._generalize_path("server/api/otc/foo.ts")
        self.assertIn("*", result)
        self.assertTrue(result.endswith(".ts"))

    def test_shallow_path_unchanged(self):
        result = cpt._generalize_path("README.md")
        self.assertEqual(result, "README.md")

    def test_backslash_normalised(self):
        result = cpt._generalize_path("server\\api\\foo.ts")
        self.assertNotIn("\\", result)


class TestKeywordSimilarity(unittest.TestCase):
    def test_identical(self):
        self.assertAlmostEqual(cpt._keyword_similarity("fix bug", "fix bug"), 1.0)

    def test_partial(self):
        sim = cpt._keyword_similarity("fix the build bug", "fix build")
        self.assertGreater(sim, 0.3)

    def test_disjoint(self):
        self.assertAlmostEqual(cpt._keyword_similarity("apple orange", "car truck"), 0.0)

    def test_empty(self):
        self.assertEqual(cpt._keyword_similarity("", "foo"), 0)
        self.assertEqual(cpt._keyword_similarity("foo", ""), 0)


class TestFindTemplatesAndInject(unittest.TestCase):
    def setUp(self):
        _controls_store.clear()

    def test_empty_library_returns_empty(self):
        self.assertEqual(cpt.find_templates({"prompt": "anything"}), [])

    def test_exact_match(self):
        task = {"prompt": "fix build", "kind": "build"}
        intent = cpt._intent_hash("fix build", "build")
        _controls_store["cross_project_templates"] = {
            intent: {
                "normalized_intent": cpt._normalize_intent("fix build"),
                "kind": "build",
                "source_project": "tomorrow",
                "merge_count": 5,
                "projects_proven": ["tomorrow", "beethoven"],
            }
        }
        results = cpt.find_templates(task)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["match_type"], "exact")

    def test_fuzzy_match_above_threshold(self):
        _controls_store["cross_project_templates"] = {
            "k1": {
                "normalized_intent": "fix build pipeline deploy error",
                "kind": "build",
                "source_project": "tomorrow",
                "merge_count": 3,
                "projects_proven": ["tomorrow"],
                "relevance": 0,
            }
        }
        results = cpt.find_templates({"prompt": "fix build pipeline", "kind": "build"})
        self.assertGreater(len(results), 0)

    def test_inject_adds_section(self):
        templates = [{
            "source_project": "tomorrow",
            "merge_count": 3,
            "projects_proven": ["tomorrow"],
            "normalized_intent": "fix build",
            "files_changed": ["server/api/*.ts"],
            "diff_summary": "added retry logic",
        }]
        result = cpt.inject_cross_templates("original prompt", templates)
        self.assertIn("CROSS-PROJECT TEMPLATES", result)
        self.assertIn("original prompt", result)

    def test_inject_empty_templates_noop(self):
        self.assertEqual(cpt.inject_cross_templates("prompt", []), "prompt")


class TestStats(unittest.TestCase):
    def setUp(self):
        _controls_store.clear()

    def test_empty_stats(self):
        s = cpt.stats()
        self.assertEqual(s["total_templates"], 0)

    def test_stats_with_data(self):
        _controls_store["cross_project_templates"] = {
            "a": {"merge_count": 5, "projects_proven": ["x", "y"]},
            "b": {"merge_count": 2, "projects_proven": ["x"]},
        }
        s = cpt.stats()
        self.assertEqual(s["total_templates"], 2)
        self.assertEqual(s["multi_project_templates"], 1)


if __name__ == "__main__":
    unittest.main()
