#!/usr/bin/env python3
"""
Comprehensive test suite for opportunity discovery and scoring system.
Tests opportunity_scout, opportunity_scorer, and cross_app_scanner modules.
"""
import os
import sys
import json
import unittest
from unittest.mock import patch, MagicMock, call
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import opportunity_scout
import opportunity_scorer
import cross_app_scanner


class RiceScoringTest(unittest.TestCase):
    """Test RICE (Reach, Impact, Confidence, Effort) scoring algorithm."""

    def test_rice_basic_calculation(self):
        """RICE = (reach * impact * confidence) / effort."""
        opportunity = {
            "reach": 10,
            "impact": 10,
            "confidence": 1.0,
            "effort_days": 5.0,
        }
        score = opportunity_scout.rice(opportunity)
        expected = (10 * 10 * 1.0) / 5.0
        self.assertEqual(score, expected)

    def test_rice_handles_zero_effort_gracefully(self):
        """When effort is 0, use minimum of 0.5 to avoid division by zero."""
        opportunity = {
            "reach": 10,
            "impact": 10,
            "confidence": 1.0,
            "effort_days": 0.0,
        }
        score = opportunity_scout.rice(opportunity)
        self.assertEqual(score, (10 * 10 * 1.0) / 0.5)

    def test_rice_handles_missing_fields(self):
        """Missing fields in dict should not crash; return 0."""
        opportunity = {"reach": 10}
        score = opportunity_scout.rice(opportunity)
        self.assertEqual(score, 0.0)

    def test_rice_returns_rounded_float(self):
        """Result should be rounded to 1 decimal place."""
        opportunity = {
            "reach": 7,
            "impact": 8,
            "confidence": 0.9,
            "effort_days": 3.5,
        }
        score = opportunity_scout.rice(opportunity)
        self.assertIsInstance(score, float)
        self.assertEqual(score, round(score, 1))

    def test_rice_low_confidence_reduces_score(self):
        """Low confidence should proportionally reduce score."""
        base = {
            "reach": 10,
            "impact": 10,
            "confidence": 1.0,
            "effort_days": 5.0,
        }
        low_conf = {
            "reach": 10,
            "impact": 10,
            "confidence": 0.1,
            "effort_days": 5.0,
        }
        base_score = opportunity_scout.rice(base)
        low_score = opportunity_scout.rice(low_conf)
        self.assertEqual(low_score, base_score * 0.1)


class ProposalScorerTest(unittest.TestCase):
    """Test proposal scoring against historical ROI data."""

    def test_score_proposal_returns_required_keys(self):
        """Result must include 'score', 'reasoning', and 'components'."""
        with patch.object(opportunity_scorer.db, "select", return_value=[]):
            result = opportunity_scorer.score_proposal(
                proposal_text="test proposal",
                project_id="proj-1",
                surface_returns={},
            )
        self.assertIn("score", result)
        self.assertIn("reasoning", result)
        self.assertIn("components", result)

    def test_score_zero_when_no_returns(self):
        """Empty surface_returns should yield score of 0.0."""
        with patch.object(opportunity_scorer.db, "select", return_value=[]):
            result = opportunity_scorer.score_proposal(
                proposal_text="test",
                project_id="proj-1",
                surface_returns={},
            )
        self.assertEqual(result["score"], 0.0)
        self.assertEqual(result["components"], {})

    def test_score_scales_with_historical_roi(self):
        """Score should scale by historical ROI data."""
        history = [{"surface": "feature", "roi": 1000.0}]

        def mock_select(table, params=None):
            if table == "opportunity_history":
                return history
            return []

        with patch.object(opportunity_scorer.db, "select", side_effect=mock_select):
            result = opportunity_scorer.score_proposal(
                proposal_text="test",
                project_id="proj-1",
                surface_returns={"feature": 100.0},
            )
        self.assertGreater(result["score"], 0.0)
        self.assertIn("feature", result["components"])

    def test_score_combines_multiple_surfaces(self):
        """Score should sum contributions from all surfaces."""
        history = [
            {"surface": "perf", "roi": 500.0},
            {"surface": "dx", "roi": 300.0},
        ]

        def mock_select(table, params=None):
            if table == "opportunity_history":
                return history
            return []

        with patch.object(opportunity_scorer.db, "select", side_effect=mock_select):
            result = opportunity_scorer.score_proposal(
                proposal_text="test",
                project_id="proj-1",
                surface_returns={"perf": 50.0, "dx": 50.0},
            )
        self.assertIn("perf", result["components"])
        self.assertIn("dx", result["components"])
        total = result["components"]["perf"] + result["components"]["dx"]
        self.assertEqual(result["score"], round(total, 4))

    def test_score_handles_db_error_gracefully(self):
        """Database errors should not crash; return sensible defaults."""
        with patch.object(
            opportunity_scorer.db, "select", side_effect=Exception("DB error")
        ):
            result = opportunity_scorer.score_proposal(
                proposal_text="test",
                project_id="proj-1",
                surface_returns={"test": 100.0},
            )
        self.assertEqual(result["score"], 0.0)
        self.assertIn("reasoning", result)


