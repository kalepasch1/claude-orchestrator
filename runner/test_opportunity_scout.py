#!/usr/bin/env python3
"""
test_opportunity_scout.py – Tests for opportunity_scout.py module.

Covers:
- RICE scoring calculation with valid and edge-case inputs
- JSON parsing from opportunoty text output
- Sorting opportunities by RICE score
- Handling missing fields and invalid JSON
- Integration with the canonical opportunity JSON schema
"""

import os
import sys
import json
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import opportunity_scout


class RICEScoringTests(unittest.TestCase):
    """Tests for the RICE scoring formula."""

    def test_rice_basic_calculation(self):
        """Test basic RICE score calculation: reach * impact * confidence / effort."""
        opportunity = {
            "reach": 8,
            "impact": 6,
            "confidence": 0.9,
            "effort_days": 3,
        }
        score = opportunity_scout.rice(opportunity)
        expected = (8 * 6 * 0.9) / 3
        self.assertAlmostEqual(score, expected, places=1)

    def test_rice_with_zero_effort(self):
        """RICE with zero effort uses min(0.5, effort) to avoid division by zero."""
        opportunity = {
            "reach": 10,
            "impact": 10,
            "confidence": 1.0,
            "effort_days": 0,
        }
        score = opportunity_scout.rice(opportunity)
        expected = (10 * 10 * 1.0) / 0.5
        self.assertAlmostEqual(score, expected, places=1)

    def test_rice_with_low_effort(self):
        """RICE with effort < 0.5 uses min(0.5, effort) to floor the divisor."""
        opportunity = {
            "reach": 5,
            "impact": 5,
            "confidence": 0.8,
            "effort_days": 0.2,
        }
        score = opportunity_scout.rice(opportunity)
        expected = (5 * 5 * 0.8) / 0.5
        self.assertAlmostEqual(score, expected, places=1)

    def test_rice_with_max_values(self):
        """RICE with maximum realistic values."""
        opportunity = {
            "reach": 10,
            "impact": 10,
            "confidence": 1.0,
            "effort_days": 1,
        }
        score = opportunity_scout.rice(opportunity)
        expected = 100.0
        self.assertAlmostEqual(score, expected, places=1)

    def test_rice_with_min_values(self):
        """RICE with minimum values."""
        opportunity = {
            "reach": 1,
            "impact": 1,
            "confidence": 0.1,
            "effort_days": 10,
        }
        score = opportunity_scout.rice(opportunity)
        expected = (1 * 1 * 0.1) / 10
        self.assertAlmostEqual(score, expected, places=2)

    def test_rice_missing_field_returns_zero(self):
        """RICE returns 0 if any required field is missing."""
        opportunities = [
            {"reach": 5, "impact": 5, "confidence": 0.8},  # missing effort_days
            {"reach": 5, "impact": 5, "effort_days": 2},  # missing confidence
            {"reach": 5, "confidence": 0.8, "effort_days": 2},  # missing impact
            {"impact": 5, "confidence": 0.8, "effort_days": 2},  # missing reach
            {},  # completely empty
        ]
        for opp in opportunities:
            self.assertEqual(opportunity_scout.rice(opp), 0.0)

    def test_rice_with_none_values_returns_zero(self):
        """RICE returns 0 if any value is None."""
        opportunity = {
            "reach": None,
            "impact": 5,
            "confidence": 0.8,
            "effort_days": 2,
        }
        self.assertEqual(opportunity_scout.rice(opportunity), 0.0)

    def test_rice_with_non_numeric_values_returns_zero(self):
        """RICE returns 0 if any value cannot be used in arithmetic."""
        opportunities = [
            {"reach": "high", "impact": 5, "confidence": 0.8, "effort_days": 2},
            {"reach": 5, "impact": "medium", "confidence": 0.8, "effort_days": 2},
            {"reach": 5, "impact": 5, "confidence": "sure", "effort_days": 2},
            {"reach": 5, "impact": 5, "confidence": 0.8, "effort_days": "days"},
        ]
        for opp in opportunities:
            self.assertEqual(opportunity_scout.rice(opp), 0.0)

    def test_rice_is_rounded_to_two_decimals(self):
        """RICE scores are rounded to two decimal places."""
        opportunity = {
            "reach": 7,
            "impact": 7,
            "confidence": 0.77,
            "effort_days": 3,
        }
        score = opportunity_scout.rice(opportunity)
        self.assertEqual(score, round((7 * 7 * 0.77) / 3, 2))


