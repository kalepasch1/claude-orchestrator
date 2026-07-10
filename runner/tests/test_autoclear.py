#!/usr/bin/env python3
"""Tests for runner/autoclear.py — rule-based auto-clearing of operator approval cards."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import autoclear


def _card(**kw):
    base = {
        "project": "beethoven",
        "kind": "operator",
        "title": "[operator] deploy staging build",
        "detail": "deploy staging build (cost ~$5)",
        "approvals_required": 1,
    }
    base.update(kw)
    return base


_RULE = [{"id": "r1", "project": "beethoven", "kind": "operator", "max_usd": 10.0, "enabled": True}]
_RULE_NO_PROJECT = [{"id": "r2", "kind": "operator", "max_usd": 10.0, "enabled": True}]


class TestAutoApprove(unittest.TestCase):
    def setUp(self):
        # Ensure kill-switch is on for positive tests
        patcher = patch.object(autoclear, "AUTOCLEAR_ENABLED", True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_matching_non_prod_under_threshold_auto_approves(self):
        decision, rule_id = autoclear.autoclear_decision(_card(), _RULE)
        self.assertEqual(decision, "approved")
        self.assertEqual(rule_id, "r1")

    def test_matching_rule_with_no_project_filter_approves(self):
        decision, rule_id = autoclear.autoclear_decision(_card(), _RULE_NO_PROJECT)
        self.assertEqual(decision, "approved")

    def test_amount_at_threshold_approves(self):
        card = _card(detail="deploy build (cost ~$10)")
        decision, _ = autoclear.autoclear_decision(card, _RULE)
        self.assertEqual(decision, "approved")

    def test_amount_over_threshold_does_not_approve(self):
        card = _card(detail="deploy build (cost ~$11)")
        decision, _ = autoclear.autoclear_decision(card, _RULE)
        self.assertIsNone(decision)

    def test_no_amount_and_rule_has_max_usd_does_not_approve(self):
        card = _card(detail="some task with no dollar amount")
        decision, _ = autoclear.autoclear_decision(card, _RULE)
        self.assertIsNone(decision)

    def test_no_matching_rule_returns_none(self):
        decision, rule_id = autoclear.autoclear_decision(_card(), [])
        self.assertIsNone(decision)
        self.assertIsNone(rule_id)


class TestHardGuards(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(autoclear, "AUTOCLEAR_ENABLED", True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_two_approvals_required_never_auto_approves(self):
        card = _card(approvals_required=2)
        decision, _ = autoclear.autoclear_decision(card, _RULE)
        self.assertIsNone(decision)

    def test_legal_card_never_auto_approves(self):
        card = _card(kind="legal", detail="sign legal agreement ($5)")
        decision, _ = autoclear.autoclear_decision(card, _RULE + [
            {"id": "legal-r", "kind": "legal", "max_usd": 1000.0, "enabled": True}
        ])
        self.assertIsNone(decision)

    def test_prod_deploy_card_never_auto_approves(self):
        card = _card(detail="deploy prod build ($5)")
        decision, _ = autoclear.autoclear_decision(card, _RULE)
        self.assertIsNone(decision)

    def test_production_keyword_blocks_auto_approve(self):
        card = _card(detail="roll out to production environment ($5)")
        decision, _ = autoclear.autoclear_decision(card, _RULE)
        self.assertIsNone(decision)


class TestKillSwitch(unittest.TestCase):
    def test_kill_switch_off_forces_all_pending(self):
        with patch.object(autoclear, "AUTOCLEAR_ENABLED", False):
            decision, rule_id = autoclear.autoclear_decision(_card(), _RULE)
        self.assertIsNone(decision)
        self.assertIsNone(rule_id)

    def test_kill_switch_on_allows_approval(self):
        with patch.object(autoclear, "AUTOCLEAR_ENABLED", True):
            decision, _ = autoclear.autoclear_decision(_card(), _RULE)
        self.assertEqual(decision, "approved")


class TestParseUsd(unittest.TestCase):
    def test_parses_dollar_amount(self):
        self.assertEqual(autoclear._parse_usd("costs $12.50"), 12.5)

    def test_returns_none_when_absent(self):
        self.assertIsNone(autoclear._parse_usd("no amount here"))

    def test_returns_none_on_empty(self):
        self.assertIsNone(autoclear._parse_usd(""))
        self.assertIsNone(autoclear._parse_usd(None))


if __name__ == "__main__":
    unittest.main()