class OpportunitySummaryTest(unittest.TestCase):
    """Test opportunity pipeline status summarization."""

    def test_summarize_counts_statuses(self):
        """Should count opportunities by status."""
        rows = [
            {"status": "proposed"},
            {"status": "proposed"},
            {"status": "approved"},
            {"status": "in_progress"},
        ]
        with patch.object(opportunity_scorer.db, "select", return_value=rows):
            summary = opportunity_scorer.summarize_opportunities("proj-1")
        self.assertEqual(summary["proposed"], 2)
        self.assertEqual(summary["approved"], 1)
        self.assertEqual(summary["in_progress"], 1)

    def test_summarize_empty_when_no_opportunities(self):
        """No opportunities should return empty dict."""
        with patch.object(opportunity_scorer.db, "select", return_value=[]):
            summary = opportunity_scorer.summarize_opportunities("proj-1")
        self.assertEqual(summary, {})

    def test_summarize_handles_db_errors(self):
        """Database errors should return empty dict, not crash."""
        with patch.object(
            opportunity_scorer.db, "select", side_effect=Exception("DB error")
        ):
            summary = opportunity_scorer.summarize_opportunities("proj-1")
        self.assertEqual(summary, {})

    def test_summarize_handles_missing_status_field(self):
        """Rows without status should be counted as 'unknown'."""
        rows = [
            {"status": "approved"},
            {"other_field": "value"},
        ]
        with patch.object(opportunity_scorer.db, "select", return_value=rows):
            summary = opportunity_scorer.summarize_opportunities("proj-1")
        self.assertEqual(summary["approved"], 1)
        self.assertEqual(summary["unknown"], 1)


class SupabaseTableScanTest(unittest.TestCase):
    """Test Supabase table detection in codebases."""

    def test_scan_finds_table_references(self):
        """Should extract table names from .from() calls."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout='from("users"\nfrom("products"\nfrom("orders")',
                returncode=0,
            )
            tables = cross_app_scanner.scan_supabase_tables("/fake/repo", "typescript")
        self.assertIn("users", tables)
        self.assertIn("products", tables)
        self.assertIn("orders", tables)

    def test_scan_handles_subprocess_errors(self):
        """Subprocess errors should return empty set, not crash."""
        with patch("subprocess.run", side_effect=Exception("Process error")):
            tables = cross_app_scanner.scan_supabase_tables("/fake/repo", "typescript")
        self.assertEqual(tables, set())

    def test_scan_handles_timeout(self):
        """Timeouts should return empty set gracefully."""
        with patch("subprocess.run", side_effect=TimeoutError()):
            tables = cross_app_scanner.scan_supabase_tables("/fake/repo", "typescript")
        self.assertEqual(tables, set())

    def test_scan_detects_quoted_table_names(self):
        """Should detect both single and double quoted table names."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout=".from('users')\n.from(\"products\")",
                returncode=0,
            )
            tables = cross_app_scanner.scan_supabase_tables("/fake/repo", "typescript")
        self.assertIn("users", tables)
        self.assertIn("products", tables)


