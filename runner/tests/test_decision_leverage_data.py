#!/usr/bin/env python3
"""
test_decision_leverage_data.py - unit tests for decision_leverage_data.py

Tests all public functions with mocked db calls to verify:
  - gather() assembles all leverage sections and caches results
  - historical_precedents() queries and formats past decisions
  - related_outcomes() computes merge rate and velocity
  - cost_context() tries the view first, falls back to outcomes
  - timing_leverage() computes urgency from pending duration and blocked tasks
  - enrich_brief() merges leverage into a decision brief
  - stats() tracks calls accurately

Run: cd runner && python3 -m pytest tests/test_decision_leverage_data.py -v
"""
import os, sys, json, time, unittest, datetime
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import decision_leverage_data as dld


class TestHistoricalPrecedents(unittest.TestCase):
    """Tests for historical_precedents()."""

    @patch.object(dld.db, "select")
    def test_returns_formatted_precedents(self, mock_select):
        """Precedents are extracted and trimmed from approval rows."""
        mock_select.return_value = [
            {"id": "a1", "title": "Vendor contract renewal", "status": "approved",
             "decision_type": "approve", "decision_text": "Approved with conditions",
             "decided_at": "2026-06-01T10:00:00Z", "project": "ACME"},
            {"id": "a2", "title": "License upgrade", "status": "denied",
             "decision_type": "deny", "decision_text": "Too expensive",
             "decided_at": "2026-05-15T08:00:00Z", "project": "ACME"},
        ]
        result = dld.historical_precedents("ACME", "legal")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["id"], "a1")
        self.assertEqual(result[0]["status"], "approved")
        self.assertEqual(result[1]["status"], "denied")
        # Verify the query filtered by project and kind
        call_args = mock_select.call_args
        self.assertEqual(call_args[0][0], "approvals")
        self.assertIn("kind", call_args[0][1])

    @patch.object(dld.db, "select")
    def test_empty_on_no_results(self, mock_select):
        mock_select.return_value = []
        result = dld.historical_precedents("NONE", "")
        self.assertEqual(result, [])

    @patch.object(dld.db, "select", side_effect=Exception("db down"))
    def test_fail_soft_on_db_error(self, mock_select):
        result = dld.historical_precedents("X", "legal")
        self.assertEqual(result, [])


class TestRelatedOutcomes(unittest.TestCase):
    """Tests for related_outcomes()."""

    @patch.object(dld.db, "select")
    def test_computes_merge_rate(self, mock_select):
        mock_select.return_value = [
            {"id": "o1", "task_id": "t1", "verdict": "merged", "created_at": "2026-07-10", "elapsed_s": 120, "usd": 0.05},
            {"id": "o2", "task_id": "t2", "verdict": "merged", "created_at": "2026-07-09", "elapsed_s": 200, "usd": 0.08},
            {"id": "o3", "task_id": "t3", "verdict": "failed", "created_at": "2026-07-08", "elapsed_s": 60, "usd": 0.02},
        ]
        result = dld.related_outcomes("ACME")
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["merged"], 2)
        self.assertEqual(result["failed"], 1)
        self.assertAlmostEqual(result["merge_rate"], 66.7, places=1)
        self.assertAlmostEqual(result["avg_duration_s"], 126.7, places=1)

    @patch.object(dld.db, "select")
    def test_empty_project(self, mock_select):
        mock_select.return_value = []
        result = dld.related_outcomes("")
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["merge_rate"], 0)


class TestCostContext(unittest.TestCase):
    """Tests for cost_context()."""

    @patch.object(dld.db, "select")
    def test_uses_view_when_available(self, mock_select):
        """When the spend view returns data, use it."""
        mock_select.return_value = [
            {"provider": "anthropic", "total_usd": 12.50, "task_count": 100},
            {"provider": "deepseek", "total_usd": 3.20, "task_count": 40},
        ]
        result = dld.cost_context("ACME")
        self.assertEqual(result["source"], dld.COST_VIEW)
        self.assertAlmostEqual(result["total_usd"], 15.70, places=2)
        self.assertEqual(result["by_provider"]["anthropic"], 12.50)
        self.assertEqual(result["task_count"], 140)

    @patch.object(dld.db, "select")
    def test_falls_back_to_outcomes(self, mock_select):
        """When view returns empty, fall back to outcomes table."""
        def side_effect(table, params):
            if table == dld.COST_VIEW:
                return []
            return [
                {"usd": 0.10, "task_id": "t1"},
                {"usd": 0.20, "task_id": "t2"},
            ]
        mock_select.side_effect = side_effect
        result = dld.cost_context("ACME")
        self.assertEqual(result["source"], "outcomes")
        self.assertAlmostEqual(result["total_usd"], 0.30, places=2)
        self.assertEqual(result["task_count"], 2)