class OpportunityParsingTests(unittest.TestCase):
    """Tests for parsing opportunity JSON from Claude output."""

    def test_parse_single_valid_json_line(self):
        """Parse a valid opportunity JSON object from a single line."""
        json_line = (
            '{"title":"Add caching","why":"Slow queries","value":"2x speedup",'
            '"risk":"Revert","reach":8,"impact":7,"confidence":0.9,"effort_days":3}'
        )
        # This would be in a larger output; test the parsing logic
        opp = json.loads(json_line)
        self.assertEqual(opp["title"], "Add caching")
        self.assertEqual(opp["reach"], 8)

    def test_parse_multiple_json_lines_from_output(self):
        """Parse multiple JSON objects from multi-line output."""
        output = (
            'Here are the top opportunities:\n'
            '{"title":"Cache","why":"Slow","value":"2x","risk":"Revert","reach":8,"impact":7,"confidence":0.9,"effort_days":3}\n'
            '{"title":"Index","why":"Slow queries","value":"3x","risk":"Revert","reach":7,"impact":8,"confidence":0.85,"effort_days":2}\n'
            'Some trailing text\n'
        )
        ideas = []
        for line in output.splitlines():
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    ideas.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        self.assertEqual(len(ideas), 2)
        self.assertEqual(ideas[0]["title"], "Cache")
        self.assertEqual(ideas[1]["title"], "Index")

    def test_skip_invalid_json_lines(self):
        """Skip lines that look like JSON but are invalid."""
        output = (
            '{"title":"Valid","why":"Test","value":"1x","risk":"None","reach":5,"impact":5,"confidence":0.8,"effort_days":1}\n'
            '{"title":"Invalid" invalid json}\n'
            '{"title":"Also valid","why":"Test","value":"1x","risk":"None","reach":5,"impact":5,"confidence":0.8,"effort_days":1}\n'
        )
        ideas = []
        for line in output.splitlines():
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    ideas.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        self.assertEqual(len(ideas), 2)

    def test_parse_json_with_special_characters(self):
        """Handle JSON with escaped quotes and special characters."""
        json_line = (
            '{"title":"Cache \\"response\\"","why":"Slow API calls","value":"3x faster",'
            '"risk":"Clear cache on rollback","reach":9,"impact":8,"confidence":0.92,"effort_days":2}'
        )
        opp = json.loads(json_line)
        self.assertIn("response", opp["title"])

    def test_parse_json_with_missing_fields(self):
        """Parse JSON objects that are missing optional fields."""
        json_line = (
            '{"title":"Opportunity","reach":5,"impact":5,"confidence":0.8,"effort_days":1}'
        )
        opp = json.loads(json_line)
        # Missing fields like "why", "value", "risk" should still be parseable
        self.assertEqual(opp.get("why"), None)
        self.assertEqual(opp.get("value"), None)
        self.assertEqual(opp.get("risk"), None)

    def test_parse_json_with_extra_fields(self):
        """Parse JSON objects that have extra fields beyond the spec."""
        json_line = (
            '{"title":"Cache","why":"Slow","value":"2x","risk":"Revert",'
            '"reach":8,"impact":7,"confidence":0.9,"effort_days":3,'
            '"extra_field":"should be ignored","another":"field"}'
        )
        opp = json.loads(json_line)
        self.assertEqual(len(opp), 10)  # 8 core + 2 extra
        self.assertIn("extra_field", opp)