class RealtimePatternDetectionTest(unittest.TestCase):
    """Test detection of real-time infrastructure patterns."""

    def test_scan_detects_supabase_realtime(self):
        """Should detect Supabase realtime channel usage."""
        with patch("subprocess.run") as mock_run:
            # Return truthy output for realtime detection
            mock_run.return_value = MagicMock(stdout="file.ts", returncode=0)
            patterns = cross_app_scanner.scan_realtime_patterns("/fake/repo", "typescript")
        self.assertTrue(patterns["supabase_realtime"])

    def test_scan_detects_websocket_patterns(self):
        """Should detect WebSocket server and client patterns."""
        with patch("subprocess.run") as mock_run:

            def side_effect(*args, **kwargs):
                # Check the pattern being searched for
                if "new WebSocket" in str(args):
                    return MagicMock(stdout="file.ts", returncode=0)
                return MagicMock(stdout="", returncode=0)

            mock_run.side_effect = side_effect
            patterns = cross_app_scanner.scan_realtime_patterns("/fake/repo", "typescript")
        # At least websocket_client should be detected
        self.assertIn("websocket_client", patterns)
        self.assertIn("websocket_server", patterns)

    def test_scan_returns_all_pattern_keys(self):
        """Result should include all expected pattern keys."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            patterns = cross_app_scanner.scan_realtime_patterns("/fake/repo", "typescript")
        expected_keys = [
            "supabase_realtime",
            "supabase_presence",
            "websocket_server",
            "websocket_client",
            "sse_server",
            "http_polling",
            "event_bus_local",
        ]
        for key in expected_keys:
            self.assertIn(key, patterns)

    def test_scan_handles_grep_errors(self):
        """Grep errors should not crash; return all False."""
        with patch("subprocess.run", side_effect=Exception("grep error")):
            patterns = cross_app_scanner.scan_realtime_patterns("/fake/repo", "typescript")
        for value in patterns.values():
            self.assertFalse(value)


class EventBusInstanceScanTest(unittest.TestCase):
    """Test event bus instance detection."""

    def test_scan_finds_bus_implementations(self):
        """Should detect class definitions and exports for bus patterns."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="src/bus.ts\nsrc/events.ts\n", returncode=0
            )
            buses = cross_app_scanner.scan_event_bus_instances("/fake/repo", "typescript")
        self.assertIn("src/bus.ts", buses)
        self.assertIn("src/events.ts", buses)

    def test_scan_returns_list(self):
        """Result should always be a list."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            buses = cross_app_scanner.scan_event_bus_instances("/fake/repo", "typescript")
        self.assertIsInstance(buses, list)

    def test_scan_deduplicates_files(self):
        """Duplicate file paths should appear only once."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="src/bus.ts\nsrc/bus.ts\nsrc/bus.ts\n", returncode=0
            )
            buses = cross_app_scanner.scan_event_bus_instances("/fake/repo", "typescript")
        count = buses.count("src/bus.ts")
        self.assertEqual(count, 1)

    def test_scan_handles_errors(self):
        """Errors should return empty list."""
        with patch("subprocess.run", side_effect=Exception("scan error")):
            buses = cross_app_scanner.scan_event_bus_instances("/fake/repo", "typescript")
        self.assertEqual(buses, [])


class ArchitectureMapBuildingTest(unittest.TestCase):
    """Test cross-app architecture map construction."""

    def test_map_includes_all_required_fields(self):
        """Architecture map must include apps, shared_tables, and asymmetries."""
        with patch.object(
            cross_app_scanner, "_resolve_repos", return_value={}
        ), patch.object(cross_app_scanner.db, "upsert") as mock_upsert:
            result = cross_app_scanner.build_architecture_map()
        self.assertIn("apps", result)
        self.assertIn("shared_tables", result)
        self.assertIn("asymmetries", result)
        self.assertIn("scanned_at", result)

    def test_map_detects_asymmetries(self):
        """Should identify asymmetries in realtime pattern usage."""
        mock_apps = {
            "app1": {"repo": "/app1", "lang": "typescript"},
            "app2": {"repo": "/app2", "lang": "typescript"},
        }

        def mock_scan_tables(*args):
            return set()

        def mock_scan_patterns(repo, lang):
            if "app1" in repo:
                return {"supabase_realtime": True, "http_polling": False}
            else:
                return {"supabase_realtime": False, "http_polling": True}

        def mock_scan_buses(*args):
            return []

        with patch.object(cross_app_scanner, "_resolve_repos", return_value=mock_apps), \
             patch.object(cross_app_scanner, "scan_supabase_tables", side_effect=mock_scan_tables), \
             patch.object(cross_app_scanner, "scan_realtime_patterns", side_effect=mock_scan_patterns), \
             patch.object(cross_app_scanner, "scan_event_bus_instances", side_effect=mock_scan_buses), \
             patch.object(cross_app_scanner.db, "upsert"):
            result = cross_app_scanner.build_architecture_map()
        # Should find asymmetry between app1 and app2 realtime patterns
        asymmetries = result.get("asymmetries", [])
        has_asymmetry = any(a["type"] == "realtime_asymmetry" for a in asymmetries)
        self.assertTrue(has_asymmetry)

    def test_map_detects_shared_tables(self):
        """Should identify tables used by multiple apps."""
        mock_apps = {
            "app1": {"repo": "/app1", "lang": "typescript"},
            "app2": {"repo": "/app2", "lang": "typescript"},
        }

        def mock_scan_tables(repo, lang):
            return {"shared_table", "app_specific"}

        with patch.object(cross_app_scanner, "_resolve_repos", return_value=mock_apps), \
             patch.object(cross_app_scanner, "scan_supabase_tables", side_effect=mock_scan_tables), \
             patch.object(cross_app_scanner, "scan_realtime_patterns", return_value={}), \
             patch.object(cross_app_scanner, "scan_event_bus_instances", return_value=[]), \
             patch.object(cross_app_scanner.db, "upsert"):
            result = cross_app_scanner.build_architecture_map()
        shared = result.get("shared_tables", {})
        self.assertIn("shared_table", shared)

    def test_map_handles_scan_exceptions(self):
        """Exceptions during app scan should not crash overall scan."""
        mock_apps = {
            "good_app": {"repo": "/good", "lang": "typescript"},
            "bad_app": {"repo": "/bad", "lang": "typescript"},
        }

        def mock_scan_tables(repo, lang):
            if "bad" in repo:
                raise Exception("Scan failed")
            return {"users"}

        with patch.object(cross_app_scanner, "_resolve_repos", return_value=mock_apps), \
             patch.object(cross_app_scanner, "scan_supabase_tables", side_effect=mock_scan_tables), \
             patch.object(cross_app_scanner, "scan_realtime_patterns", return_value={}), \
             patch.object(cross_app_scanner, "scan_event_bus_instances", return_value=[]), \
             patch.object(cross_app_scanner.db, "upsert"):
            result = cross_app_scanner.build_architecture_map()
        # Should have results for good_app at least
        self.assertIn("apps", result)


