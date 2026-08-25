"""Tests for cowork_assemble — CLI bridge for cowork executor enrichment."""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Stub db before importing the module
fake_db = MagicMock()
with patch.dict(sys.modules, {"db": fake_db, "prompt_assembler": MagicMock()}):
    import cowork_assemble


class TestGetVercelConfig(unittest.TestCase):
    """Tests for get_vercel_config env + DB reading."""

    def test_the_token_is_withheld_even_when_the_env_has_one(self):
        """The security invariant, asserted in the direction the module states it.

        This used to be test_reads_token_from_env, asserting
        result["token"] == "tok_test". get_vercel_config ends with a literal
        `"token": ""` and its docstring says why: "Cowork tasks must never
        receive the account token: direct CLI deployments bypass Git branch
        gates, release batching, and production verification." So the test was
        red permanently, and the only way to make it green would have been to
        hand cowork agents the account token.

        team_id is metadata and IS passed through, which is what separates this
        from a test that just asserts the function returns nothing useful.
        """
        with patch.dict(os.environ, {"VERCEL_TOKEN": "tok_test", "VERCEL_TEAM_ID": "team_x"}, clear=False):
            result = cowork_assemble.get_vercel_config()
            self.assertEqual(result["token"], "",
                             "the Vercel account token must never reach a cowork agent")
            self.assertEqual(result["team_id"], "team_x")

    def test_returns_empty_on_no_env(self):
        # patch.object, not `cowork_assemble._safe_import = MagicMock(...)`.
        # The bare assignment had no restore, and unittest runs this class's
        # methods alphabetically, so it left _safe_import stubbed for every test
        # that followed -- including TestSafeImport.test_returns_module_on_success
        # two classes down, which then read None for `os` and failed.
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(cowork_assemble, "_safe_import", return_value=None):
            result = cowork_assemble.get_vercel_config()
            self.assertEqual(result["token"], "")
            self.assertEqual(result["team_id"], "")
            self.assertIsInstance(result["project_map"], dict)

    def test_collects_project_map_from_env(self):
        env = {
            "VERCEL_TOKEN": "",
            "VERCEL_TEAM_ID": "",
            "VERCEL_PROJECT_BEETHOVEN": "prj_abc",
            "VERCEL_PROJECT_TOMORROW": "prj_xyz",
        }
        with patch.dict(os.environ, env, clear=False), \
                patch.object(cowork_assemble, "_safe_import", return_value=None):
            result = cowork_assemble.get_vercel_config()
            self.assertEqual(result["project_map"]["beethoven"], "prj_abc")
            self.assertEqual(result["project_map"]["tomorrow"], "prj_xyz")


class TestSafeImport(unittest.TestCase):
    """Tests for _safe_import graceful fallback."""

    def test_returns_none_on_missing_module(self):
        result = cowork_assemble._safe_import("nonexistent_module_xyz_999")
        self.assertIsNone(result)

    def test_returns_module_on_success(self):
        result = cowork_assemble._safe_import("os")
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