class TestTimingLeverage(unittest.TestCase):
    """Tests for timing_leverage()."""

    @patch.object(dld.db, "select")
    def test_low_urgency(self, mock_select):
        """A recently created approval with no blocked tasks = low urgency."""
        mock_select.return_value = []
        now = datetime.datetime.utcnow()
        approval = {"id": "a1", "created_at": (now - datetime.timedelta(hours=2)).isoformat()}
        result = dld.timing_leverage(approval)
        self.assertEqual(result["urgency"], "low")
        self.assertAlmostEqual(result["pending_hours"], 2.0, delta=0.2)

    @patch.object(dld.db, "select")
    def test_high_urgency_long_pending(self, mock_select):
        """Pending > 72h = high urgency."""
        mock_select.return_value = []
        now = datetime.datetime.utcnow()
        approval = {"id": "a1", "created_at": (now - datetime.timedelta(hours=80)).isoformat()}
        result = dld.timing_leverage(approval)
        self.assertEqual(result["urgency"], "high")

    @patch.object(dld.db, "select")
    def test_medium_urgency_with_blocked_tasks(self, mock_select):
        """Blocked tasks push urgency to medium."""
        mock_select.return_value = [{"id": "t1"}]  # 1 blocked task (contains approval id)
        now = datetime.datetime.utcnow()
        approval = {"id": "t1", "created_at": (now - datetime.timedelta(hours=5)).isoformat()}
        result = dld.timing_leverage(approval)
        self.assertEqual(result["urgency"], "medium")

    def test_missing_created_at(self):
        """Handles missing created_at gracefully."""
        with patch.object(dld.db, "select", return_value=[]):
            result = dld.timing_leverage({"id": "a1"})
        self.assertEqual(result["pending_hours"], 0)
        self.assertEqual(result["urgency"], "low")


class TestGather(unittest.TestCase):
    """Tests for gather() — the main entry point."""

    def setUp(self):
        dld._cache.clear()
        dld._stats.update({"gather_calls": 0, "enrichments": 0, "cache_hits": 0, "errors": 0})

    @patch.object(dld.db, "select")
    def test_assembles_all_sections(self, mock_select):
        mock_select.return_value = [{"id": "a1", "project": "ACME", "kind": "legal",
                                      "created_at": datetime.datetime.utcnow().isoformat()}]
        result = dld.gather("a1")
        self.assertIn("historical_precedents", result)
        self.assertIn("related_outcomes", result)
        self.assertIn("cost_context", result)
        self.assertIn("timing_leverage", result)
        self.assertIn("alternatives", result)
        self.assertEqual(dld._stats["gather_calls"], 1)

    @patch.object(dld.db, "select")
    def test_cache_hit(self, mock_select):
        """Second call within TTL returns cached data."""
        mock_select.return_value = [{"id": "a1", "project": "X", "kind": "legal",
                                      "created_at": datetime.datetime.utcnow().isoformat()}]
        dld.gather("a1")
        dld.gather("a1")
        self.assertEqual(dld._stats["cache_hits"], 1)
        self.assertEqual(dld._stats["gather_calls"], 2)

    @patch.object(dld.db, "select")
    def test_cache_expired(self, mock_select):
        """Expired cache entries are refreshed."""
        mock_select.return_value = [{"id": "a1", "project": "X", "kind": "legal",
                                      "created_at": datetime.datetime.utcnow().isoformat()}]
        dld.gather("a1")
        # Expire the cache
        dld._cache["a1"] = (time.time() - dld.CACHE_TTL - 1, dld._cache["a1"][1])
        dld.gather("a1")
        self.assertEqual(dld._stats["cache_hits"], 0)  # no cache hit on second call


class TestEnrichBrief(unittest.TestCase):
    """Tests for enrich_brief()."""

    def setUp(self):
        dld._stats.update({"gather_calls": 0, "enrichments": 0, "cache_hits": 0, "errors": 0})

    def test_enriches_negotiation_section(self):
        brief = {
            "decision": "Renew vendor contract",
            "negotiation": {"leverage": "Multi-year discount", "batna": "Switch vendors", "counter": ""},
            "recommendation": "Negotiate harder",
        }
        leverage = {
            "historical_precedents": [
                {"id": "a1", "title": "Prior renewal", "status": "approved", "decision_type": "conditions"},
            ],
            "related_outcomes": {"total": 50, "merged": 45, "merge_rate": 90.0, "avg_duration_s": 100},
            "cost_context": {"total_usd": 25.50, "task_count": 200},
            "timing_leverage": {"pending_hours": 48, "urgency": "medium",
                                "timing_advantage": "Moderate pressure", "blocked_tasks": 1},
            "alternatives": [{"decision_type": "negotiate", "example_title": "Old deal"}],
        }
        result = dld.enrich_brief(brief, leverage)
        # Original not mutated
        self.assertNotIn("project_health", brief)
        # Enriched has timing in leverage
        self.assertIn("Moderate pressure", result["negotiation"]["leverage"])
        # Cost in BATNA
        self.assertIn("$25.50", result["negotiation"]["batna"])
        # Precedent in counter
        self.assertIn("Prior renewal", result["negotiation"]["counter"])
        # Project health added
        self.assertEqual(result["project_health"]["merge_rate"], "90.0%")
        # Alternatives added
        self.assertEqual(len(result["alternative_approaches"]), 1)
        # Stats updated
        self.assertEqual(dld._stats["enrichments"], 1)

    def test_handles_empty_brief(self):
        """Enrich works on a minimal/empty brief without crashing."""
        result = dld.enrich_brief({}, {"timing_leverage": {}, "historical_precedents": [],
                                        "cost_context": {}, "related_outcomes": {}, "alternatives": []})
        self.assertIn("negotiation", result)
        self.assertEqual(dld._stats["enrichments"], 1)


class TestStats(unittest.TestCase):
    """Tests for stats()."""

    def test_returns_copy(self):
        s = dld.stats()
        s["gather_calls"] = 9999
        self.assertNotEqual(dld._stats["gather_calls"], 9999)


if __name__ == "__main__":
    unittest.main()
