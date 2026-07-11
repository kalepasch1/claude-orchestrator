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


if __name__ == "__main__":
    unittest.main()
