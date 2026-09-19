"""db_chains: FK blast radius + cross-project peer correlation."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import db_chains as CH  # noqa: E402
import db_probes as P  # noqa: E402


EDGES = [{"child": "orders", "parent": "customers", "columns": ["customer_id"]},
         {"child": "order_items", "parent": "orders", "columns": ["order_id"]},
         {"child": "payments", "parent": "order_items", "columns": ["item_id"]},
         {"child": "unrelated_a", "parent": "unrelated_b", "columns": ["b_id"]}]
SNAP = {"facts": {"fk_edges": EDGES}}


class Base(unittest.TestCase):
    def setUp(self):
        CH._facts_cache.clear()

    def _patch_snap(self):
        return patch.object(CH.db, "select",
                            lambda t, p=None: [dict(SNAP)] if t == CH.SNAPSHOTS else [])


class BlastRadiusTest(Base):
    def test_walks_both_directions_two_hops(self):
        with self._patch_snap():
            r = CH.blast_radius("proj", "orders")
        self.assertEqual(set(r["ancestors"]), {"customers"})
        self.assertIn("order_items", r["descendants"]) and self.assertIn("payments", r["descendants"])
        self.assertEqual(r["reach"], 3)

    def test_unknown_table_yields_zero(self):
        with self._patch_snap():
            r = CH.blast_radius("proj", "nope")
        self.assertEqual(r["reach"], 0)

    def test_no_snapshot_is_empty_not_crash(self):
        with patch.object(CH.db, "select", lambda t, p=None: []):
            self.assertEqual(CH.blast_radius("proj", "orders")["reach"], 0)

    def test_cache_per_project(self):
        calls = [0]
        def counting(t, p=None):
            calls[0] += 1
            return [dict(SNAP)]
        with patch.object(CH.db, "select", counting):
            CH.blast_radius("proj", "orders")
            CH.blast_radius("proj", "orders")
        self.assertEqual(calls[0], 1, "cached within TTL")


class ChainLinesTest(Base):
    def test_high_finding_with_reach_gets_a_chain_line(self):
        def sel(t, p=None):
            if t == CH.SNAPSHOTS:
                return [dict(SNAP)]
            return [{"severity": "high", "title": "anon grants on orders", "object_name": "orders",
                     "probe_id": "anon_or_public_grants"}]
        with patch.object(CH.db, "select", sel):
            lines = CH.chain_lines("proj")
        self.assertTrue(lines and "opens into 3 tables" in lines[0])

    def test_empty_when_no_edges_or_findings(self):
        with patch.object(CH.db, "select", lambda t, p=None: []):
            self.assertEqual(CH.chain_lines("proj"), [])


class PeerCopyTest(Base):
    def test_worst_quartile_with_zero_peer(self):
        fake_baseline = {"project": "proj", "score": 10, "rank": 4, "n": 4,
                         "categories": [{"category": "security", "count": 14, "median": 6,
                                         "ratio": 2.33, "quartile": "worst"}]}
        fake_fleet = {"n": 4, "median_by_category": {"security": 6},
                      "projects": {"proj": {"by_category": {"security": 14}},
                                   "peer": {"by_category": {"security": 0}}}}
        with patch.dict("sys.modules", {}):
            import db_baselines
            with patch.object(db_baselines, "baseline", lambda p: dict(fake_baseline)), \
                 patch.object(db_baselines, "fleet", lambda: dict(fake_fleet)):
                lines = CH.peer_copy_lines("proj")
        self.assertTrue(lines and "peer closes this class at 0" in lines[0])

    def test_no_lines_when_fleet_too_small(self):
        import db_baselines
        with patch.object(db_baselines, "baseline", lambda p: {}), \
             patch.object(db_baselines, "fleet", lambda: {}):
            self.assertEqual(CH.peer_copy_lines("proj"), [])


class FactProbesTest(unittest.TestCase):
    def test_fk_graph_populates_facts_and_emits_nothing(self):
        rows = [{"child_schema": "public", "child_table": "orders", "parent_schema": "public",
                 "parent_table": "customers", "fk_columns": ["customer_id"]}]
        facts = {}
        out = P._p_fk_graph(rows, {}, facts)
        self.assertEqual(out, [])
        self.assertEqual(facts["fk_edges"][0],
                         {"child": "orders", "parent": "customers", "columns": ["customer_id"]})

    def test_column_inventory_populates_facts(self):
        rows = [{"tablename": "orders", "columns": ["id", "customer_id", "created_at"]}]
        facts = {}
        out = P._p_columns(rows, {}, facts)
        self.assertEqual(out, [])
        self.assertEqual(facts["columns"]["orders"], ["id", "customer_id", "created_at"])

    def test_catalog_stays_valid(self):
        self.assertEqual(P.validate_catalog(), [])


if __name__ == "__main__":
    unittest.main()
