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

    def test_reads_token_from_env(self):
        with patch.dict(os.environ, {"VERCEL_TOKEN": "tok_test", "VERCEL_TEAM_ID": "team_x"}, clear=False):
            result = cowork_assemble.get_vercel_config()
            self.assertEqual(result["token"], "tok_test")
            self.assertEqual(result["team_id"], "team_x")

    def test_returns_empty_on_no_env(self):
        with patch.dict(os.environ, {}, clear=True):
            # Suppress DB fallback
            cowork_assemble._safe_import = MagicMock(return_value=None)
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
        with patch.dict(os.environ, env, clear=False):
            cowork_assemble._safe_import = MagicMock(return_value=None)
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