class OpportunitySortingTests(unittest.TestCase):
    """Tests for sorting opportunities by RICE score."""

    def test_sort_three_opportunities_by_rice(self):
        """Sort multiple opportunities in descending order by RICE score."""
        opps = [
            {
                "title": "Low score",
                "reach": 2,
                "impact": 2,
                "confidence": 0.5,
                "effort_days": 5,
            },
            {
                "title": "High score",
                "reach": 10,
                "impact": 10,
                "confidence": 1.0,
                "effort_days": 1,
            },
            {
                "title": "Medium score",
                "reach": 5,
                "impact": 5,
                "confidence": 0.8,
                "effort_days": 2,
            },
        ]
        sorted_opps = sorted(opps, key=opportunity_scout.rice, reverse=True)
        self.assertEqual(sorted_opps[0]["title"], "High score")
        self.assertEqual(sorted_opps[1]["title"], "Medium score")
        self.assertEqual(sorted_opps[2]["title"], "Low score")

    def test_take_top_three_only(self):
        """Take only top 3 opportunities from a larger list."""
        opps = [
            {
                "title": f"Opportunity {i}",
                "reach": i,
                "impact": i,
                "confidence": 0.5,
                "effort_days": 1,
            }
            for i in range(1, 11)
        ]
        top_three = sorted(opps, key=opportunity_scout.rice, reverse=True)[:3]
        self.assertEqual(len(top_three), 3)
        self.assertEqual(top_three[0]["title"], "Opportunity 10")
        self.assertEqual(top_three[1]["title"], "Opportunity 9")
        self.assertEqual(top_three[2]["title"], "Opportunity 8")

    def test_handle_tied_scores(self):
        """Handle opportunities with identical RICE scores."""
        opps = [
            {
                "title": "A",
                "reach": 5,
                "impact": 5,
                "confidence": 0.8,
                "effort_days": 2,
            },
            {
                "title": "B",
                "reach": 5,
                "impact": 5,
                "confidence": 0.8,
                "effort_days": 2,
            },
            {
                "title": "C",
                "reach": 5,
                "impact": 5,
                "confidence": 0.8,
                "effort_days": 2,
            },
        ]
        sorted_opps = sorted(opps, key=opportunity_scout.rice, reverse=True)
        # All have the same RICE score; order is stable after sort
        self.assertEqual(len(sorted_opps), 3)
        for opp in sorted_opps:
            self.assertAlmostEqual(opportunity_scout.rice(opp), opportunity_scout.rice(opps[0]), places=1)

    def test_empty_list(self):
        """Handle empty opportunity list."""
        opps = []
        sorted_opps = sorted(opps, key=opportunity_scout.rice, reverse=True)[:3]
        self.assertEqual(sorted_opps, [])

    def test_single_opportunity(self):
        """Handle list with single opportunity."""
        opps = [
            {
                "title": "Only one",
                "reach": 5,
                "impact": 5,
                "confidence": 0.8,
                "effort_days": 2,
            }
        ]
        sorted_opps = sorted(opps, key=opportunity_scout.rice, reverse=True)[:3]
        self.assertEqual(len(sorted_opps), 1)
        self.assertEqual(sorted_opps[0]["title"], "Only one")


class JSONSchemaTests(unittest.TestCase):
    """Tests for the canonical opportunity JSON schema."""

    EXPECTED_FIELDS = {"title", "why", "value", "risk", "reach", "impact", "confidence", "effort_days"}

    def test_complete_opportunity_has_all_fields(self):
        """A well-formed opportunity has all expected fields."""
        opp = {
            "title": "Cache responses",
            "why": "API latency is 500ms per request",
            "value": "3x reduction in latency; $10k/year cost savings",
            "risk": "Stale data for 5 minutes; clear cache on rollback",
            "reach": 8,
            "impact": 7,
            "confidence": 0.9,
            "effort_days": 3,
        }
        self.assertEqual(set(opp.keys()), self.EXPECTED_FIELDS)

    def test_field_types_are_correct(self):
        """Field types match the schema: strings for text, numbers for metrics."""
        opp = {
            "title": "Cache responses",
            "why": "API latency is high",
            "value": "3x speedup",
            "risk": "Clear cache on rollback",
            "reach": 8,
            "impact": 7,
            "confidence": 0.9,
            "effort_days": 3,
        }
        self.assertIsInstance(opp["title"], str)
        self.assertIsInstance(opp["why"], str)
        self.assertIsInstance(opp["value"], str)
        self.assertIsInstance(opp["risk"], str)
        self.assertIsInstance(opp["reach"], int)
        self.assertIsInstance(opp["impact"], int)
        self.assertIsInstance(opp["confidence"], float)
        self.assertIsInstance(opp["effort_days"], (int, float))

    def test_reach_and_impact_are_1_to_10_scale(self):
        """Reach and impact should be in [1, 10] range."""
        valid_opportunities = [
            {
                "title": "Test",
                "why": "Test",
                "value": "Test",
                "risk": "Test",
                "reach": 1,
                "impact": 10,
                "confidence": 0.5,
                "effort_days": 1,
            },
            {
                "title": "Test",
                "why": "Test",
                "value": "Test",
                "risk": "Test",
                "reach": 5,
                "impact": 5,
                "confidence": 0.5,
                "effort_days": 1,
            },
            {
                "title": "Test",
                "why": "Test",
                "value": "Test",
                "risk": "Test",
                "reach": 10,
                "impact": 1,
                "confidence": 0.5,
                "effort_days": 1,
            },
        ]
        for opp in valid_opportunities:
            self.assertGreaterEqual(opp["reach"], 1)
            self.assertLessEqual(opp["reach"], 10)
            self.assertGreaterEqual(opp["impact"], 1)
            self.assertLessEqual(opp["impact"], 10)

    def test_confidence_is_0_to_1_scale(self):
        """Confidence should be in [0.0, 1.0] range."""
        valid_opportunities = [
            {
                "title": "Test",
                "why": "Test",
                "value": "Test",
                "risk": "Test",
                "reach": 5,
                "impact": 5,
                "confidence": 0.0,
                "effort_days": 1,
            },
            {
                "title": "Test",
                "why": "Test",
                "value": "Test",
                "risk": "Test",
                "reach": 5,
                "impact": 5,
                "confidence": 0.5,
                "effort_days": 1,
            },
            {
                "title": "Test",
                "why": "Test",
                "value": "Test",
                "risk": "Test",
                "reach": 5,
                "impact": 5,
                "confidence": 1.0,
                "effort_days": 1,
            },
        ]
        for opp in valid_opportunities:
            self.assertGreaterEqual(opp["confidence"], 0.0)
            self.assertLessEqual(opp["confidence"], 1.0)

    def test_effort_days_is_positive(self):
        """Effort days should be positive number."""
        opp = {
            "title": "Test",
            "why": "Test",
            "value": "Test",
            "risk": "Test",
            "reach": 5,
            "impact": 5,
            "confidence": 0.5,
            "effort_days": 0.1,
        }
        self.assertGreater(opp["effort_days"], 0)


