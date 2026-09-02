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
    """The shape `recommend_topology` returns, as its caller actually reads it.

    These two tests asserted a bare list and had been failing for long enough
    that the red was ambient. The implementation returns a dict, and so does
    the contract its only production caller relies on —
    `sub_recommend_tick.tick()` does `reco.get("recommendations", [])[:3]` and
    then reads `r["action"]` off each entry. Code and caller agree; the test
    was the outlier, so the test is what moves.

    Pinned here as the caller reads it, so a change that breaks
    sub_recommend_tick fails here first.
    """

    def _topo(self):
        return fleet_topology.FleetTopology().recommend_topology(
            target_tasks_hour=10)

    def test_returns_a_mapping(self):
        self.assertIsInstance(self._topo(), dict)

    def test_carries_the_keys_the_caller_reads(self):
        topo = self._topo()
        for key in ("current", "target_tasks_hour", "gap", "recommendations"):
            self.assertIn(key, topo)

    def test_recommendations_is_a_list(self):
        self.assertIsInstance(self._topo()["recommendations"], list)

    def test_every_recommendation_has_an_action(self):
        # sub_recommend_tick indexes r["action"] directly — a missing key is a
        # KeyError in a scheduled job, where nobody is watching.
        for rec in self._topo()["recommendations"]:
            self.assertIn("action", rec)

    def test_every_recommendation_has_a_rationale(self):
        # Read as r.get("rationale", "") and printed to the operator; an entry
        # with no reason is a recommendation nobody can act on.
        for rec in self._topo()["recommendations"]:
            self.assertTrue(str(rec.get("rationale") or "").strip(),
                            f"no rationale on {rec.get('action')!r}")

    def test_the_target_is_echoed_back(self):
        self.assertEqual(self._topo()["target_tasks_hour"], 10)

    def test_gap_is_never_negative(self):
        self.assertGreaterEqual(self._topo()["gap"], 0)


if __name__ == "__main__":
    unittest.main()
