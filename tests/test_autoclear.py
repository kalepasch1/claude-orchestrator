"""Test autoclear.py rule matching and hard guards."""
import os
import sys
import unittest
from unittest import mock

# Add runner to path so we can import autoclear
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "runner"))

import autoclear


class TestAutoclearDecision(unittest.TestCase):
    """Tests for autoclear_decision() logic."""

    def setUp(self):
        """Set up test fixtures."""
        self.basic_rule = {
            "id": "r-operator-10",
            "project": "beethoven",
            "kind": "operator",
            "max_usd": 10.0,
            "enabled": True,
        }
        self.deploy_rule = {
            "id": "r-deploy-50",
            "kind": "deploy",
            "max_usd": 50.0,
            "enabled": True,
        }
        self.basic_card = {
            "project": "beethoven",
            "kind": "operator",
            "title": "Test approval",
            "detail": "Do something costing $5",
            "approvals_required": 1,
        }

    def test_autoclear_enabled_env_var_required(self):
        """Kill-switch: if AUTOCLEAR_ENABLED is not 'true', no auto-approvals happen."""
        with mock.patch.dict(os.environ, {"AUTOCLEAR_ENABLED": "false"}):
            # Reload module to pick up the env var
            import importlib
            importlib.reload(autoclear)
            decision, rule_id = autoclear.autoclear_decision(self.basic_card, [self.basic_rule])
            self.assertIsNone(decision)
            self.assertIsNone(rule_id)

    def test_non_prod_deploy_under_threshold_auto_approves(self):
        """A matching non-prod deploy under the threshold auto-approves."""
        with mock.patch.dict(os.environ, {"AUTOCLEAR_ENABLED": "true"}):
            # Reload to pick up env var
            import importlib
            importlib.reload(autoclear)

            card = {
                "project": None,  # Match all projects
                "kind": "deploy",
                "title": "Deploy service",
                "detail": "Deploying to staging, costing $25",
                "approvals_required": 1,
            }
            decision, rule_id = autoclear.autoclear_decision(card, [self.deploy_rule])
            self.assertEqual(decision, "approved")
            self.assertEqual(rule_id, "r-deploy-50")

    def test_two_key_card_never_auto_approves(self):
        """A card requiring 2+ approvals never auto-approves."""
        with mock.patch.dict(os.environ, {"AUTOCLEAR_ENABLED": "true"}):
            import importlib
            importlib.reload(autoclear)

            card = {
                "project": "beethoven",
                "kind": "operator",
                "title": "Multi-sig approval",
                "detail": "Do something costing $5",
                "approvals_required": 2,
            }
            decision, rule_id = autoclear.autoclear_decision(card, [self.basic_rule])
            self.assertIsNone(decision)
            self.assertIsNone(rule_id)

    def test_legal_card_never_auto_approves(self):
        """A legal card never auto-approves, even with matching rules."""
        with mock.patch.dict(os.environ, {"AUTOCLEAR_ENABLED": "true"}):
            import importlib
            importlib.reload(autoclear)

            legal_rule = {
                "id": "r-legal-0",
                "kind": "legal",
                "max_usd": 100.0,
                "enabled": True,
            }
            card = {
                "project": None,
                "kind": "legal",
                "title": "Legal review needed",
                "detail": "Needs counsel sign-off, costing $50",
                "approvals_required": 1,
            }
            decision, rule_id = autoclear.autoclear_decision(card, [legal_rule])
            self.assertIsNone(decision)
            self.assertIsNone(rule_id)

    def test_prod_deploy_card_never_auto_approves(self):
        """A card mentioning prod/production never auto-approves."""
        with mock.patch.dict(os.environ, {"AUTOCLEAR_ENABLED": "true"}):
            import importlib
            importlib.reload(autoclear)

            card = {
                "project": None,
                "kind": "deploy",
                "title": "Production deploy",
                "detail": "Deploy to production, costing $30",
                "approvals_required": 1,
            }
            decision, rule_id = autoclear.autoclear_decision(card, [self.deploy_rule])
            self.assertIsNone(decision)
            self.assertIsNone(rule_id)

    def test_prod_deploy_case_insensitive(self):
        """Prod/production detection is case-insensitive."""
        with mock.patch.dict(os.environ, {"AUTOCLEAR_ENABLED": "true"}):
            import importlib
            importlib.reload(autoclear)

            for prod_text in ["PROD", "Production", "PRODUCTION", "PrOd"]:
                card = {
                    "project": None,
                    "kind": "deploy",
                    "title": f"Deploy to {prod_text}",
                    "detail": f"Deploying to {prod_text} environment",
                    "approvals_required": 1,
                }
                decision, rule_id = autoclear.autoclear_decision(card, [self.deploy_rule])
                self.assertIsNone(decision, f"Should reject {prod_text}")

    def test_kill_switch_off_forces_pending(self):
        """With kill-switch off, all cards remain pending."""
        with mock.patch.dict(os.environ, {"AUTOCLEAR_ENABLED": "false"}):
            import importlib
            importlib.reload(autoclear)

            card = {
                "project": "beethoven",
                "kind": "operator",
                "title": "Simple approval",
                "detail": "Costing $5",
                "approvals_required": 1,
            }
            decision, rule_id = autoclear.autoclear_decision(card, [self.basic_rule])
            self.assertIsNone(decision)
            self.assertIsNone(rule_id)

    def test_rule_project_filter(self):
        """Rules only match cards with matching project (or rule with no project filter)."""
        with mock.patch.dict(os.environ, {"AUTOCLEAR_ENABLED": "true"}):
            import importlib
            importlib.reload(autoclear)

            # Card from different project doesn't match project-specific rule
            card = {
                "project": "other-project",
                "kind": "operator",
                "title": "Approval",
                "detail": "Costing $5",
                "approvals_required": 1,
            }
            decision, rule_id = autoclear.autoclear_decision(card, [self.basic_rule])
            self.assertIsNone(decision)

    def test_rule_no_project_filter_matches_all(self):
        """A rule with no project filter matches any project."""
        with mock.patch.dict(os.environ, {"AUTOCLEAR_ENABLED": "true"}):
            import importlib
            importlib.reload(autoclear)

            rule_no_project = {
                "id": "r-any-10",
                "kind": "operator",
                "max_usd": 10.0,
                "enabled": True,
            }
            card = {
                "project": "any-project",
                "kind": "operator",
                "title": "Approval",
                "detail": "Costing $5",
                "approvals_required": 1,
            }
            decision, rule_id = autoclear.autoclear_decision(card, [rule_no_project])
            self.assertEqual(decision, "approved")
            self.assertEqual(rule_id, "r-any-10")

    def test_amount_above_threshold_doesnt_match(self):
        """A card with amount above rule threshold doesn't auto-approve."""
        with mock.patch.dict(os.environ, {"AUTOCLEAR_ENABLED": "true"}):
            import importlib
            importlib.reload(autoclear)

            card = {
                "project": "beethoven",
                "kind": "operator",
                "title": "Expensive approval",
                "detail": "Costing $15 (above threshold)",
                "approvals_required": 1,
            }
            decision, rule_id = autoclear.autoclear_decision(card, [self.basic_rule])
            self.assertIsNone(decision)

    def test_no_amount_in_detail(self):
        """A card with no amount in detail doesn't match max_usd rule."""
        with mock.patch.dict(os.environ, {"AUTOCLEAR_ENABLED": "true"}):
            import importlib
            importlib.reload(autoclear)

            card = {
                "project": "beethoven",
                "kind": "operator",
                "title": "Approval",
                "detail": "Do something (no price mentioned)",
                "approvals_required": 1,
            }
            decision, rule_id = autoclear.autoclear_decision(card, [self.basic_rule])
            self.assertIsNone(decision)

    def test_empty_rules_no_auto_approval(self):
        """With no rules, no cards are auto-approved."""
        with mock.patch.dict(os.environ, {"AUTOCLEAR_ENABLED": "true"}):
            import importlib
            importlib.reload(autoclear)

            card = {
                "project": "beethoven",
                "kind": "operator",
                "title": "Approval",
                "detail": "Costing $5",
                "approvals_required": 1,
            }
            decision, rule_id = autoclear.autoclear_decision(card, [])
            self.assertIsNone(decision)

    def test_disabled_rule_ignored(self):
        """A disabled rule is not evaluated."""
        with mock.patch.dict(os.environ, {"AUTOCLEAR_ENABLED": "true"}):
            import importlib
            importlib.reload(autoclear)

            disabled_rule = dict(self.basic_rule, enabled=False)
            card = {
                "project": "beethoven",
                "kind": "operator",
                "title": "Approval",
                "detail": "Costing $5",
                "approvals_required": 1,
            }
            decision, rule_id = autoclear.autoclear_decision(card, [disabled_rule])
            self.assertIsNone(decision)

    def test_first_matching_rule_wins(self):
        """When multiple rules match, the first one wins."""
        with mock.patch.dict(os.environ, {"AUTOCLEAR_ENABLED": "true"}):
            import importlib
            importlib.reload(autoclear)

            rule1 = {
                "id": "r-first",
                "kind": "operator",
                "max_usd": 10.0,
                "enabled": True,
            }
            rule2 = {
                "id": "r-second",
                "kind": "operator",
                "max_usd": 20.0,
                "enabled": True,
            }
            card = {
                "project": None,
                "kind": "operator",
                "title": "Approval",
                "detail": "Costing $5",
                "approvals_required": 1,
            }
            decision, rule_id = autoclear.autoclear_decision(card, [rule1, rule2])
            self.assertEqual(rule_id, "r-first")

    def test_decimal_amounts(self):
        """Amounts with decimals are parsed correctly."""
        with mock.patch.dict(os.environ, {"AUTOCLEAR_ENABLED": "true"}):
            import importlib
            importlib.reload(autoclear)

            card = {
                "project": "beethoven",
                "kind": "operator",
                "title": "Approval",
                "detail": "Costing $9.50",
                "approvals_required": 1,
            }
            decision, rule_id = autoclear.autoclear_decision(card, [self.basic_rule])
            self.assertEqual(decision, "approved")

    def test_decimal_amount_above_threshold(self):
        """A decimal amount above threshold doesn't match."""
        with mock.patch.dict(os.environ, {"AUTOCLEAR_ENABLED": "true"}):
            import importlib
            importlib.reload(autoclear)

            card = {
                "project": "beethoven",
                "kind": "operator",
                "title": "Approval",
                "detail": "Costing $10.01",
                "approvals_required": 1,
            }
            decision, rule_id = autoclear.autoclear_decision(card, [self.basic_rule])
            self.assertIsNone(decision)


class TestParseAmount(unittest.TestCase):
    """Tests for _parse_usd() helper."""

    def test_parse_simple_amount(self):
        """Parse $X amount from detail."""
        result = autoclear._parse_usd("Do something costing $50")
        self.assertEqual(result, 50.0)

    def test_parse_decimal_amount(self):
        """Parse $X.YY amount."""
        result = autoclear._parse_usd("Cost: $12.34")
        self.assertEqual(result, 12.34)

    def test_parse_no_amount(self):
        """Return None if no amount found."""
        result = autoclear._parse_usd("No price here")
        self.assertIsNone(result)

    def test_parse_first_amount_only(self):
        """If multiple amounts, return the first."""
        result = autoclear._parse_usd("Cost $10, but really $20")
        self.assertEqual(result, 10.0)


if __name__ == "__main__":
    unittest.main()