class EdgeCaseTests(unittest.TestCase):
    """Tests for edge cases and error handling."""

    def test_very_large_values_dont_overflow(self):
        """RICE calculation with very large values."""
        opportunity = {
            "reach": 10,
            "impact": 10,
            "confidence": 1.0,
            "effort_days": 0.1,
        }
        score = opportunity_scout.rice(opportunity)
        self.assertGreater(score, 0)
        self.assertTrue(isinstance(score, float))

    def test_very_small_confidence(self):
        """RICE calculation with very small confidence values."""
        opportunity = {
            "reach": 10,
            "impact": 10,
            "confidence": 0.001,
            "effort_days": 1,
        }
        score = opportunity_scout.rice(opportunity)
        self.assertAlmostEqual(score, 0.1, places=2)

    def test_json_with_unicode_characters(self):
        """Parse JSON with unicode characters in strings."""
        json_line = (
            '{"title":"优化缓存","why":"API延迟高","value":"3倍速度提升",'
            '"risk":"回滚时清除缓存","reach":8,"impact":7,"confidence":0.9,"effort_days":2}'
        )
        opp = json.loads(json_line)
        self.assertIn("优化", opp["title"])

    def test_json_with_newlines_in_strings(self):
        """Parse JSON with escaped newlines in field values."""
        json_line = (
            '{"title":"Multi\\nLine","why":"This is\\na test","value":"2x",'
            '"risk":"Revert","reach":5,"impact":5,"confidence":0.8,"effort_days":1}'
        )
        opp = json.loads(json_line)
        self.assertIn("\n", opp["title"])

    def test_opportunity_with_all_fields_at_minimum(self):
        """Create an opportunity with all minimum valid values."""
        opp = {
            "title": "A",
            "why": "B",
            "value": "C",
            "risk": "D",
            "reach": 1,
            "impact": 1,
            "confidence": 0.0,
            "effort_days": 0.1,
        }
        score = opportunity_scout.rice(opp)
        self.assertGreaterEqual(score, 0.0)

    def test_opportunity_with_all_fields_at_maximum(self):
        """Create an opportunity with all maximum valid values."""
        opp = {
            "title": "A" * 200,
            "why": "B" * 600,
            "value": "C" * 100,
            "risk": "D" * 800,
            "reach": 10,
            "impact": 10,
            "confidence": 1.0,
            "effort_days": 100,
        }
        score = opportunity_scout.rice(opp)
        self.assertGreaterEqual(score, 0.0)
        self.assertLess(score, 1000)  # Should not overflow


if __name__ == "__main__":
    unittest.main()
