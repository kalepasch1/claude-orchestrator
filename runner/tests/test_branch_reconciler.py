import os
import sys
import types
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Provide stub db before importing
_fake_db = types.ModuleType("db")
_fake_db.select = MagicMock(return_value=[])
_fake_db.insert = MagicMock()
_fake_db.update = MagicMock()
sys.modules.setdefault("db", _fake_db)

import branch_reconciler
import build_gate


class TestClusterByDependency(unittest.TestCase):
    """Clustering groups branches by same missing dependency."""

    def test_groups_by_same_module(self):
        failures = [
            {"branch": "agent/a", "has_failures": True,
             "reasons": [{"type": "missing_module", "detail": "utils.helpers"}]},
            {"branch": "agent/b", "has_failures": True,
             "reasons": [{"type": "missing_module", "detail": "utils.helpers"}]},
            {"branch": "agent/c", "has_failures": True,
             "reasons": [{"type": "missing_module", "detail": "config_loader"}]},
        ]
        clusters = branch_reconciler.cluster_by_dependency(failures)
        self.assertIn("missing_module:utils.helpers", clusters)
        self.assertEqual(len(clusters["missing_module:utils.helpers"]), 2)
        self.assertIn("missing_module:config_loader", clusters)
        self.assertEqual(len(clusters["missing_module:config_loader"]), 1)

    def test_groups_by_missing_table(self):
        failures = [
            {"branch": "agent/x", "has_failures": True,
             "reasons": [{"type": "missing_table", "detail": "accounts"}]},
            {"branch": "agent/y", "has_failures": True,
             "reasons": [{"type": "missing_table", "detail": "accounts"}]},
        ]
        clusters = branch_reconciler.cluster_by_dependency(failures)
        self.assertIn("missing_table:accounts", clusters)
        self.assertEqual(len(clusters["missing_table:accounts"]), 2)

    def test_no_reasons_goes_to_unknown(self):
        failures = [
            {"branch": "agent/z", "has_failures": False, "reasons": []},
        ]
        clusters = branch_reconciler.cluster_by_dependency(failures)
        self.assertIn("unknown", clusters)

    def test_empty_input(self):
        self.assertEqual(branch_reconciler.cluster_by_dependency([]), {})
        self.assertEqual(branch_reconciler.cluster_by_dependency(None), {})

    def test_priority_selects_actionable_type(self):
        """When a branch has both missing_module and type_error, cluster by missing_module."""
        failures = [
            {"branch": "agent/multi", "has_failures": True,
             "reasons": [
                 {"type": "type_error", "detail": "TypeError: bad arg"},
                 {"type": "missing_module", "detail": "core.engine"},
             ]},
        ]
        clusters = branch_reconciler.cluster_by_dependency(failures)
        self.assertIn("missing_module:core.engine", clusters)
        self.assertNotIn("type_error", str(list(clusters.keys())))


class TestGenerateProposals(unittest.TestCase):
    """Proposal generation creates one task per cluster."""

    def test_one_proposal_per_cluster(self):
        clusters = {
            "missing_module:utils.helpers": [
                {"branch": "agent/a", "reasons": [{"type": "missing_module", "detail": "utils.helpers"}]},
                {"branch": "agent/b", "reasons": [{"type": "missing_module", "detail": "utils.helpers"}]},
            ],
            "missing_table:accounts": [
                {"branch": "agent/c", "reasons": [{"type": "missing_table", "detail": "accounts"}]},
            ],
        }
        proposals = branch_reconciler.generate_proposals(clusters)
        self.assertEqual(len(proposals), 2)
        slugs = [p["proposal"]["slug"] for p in proposals]
        self.assertTrue(any("utils-helpers" in s for s in slugs))
        self.assertTrue(any("accounts" in s for s in slugs))

    def test_proposal_has_required_keys(self):
        clusters = {
            "missing_module:foo": [
                {"branch": "agent/x", "reasons": [{"type": "missing_module", "detail": "foo"}]},
            ],
        }
        proposals = branch_reconciler.generate_proposals(clusters)
        p = proposals[0]
        self.assertIn("dependency_key", p)
        self.assertIn("affected_branches", p)
        self.assertIn("proposal", p)
        self.assertIn("slug", p["proposal"])
        self.assertIn("prompt", p["proposal"])
        self.assertEqual(p["proposal"]["kind"], "foundation")

    def test_empty_clusters(self):
        self.assertEqual(branch_reconciler.generate_proposals({}), [])
        self.assertEqual(branch_reconciler.generate_proposals(None), [])


class TestReconcile(unittest.TestCase):
    """End-to-end reconcile orchestration."""

    @patch.object(branch_reconciler, "scan_unmerged")
    def test_reconcile_end_to_end(self, mock_scan):
        mock_scan.return_value = [
            {"branch": "agent/a", "has_failures": True,
             "reasons": [{"type": "missing_module", "detail": "core.db"}]},
            {"branch": "agent/b", "has_failures": True,
             "reasons": [{"type": "missing_module", "detail": "core.db"}]},
            {"branch": "agent/c", "has_failures": False, "reasons": []},
        ]
        result = branch_reconciler.reconcile()
        self.assertEqual(result["branches_scanned"], 3)
        self.assertEqual(result["branches_with_failures"], 2)
        self.assertEqual(len(result["proposals"]), 1)

    def test_reconcile_disabled(self):
        with patch.object(branch_reconciler, "ENABLED", False):
            result = branch_reconciler.reconcile()
            self.assertEqual(result["branches_scanned"], 0)
            self.assertIn("skipped", result)


class TestStats(unittest.TestCase):
    """Stats output."""

    @patch.object(branch_reconciler, "reconcile")
    def test_stats_keys(self, mock_reconcile):
        mock_reconcile.return_value = {
            "branches_scanned": 5,
            "branches_with_failures": 2,
            "clusters": {"a": [], "b": []},
            "proposals": [{"p": 1}, {"p": 2}],
        }
        s = branch_reconciler.stats()
        self.assertIn("enabled", s)
        self.assertIn("branches_scanned", s)
        self.assertIn("cluster_count", s)
        self.assertIn("proposal_count", s)
        self.assertEqual(s["cluster_count"], 2)
        self.assertEqual(s["proposal_count"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
