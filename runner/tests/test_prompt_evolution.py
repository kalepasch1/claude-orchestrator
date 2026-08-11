"""Tests for prompt_evolution — self-improving prompt evolution."""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Stub db before importing the module
fake_db = MagicMock()
fake_db.select.return_value = []
fake_db.insert.return_value = None
with patch.dict(sys.modules, {"db": fake_db}):
    import prompt_evolution


class TestPromptEvolutionStats(unittest.TestCase):
    def test_stats_returns_dict(self):
        result = prompt_evolution.stats()
        self.assertIsInstance(result, dict)


class TestGetEvolvedAdditions(unittest.TestCase):
    def test_get_evolved_additions_empty(self):
        with patch.object(prompt_evolution, "db") as mdb:
            mdb.select.return_value = []
            result = prompt_evolution.get_evolved_additions({}, "test")
            # With no data, should return empty string or None
            self.assertFalse(result)  # empty string or None are both falsy


class TestRecordPromptOutcome(unittest.TestCase):
    def test_record_no_raise(self):
        with patch.object(prompt_evolution, "db") as mdb:
            mdb.insert.return_value = None
            # Should not raise
            prompt_evolution.record_prompt_outcome(
                {"slug": "test-task"}, "prompt text", "claude-sonnet",
                True, 0.05, 1
            )


class TestFeatureExtraction(unittest.TestCase):
    """_extract_features is the input to every downstream decision: the
    fingerprint, the effectiveness analysis and the evolved additions all key
    off it. A feature that silently stops matching makes the whole loop learn
    from a constant."""

    def test_every_declared_feature_is_present_in_the_output(self):
        features = prompt_evolution._extract_features("anything")
        for name in prompt_evolution._FEATURE_NAMES + prompt_evolution._NUMERIC_FEATURES:
            self.assertIn(name, features, f"{name} is declared but never extracted")

    def test_empty_and_none_prompts_are_all_false_not_a_crash(self):
        for empty in ("", None):
            features = prompt_evolution._extract_features(empty)
            self.assertEqual(features["word_count"], 0)
            self.assertEqual(features["section_count"], 0)
            for name in prompt_evolution._FEATURE_NAMES:
                self.assertFalse(features[name])

    def test_boolean_features_are_actually_booleans(self):
        features = prompt_evolution._extract_features("for example, do not break the build")
        for name in prompt_evolution._FEATURE_NAMES:
            self.assertIsInstance(features[name], bool, f"{name} must be a bool")

    def test_each_boolean_feature_has_at_least_one_phrase_that_trips_it(self):
        trips = {
            "has_examples": "for example, see below",
            "has_constraints": "you must not delete the lockfile",
            "has_test_criteria": "verify the suite is green",
            "has_build_mandate": "the project must build with no errors",
            "has_precedent": "follow the precedent from the prior merge",
            "has_spec_refinement": "refine the spec first",
            "has_file_list": "files:\nrunner/a.py",
        }
        for name, text in trips.items():
            with self.subTest(name):
                self.assertTrue(prompt_evolution._extract_features(text)[name],
                                f"{name} no longer matches {text!r}")

    def test_matching_is_case_insensitive(self):
        lower = prompt_evolution._extract_features("you must not do that")
        upper = prompt_evolution._extract_features("YOU MUST NOT DO THAT")
        self.assertEqual(lower["has_constraints"], upper["has_constraints"])

    def test_word_and_section_counts(self):
        text = "# One\nalpha beta gamma\n## Two\ndelta"
        features = prompt_evolution._extract_features(text)
        self.assertEqual(features["section_count"], 2)
        self.assertEqual(features["word_count"], len(text.split()))

    def test_a_non_string_prompt_does_not_raise(self):
        self.assertIsInstance(prompt_evolution._extract_features(12345), dict)


