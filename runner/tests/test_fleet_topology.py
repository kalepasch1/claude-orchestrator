"""Tests for fleet_topology — fleet topology awareness and hardware profiling."""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Stub db before importing the module
fake_db = MagicMock()
with patch.dict(sys.modules, {"db": fake_db}):
    import fleet_topology


class TestProfile(unittest.TestCase):
    def test_profile_returns_dict(self):
        result = fleet_topology.profile()
        self.assertIsInstance(result, dict)
        for key in ("ram_gb", "cpu_count", "tools"):
            self.assertIn(key, result)

    def test_profile_has_tools(self):
        result = fleet_topology.profile()
        self.assertIsInstance(result["tools"], list)


class TestCanHandle(unittest.TestCase):
    def test_can_handle_default_true(self):
        result = fleet_topology.can_handle({})
        self.assertTrue(result)


class TestFleetTopologyStats(unittest.TestCase):
    def test_stats_returns_dict(self):
        # stats is aliased to topology_stats at module level
        result = fleet_topology.stats()
        self.assertIsInstance(result, dict)
        self.assertIn("enabled", result)


class TestDetectCoworkTerminals(unittest.TestCase):
    """Tests for _detect_cowork_terminals DB-based detection."""

    def test_returns_count_from_db(self):
        fake_db.query = MagicMock(return_value=[{"n": 3}])
        result = fleet_topology._detect_cowork_terminals()
        self.assertEqual(result, 3)
        fake_db.query.assert_called_once()

    def test_returns_zero_on_empty_result(self):
        fake_db.query = MagicMock(return_value=[])
        result = fleet_topology._detect_cowork_terminals()
        self.assertEqual(result, 0)

    def test_returns_zero_on_db_error(self):
        fake_db.query = MagicMock(side_effect=Exception("connection lost"))
        result = fleet_topology._detect_cowork_terminals()
        self.assertEqual(result, 0)

    def test_returns_zero_on_none_result(self):
        fake_db.query = MagicMock(return_value=None)
        result = fleet_topology._detect_cowork_terminals()
        self.assertEqual(result, 0)


class TestRecommendTopology(unittest.TestCase):
    """Basic smoke test for recommend_topology output shape."""

    def test_returns_list(self):
        topo = fleet_topology.FleetTopology()
        recs = topo.recommend_topology(target_tasks_hour=10)
        self.assertIsInstance(recs, list)

    def test_recommendations_have_action_key(self):
        topo = fleet_topology.FleetTopology()
        recs = topo.recommend_topology(target_tasks_hour=10)
        for rec in recs:
            self.assertIn("action", rec)


if __name__ == "__main__":
    unittest.main()