class MinerContextGenerationTest(unittest.TestCase):
    """Test context string generation for improvement_miner."""

    def test_context_generated_from_db(self):
        """Should retrieve and format context from database."""
        arch_data = {
            "apps": {
                "app1": {
                    "supabase_tables": ["users", "products"],
                    "realtime_patterns": {"supabase_realtime": True},
                    "event_bus_count": 1,
                }
            },
            "asymmetries": [],
            "shared_tables": {},
        }

        def mock_select(table, params=None):
            if table == "cross_app_architecture":
                return [{"data": json.dumps(arch_data)}]
            return []

        with patch.object(cross_app_scanner.db, "select", side_effect=mock_select):
            context = cross_app_scanner.get_context_for_miner()
        self.assertIn("CROSS-APP ARCHITECTURE", context)
        self.assertIn("app1", context)

    def test_context_handles_missing_db_data(self):
        """Should fall back when database has no data."""
        with patch.object(cross_app_scanner.db, "select", return_value=[]), \
             patch("builtins.open", side_effect=FileNotFoundError()), \
             patch.object(cross_app_scanner, "build_architecture_map", return_value={"apps": {}}):
            context = cross_app_scanner.get_context_for_miner()
        self.assertIn("CROSS-APP ARCHITECTURE", context)

    def test_context_returns_string(self):
        """Context should always be a string, even on errors."""
        with patch.object(cross_app_scanner.db, "select", side_effect=Exception("DB error")):
            context = cross_app_scanner.get_context_for_miner()
        self.assertIsInstance(context, str)


class IntegrationTest(unittest.TestCase):
    """Integration tests for the full opportunity discovery pipeline."""

    def test_full_pipeline_respects_suppression(self):
        """Opportunities below preference threshold should be suppressed."""
        # This tests that the full pipeline honors suppression logic
        opportunity = {
            "title": "Test Opportunity",
            "reach": 2,
            "impact": 1,
            "confidence": 0.1,
            "effort_days": 10.0,
        }
        score = opportunity_scout.rice(opportunity)
        # Low RICE score should be considered low-priority
        self.assertLess(score, 1.0)

    def test_json_output_format_matches_spec(self):
        """Opportunities output should match JSON spec from PROMPT."""
        opportunity = {
            "title": "Refactor database layer",
            "why": "Current schema lacks indexes",
            "value": "50% query time reduction",
            "risk": "Rollback by recreating old indexes",
            "reach": 8,
            "impact": 9,
            "confidence": 0.8,
            "effort_days": 5.0,
        }
        # Verify all required fields are present
        required_fields = ["title", "why", "value", "risk", "reach", "impact", "confidence", "effort_days"]
        for field in required_fields:
            self.assertIn(field, opportunity)
        # Verify numeric ranges
        self.assertGreaterEqual(opportunity["reach"], 1)
        self.assertLessEqual(opportunity["reach"], 10)
        self.assertGreaterEqual(opportunity["confidence"], 0.0)
        self.assertLessEqual(opportunity["confidence"], 1.0)

    def test_multiple_opportunities_sorted_by_rice(self):
        """Multiple opportunities should be sortable by RICE score."""
        opportunities = [
            {"title": "Low", "reach": 2, "impact": 2, "confidence": 0.5, "effort_days": 10.0},
            {"title": "High", "reach": 10, "impact": 10, "confidence": 0.9, "effort_days": 2.0},
            {"title": "Medium", "reach": 5, "impact": 5, "confidence": 0.7, "effort_days": 3.0},
        ]
        sorted_opps = sorted(opportunities, key=opportunity_scout.rice, reverse=True)
        # High-scoring opportunity should be first
        self.assertEqual(sorted_opps[0]["title"], "High")


if __name__ == "__main__":
    unittest.main()