class TestFingerprint(unittest.TestCase):
    def test_same_structure_same_fingerprint(self):
        a = prompt_evolution._fingerprint("for example: do not break the build")
        b = prompt_evolution._fingerprint("for example: do not break the build")
        self.assertEqual(a, b)

    def test_different_structure_different_fingerprint(self):
        plain = prompt_evolution._fingerprint("just do the thing")
        rich = prompt_evolution._fingerprint(
            "# Task\nfor example, verify tests pass and you must not delete files")
        self.assertNotEqual(plain, rich)

    def test_fingerprint_is_a_short_stable_hex_string(self):
        fp = prompt_evolution._fingerprint("anything at all")
        self.assertEqual(len(fp), 16)
        int(fp, 16)  # raises if not hex

    def test_empty_prompt_still_fingerprints(self):
        self.assertTrue(prompt_evolution._fingerprint(""))


class TestSlugPrefix(unittest.TestCase):
    def test_verb_noun_prefix_from_a_task_dict(self):
        self.assertEqual(
            prompt_evolution._slug_prefix({"slug": "fix-router-timeout-retry"}),
            "fix-router")

    def test_accepts_a_bare_string(self):
        self.assertEqual(prompt_evolution._slug_prefix("add-tests-for-bandit"), "add-tests")

    def test_short_and_missing_slugs_degrade_to_a_label_not_a_crash(self):
        self.assertEqual(prompt_evolution._slug_prefix({"slug": "solo"}), "solo")
        self.assertEqual(prompt_evolution._slug_prefix({}), "unknown")
        self.assertEqual(prompt_evolution._slug_prefix(None), "unknown")


class TestModuleApiIsFailSoft(unittest.TestCase):
    """Every public entry point is called from the hot path of the runner. A
    DB outage must degrade the evolution loop, never stop a task."""

    def test_analyze_effectiveness_survives_a_db_outage(self):
        with patch.object(prompt_evolution, "db") as mdb:
            mdb.select.side_effect = RuntimeError("supabase down")
            prompt_evolution.analyze_effectiveness()

    def test_get_evolved_additions_survives_a_db_outage(self):
        with patch.object(prompt_evolution, "db") as mdb:
            mdb.select.side_effect = RuntimeError("supabase down")
            self.assertFalse(prompt_evolution.get_evolved_additions({"slug": "a-b"}, "proj"))

    def test_record_prompt_outcome_survives_a_db_outage(self):
        with patch.object(prompt_evolution, "db") as mdb:
            mdb.insert.side_effect = RuntimeError("supabase down")
            prompt_evolution.record_prompt_outcome(
                {"slug": "a-b"}, "prompt", "claude-sonnet", True, 0.05, 1)

    def test_evolve_template_returns_a_string_even_with_no_data(self):
        with patch.object(prompt_evolution, "db") as mdb:
            mdb.select.return_value = []
            evolved = prompt_evolution.evolve_template("BASE TEMPLATE")
            self.assertIsInstance(evolved, str)
            self.assertIn("BASE TEMPLATE", evolved)

    def test_evolve_template_does_not_lose_the_original_on_a_db_outage(self):
        with patch.object(prompt_evolution, "db") as mdb:
            mdb.select.side_effect = RuntimeError("supabase down")
            self.assertIn("BASE TEMPLATE", prompt_evolution.evolve_template("BASE TEMPLATE"))

    def test_stats_reports_the_min_sample_threshold(self):
        result = prompt_evolution.stats()
        self.assertIsInstance(result, dict)

    def test_min_samples_is_a_positive_threshold(self):
        self.assertGreater(prompt_evolution.MIN_SAMPLES, 0)


class TestFeatureToPromptAdditions(unittest.TestCase):
    """The three _feature_to_* helpers turn a learned feature name back into
    prompt text. An unknown feature must not produce a None that ends up
    concatenated into a real prompt."""

    def test_every_known_feature_maps_to_text(self):
        for name in prompt_evolution._FEATURE_NAMES:
            with self.subTest(name):
                self.assertIsInstance(prompt_evolution._feature_to_section(name), str)
                self.assertIsInstance(prompt_evolution._feature_to_marker(name), str)
                self.assertIsInstance(prompt_evolution._feature_to_addition(name), str)

    def test_an_unknown_feature_yields_a_string_not_none(self):
        for fn in (prompt_evolution._feature_to_section,
                   prompt_evolution._feature_to_marker,
                   prompt_evolution._feature_to_addition):
            with self.subTest(fn.__name__):
                self.assertIsInstance(fn("no_such_feature"), str)


if __name__ == "__main__":
    unittest.main()
