"""
test_red_team.py - material_red_team tests.

Tests: only-sensitive invocation, block/pass thresholds, budget cap, parse findings.
All mocked — no live API calls.
"""
import os, sys, json, unittest
from unittest.mock import patch, MagicMock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import material_red_team


class TestIsSensitive(unittest.TestCase):

    def test_explicit_sensitive(self):
        self.assertTrue(material_red_team._is_sensitive({"risk_level": "sensitive"}))

    def test_not_sensitive(self):
        self.assertFalse(material_red_team._is_sensitive({"risk_level": "low", "slug": "add-docs", "prompt": "update readme"}))

    def test_sensitive_by_slug(self):
        self.assertTrue(material_red_team._is_sensitive({"slug": "fix-auth-bypass", "prompt": ""}))

    def test_sensitive_by_prompt(self):
        self.assertTrue(material_red_team._is_sensitive({"slug": "task1", "prompt": "update stripe payment flow"}))


class TestParseFindings(unittest.TestCase):

    def test_valid_json(self):
        findings = material_red_team._parse_findings('[{"severity": 8, "description": "SQL injection"}]')
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], 8)

    def test_empty_array(self):
        self.assertEqual(material_red_team._parse_findings("[]"), [])

    def test_invalid_json(self):
        self.assertEqual(material_red_team._parse_findings("not json"), [])

    def test_json_with_preamble(self):
        text = "Here are the findings:\n[{\"severity\": 5, \"description\": \"info leak\"}]"
        findings = material_red_team._parse_findings(text)
        self.assertEqual(len(findings), 1)


class TestReview(unittest.TestCase):

    def test_skip_non_sensitive(self):
        result = material_red_team.review(
            {"risk_level": "low", "slug": "docs", "prompt": "update docs"},
            "diff content"
        )
        self.assertEqual(result["action"], "skip")

    @patch("material_red_team._get_daily_spend", return_value=100.0)
    def test_skip_budget_exhausted(self, _):
        result = material_red_team.review(
            {"risk_level": "sensitive"},
            "diff content"
        )
        self.assertEqual(result["action"], "skip")
        self.assertIn("budget", result["note"])

    @patch("material_red_team._record_spend")
    @patch("material_red_team._get_daily_spend", return_value=0.0)
    def test_block_on_high_severity(self, mock_spend, mock_record):
        mock_cli = MagicMock()
        mock_cli.run.return_value = {
            "text": json.dumps([{"severity": 9, "category": "auth", "description": "auth bypass", "file": "a.py", "line": 10}]),
            "cost_usd": 0.01,
        }
        material_red_team.claude_cli = mock_cli
        with patch("material_red_team.db") as mock_db:
            result = material_red_team.review(
                {"risk_level": "sensitive", "slug": "auth-fix", "project_id": "p1"},
                "diff with auth changes"
            )
        self.assertEqual(result["action"], "block")
        self.assertTrue(len(result["findings"]) >= 1)

    @patch("material_red_team._record_spend")
    @patch("material_red_team._get_daily_spend", return_value=0.0)
    def test_pass_on_low_severity(self, mock_spend, mock_record):
        mock_cli = MagicMock()
        mock_cli.run.return_value = {
            "text": json.dumps([{"severity": 3, "category": "info", "description": "minor issue", "file": "b.py", "line": 5}]),
            "cost_usd": 0.01,
        }
        material_red_team.claude_cli = mock_cli
        result = material_red_team.review(
            {"risk_level": "sensitive", "slug": "minor-fix"},
            "small diff"
        )
        self.assertEqual(result["action"], "pass")

    @patch("material_red_team._record_spend")
    @patch("material_red_team._get_daily_spend", return_value=0.0)
    def test_pass_on_no_findings(self, mock_spend, mock_record):
        mock_cli = MagicMock()
        mock_cli.run.return_value = {"text": "[]", "cost_usd": 0.01}
        material_red_team.claude_cli = mock_cli
        result = material_red_team.review(
            {"risk_level": "sensitive", "slug": "safe-fix"},
            "clean diff"
        )
        self.assertEqual(result["action"], "pass")
        self.assertEqual(len(result["findings"]), 0)

    @patch("material_red_team._get_daily_spend", return_value=0.0)
    def test_pass_on_api_failure(self, mock_spend):
        mock_cli = MagicMock()
        mock_cli.run.side_effect = Exception("API down")
        material_red_team.claude_cli = mock_cli
        result = material_red_team.review(
            {"risk_level": "sensitive", "slug": "task1"},
            "diff"
        )
        self.assertEqual(result["action"], "pass")
        self.assertIn("failed", result["note"])


if __name__ == "__main__":
    unittest.main()
