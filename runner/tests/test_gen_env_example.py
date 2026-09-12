#!/usr/bin/env python3
"""Tests for scripts/gen_env_example.py — the generated configuration template.

The safety property that matters most is the last class: this file is COMMITTED, so it
must never carry a credential value. Everything else pins the scanner's accuracy, because
a template that misreports required-vs-optional is worse than no template.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "scripts"))

import gen_env_example as gee  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class ScannerTests(unittest.TestCase):
    def test_subscript_access_is_required(self):
        found = gee.scan_source('import os\nx = os.environ["ORCH_THING"]\n')
        self.assertTrue(found["ORCH_THING"]["required"])

    def test_get_with_a_default_is_optional_and_records_it(self):
        found = gee.scan_source('import os\nx = os.environ.get("ORCH_THING", "7")\n')
        self.assertFalse(found["ORCH_THING"]["required"])
        self.assertEqual(found["ORCH_THING"]["defaults"], {"7"})

    def test_getenv_is_recognised(self):
        found = gee.scan_source('import os\nx = os.getenv("ORCH_THING", "abc")\n')
        self.assertIn("ORCH_THING", found)
        self.assertEqual(found["ORCH_THING"]["defaults"], {"abc"})

    def test_a_var_read_both_ways_is_required(self):
        """Required wins: one raising read is enough to make it mandatory."""
        found = gee.scan_source(
            'import os\na = os.environ.get("ORCH_X", "1")\nb = os.environ["ORCH_X"]\n')
        self.assertTrue(found["ORCH_X"]["required"])

    def test_system_vars_are_excluded(self):
        found = gee.scan_source('import os\nx = os.environ["PATH"]\n')
        self.assertNotIn("PATH", found)

    def test_a_non_literal_default_is_not_guessed_at(self):
        found = gee.scan_source('import os\nd = "x"\nv = os.environ.get("ORCH_X", d)\n')
        self.assertEqual(found["ORCH_X"]["defaults"], set())

    def test_an_upper_snake_constant_default_is_resolved(self):
        """Resolving a named constant is exact, not a guess — it is the same value.

        The codebase is actively moving defaults OUT of `os.environ.get(N, "3600")`
        and into named constants, because convention-lint's MAGIC_NUMBERS rule pushes
        every author that way. Without this, each such improvement silently blanked
        the knob's documented default in .env.example — which is where an operator
        goes to learn what a knob does when unset. Twelve had already gone that way.
        """
        found = gee.scan_source(
            'import os\nGATE_TIMEOUT_DEFAULT = 3600\n'
            'v = os.environ.get("ORCH_X", GATE_TIMEOUT_DEFAULT)\n')
        self.assertEqual(found["ORCH_X"]["defaults"], {"3600"})

    def test_str_around_a_constant_is_resolved(self):
        """A string-typed knob whose default lives in an int constant is written so."""
        found = gee.scan_source(
            'import os\nGATE_TIMEOUT_DEFAULT = 3600\n'
            'v = os.environ.get("ORCH_X", str(GATE_TIMEOUT_DEFAULT))\n')
        self.assertEqual(found["ORCH_X"]["defaults"], {"3600"})

    def test_a_constant_rebound_anywhere_is_not_resolved(self):
        """A second binding this scan cannot see is exactly how it would lie."""
        found = gee.scan_source(
            'import os\nGATE_TIMEOUT_DEFAULT = 3600\n'
            'if os.getenv("Y"):\n    GATE_TIMEOUT_DEFAULT = 60\n'
            'v = os.environ.get("ORCH_X", GATE_TIMEOUT_DEFAULT)\n')
        self.assertEqual(found["ORCH_X"]["defaults"], set())

    def test_a_lowercase_variable_is_still_not_resolved(self):
        """Only UPPER_SNAKE promises not to move; an ordinary variable does not."""
        found = gee.scan_source(
            'import os\ntimeout = 3600\nv = os.environ.get("ORCH_X", timeout)\n')
        self.assertEqual(found["ORCH_X"]["defaults"], set())

    def test_a_computed_default_is_still_not_guessed_at(self):
        found = gee.scan_source(
            'import os\nA = 60\nv = os.environ.get("ORCH_X", A * 60)\n')
        self.assertEqual(found["ORCH_X"]["defaults"], set())

    def test_a_dynamic_name_is_not_reported(self):
        found = gee.scan_source('import os\nn = "ORCH_X"\nv = os.environ.get(n)\n')
        self.assertEqual(found, {})

    def test_a_syntax_error_does_not_raise(self):
        self.assertEqual(gee.scan_source("def (:\n"), {})

    def test_boolean_defaults_render_as_lowercase_words(self):
        found = gee.scan_source('import os\nv = os.environ.get("ORCH_X", True)\n')
        self.assertEqual(found["ORCH_X"]["defaults"], {"true"})


class TestExclusionTests(unittest.TestCase):
    def test_test_paths_are_identified(self):
        for path in ("runner/tests/test_x.py", "runner/test_x.py", "tools/test/x.py"):
            self.assertTrue(gee.is_test_path(path), path)

    def test_ordinary_modules_are_not(self):
        for path in ("runner/db.py", "tools/convention_lint.py", "scripts/x.py"):
            self.assertFalse(gee.is_test_path(path), path)


class SecretSafetyTests(unittest.TestCase):
    """This file is committed. A credential in it is the failure that matters."""

    def test_secret_names_are_detected(self):
        for name in ("OPENAI_API_KEY", "GITHUB_PAT", "DB_PASSWORD", "ORCH_SUPABASE_SECRET",
                     "SOME_TOKEN", "X_CREDENTIAL"):
            self.assertTrue(gee.is_secret(name), name)

    def test_ordinary_names_are_not(self):
        for name in ("ORCH_MAX_ROWS", "MAX_PARALLEL", "ORCH_TIMEOUT"):
            self.assertFalse(gee.is_secret(name), name)

    def test_a_secret_is_rendered_with_an_empty_value_even_if_it_has_a_default(self):
        rendered = "\n".join(gee._render_one(
            "OPENAI_API_KEY", {"required": True, "defaults": {"sk-live-do-not-commit"},
                               "files": {"runner/x.py"}}))
        self.assertIn("OPENAI_API_KEY=\n", rendered + "\n")
        self.assertNotIn("sk-live-do-not-commit", rendered)

    def test_the_generated_file_carries_no_secret_values(self):
        content = gee.render(gee.scan_repo(REPO_ROOT))
        for line in content.splitlines():
            if line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            if gee.is_secret(name):
                self.assertEqual(value, "", f"{name} must be empty in a committed template")


class RenderTests(unittest.TestCase):
    def test_output_is_deterministic(self):
        variables = gee.scan_repo(REPO_ROOT)
        self.assertEqual(gee.render(variables), gee.render(variables))

    def test_required_and_optional_sections_are_both_present(self):
        content = gee.render({
            "ORCH_A": {"required": True, "defaults": set(), "files": {"runner/a.py"}},
            "ORCH_B": {"required": False, "defaults": {"3"}, "files": {"runner/b.py"}},
        })
        self.assertIn("REQUIRED (1)", content)
        self.assertIn("OPTIONAL (1)", content)
        self.assertIn("ORCH_B=3", content)

    def test_conflicting_defaults_are_surfaced_not_silently_resolved(self):
        content = gee.render({
            "MAX_PARALLEL": {"required": False, "defaults": {"4", "10", "12"},
                             "files": {"runner/a.py"}},
        })
        self.assertIn("differing defaults", content)

    def test_an_empty_scan_still_renders_both_sections(self):
        content = gee.render({})
        self.assertIn("REQUIRED (0)", content)
        self.assertIn("(none)", content)


class CheckModeTests(unittest.TestCase):
    def test_check_passes_on_the_committed_file(self):
        """The committed .env.example must match the code. This is the CI gate."""
        committed = os.path.join(REPO_ROOT, ".env.example")
        self.assertTrue(os.path.exists(committed), ".env.example is missing")
        self.assertEqual(gee.main(["--check", "--out", committed]), 0)

    def test_check_fails_on_a_drifted_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".env.example")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("STALE=1\n")
            self.assertEqual(gee.main(["--check", "--out", path]), 1)

    def test_check_fails_when_the_file_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(gee.main(["--check", "--out", os.path.join(tmp, "nope")]), 1)


if __name__ == "__main__":
    unittest.main()
