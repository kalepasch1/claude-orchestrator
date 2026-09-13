"""The probe execution engine: batching into one round trip, per-probe fallback, waves
gated on facts, selective execution, and the schema signature."""
import json
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import db_probes  # noqa: E402
from db_steering_contract import assert_read_only  # noqa: E402

SRC = {"id": "s1", "provider": "supabase", "dialect": "postgres", "ref": "abc", "label": "t",
       "project": "apparently-law", "config": {}}


class BatchQuery:
    """A query_fn that answers batch statements from a per-probe row table and records
    every statement it saw. `fail_batch` makes the combined statement raise."""

    def __init__(self, rows_by_probe, fail_batch=False, fail_single=()):
        self.rows = rows_by_probe
        self.calls = []
        self.fail_batch = fail_batch
        self.fail_single = set(fail_single)
        self.lock = threading.Lock()

    def __call__(self, source, sql, timeout=None):
        with self.lock:
            self.calls.append(sql)
        if sql.startswith("select json_build_object("):
            if self.fail_batch:
                raise RuntimeError("batch refused")
            payload = {}
            for p in db_probes.PROBES:
                if "'%s'" % p["id"] in sql:
                    payload[p["id"]] = self.rows.get(p["id"], [])
            return [{"batch": json.dumps(payload)}]
        for pid, stmt in ((p["id"], (p.get("sql") or {}).get("postgres")) for p in db_probes.PROBES):
            if stmt and stmt.strip().rstrip(";") == sql.strip().rstrip(";"):
                if pid in self.fail_single:
                    raise RuntimeError("single refused")
                return list(self.rows.get(pid, []))
        if "signature" in sql:
            return [{"signature": "abc123", "parts": 42}]
        return []


class _NoNetwork(unittest.TestCase):
    """Config probes GET the Management API; the engine tests stub that out."""

    def setUp(self):
        from unittest.mock import patch
        p = patch.object(db_probes.db_adapters, "supabase_config", lambda s, path, timeout=None: {}, create=True)
        p.start()
        self.addCleanup(p.stop)


class BatchingTest(_NoNetwork):
    def test_batchable_probes_cost_one_round_trip_each_batch(self):
        q = BatchQuery({"rls_disabled_tables": [{"schemaname": "public", "tablename": "matters", "n_live_tup": 5}]})
        out = db_probes.run_all(SRC, query_fn=q, tiers=("cheap",), advisors_fn=lambda s, k: [],
                                capabilities={"advisors": True, "pg_stat_statements": True, "dialect": "postgres"},
                                parallel=1)
        batched = [r for r in out["results"] if r.get("batched")]
        self.assertGreater(len(batched), 5)
        self.assertTrue(all(r["ok"] for r in batched), [r for r in batched if not r["ok"]])
        n_batch_calls = sum(1 for c in q.calls if c.startswith("select json_build_object("))
        self.assertLessEqual(n_batch_calls, 2)
        self.assertLess(out["stats"]["round_trips"], out["stats"]["run"])
        self.assertTrue(any(f["probe_id"] == "rls_disabled_tables" for f in out["findings"]))

    def test_batch_statement_is_read_only_and_well_formed(self):
        members = [p for p in db_probes.PROBES if db_probes._batchable(p, "postgres")][:5]
        sql = db_probes._batch_sql(members, "postgres")
        assert_read_only(sql)
        self.assertTrue(sql.startswith("select json_build_object("))
        for m in members:
            self.assertIn("'%s'" % m["id"], sql)
        self.assertNotIn(";", sql)

    def test_failed_batch_falls_back_per_probe_and_loses_nothing(self):
        q = BatchQuery({"rls_disabled_tables": [{"schemaname": "public", "tablename": "matters", "n_live_tup": 5}]},
                       fail_batch=True)
        out = db_probes.run_all(SRC, query_fn=q, tiers=("cheap",), advisors_fn=lambda s, k: [],
                                capabilities={"advisors": True, "pg_stat_statements": True, "dialect": "postgres"},
                                parallel=1)
        self.assertFalse(any(r.get("batched") for r in out["results"]))
        self.assertTrue(any(f["probe_id"] == "rls_disabled_tables" for f in out["findings"]))
        self.assertEqual(out["stats"]["failed"], 0)

    def test_batch_disabled_matches_batched_findings(self):
        rows = {"rls_disabled_tables": [{"schemaname": "public", "tablename": "matters", "n_live_tup": 5}],
                "tables_without_primary_key": [{"schemaname": "public", "tablename": "notes"}]}
        a = db_probes.run_all(SRC, query_fn=BatchQuery(rows), tiers=("cheap",), advisors_fn=lambda s, k: [],
                              capabilities={"advisors": True, "dialect": "postgres"}, batch=True, parallel=3)
        b = db_probes.run_all(SRC, query_fn=BatchQuery(rows), tiers=("cheap",), advisors_fn=lambda s, k: [],
                              capabilities={"advisors": True, "dialect": "postgres"}, batch=False, parallel=1)
        self.assertEqual(sorted(f["fingerprint"] for f in a["findings"]), sorted(f["fingerprint"] for f in b["findings"]))
        self.assertEqual([r["probe_id"] for r in a["results"]], [r["probe_id"] for r in b["results"]], "catalog order kept")

    def test_coerce_batch_accepts_object_or_text(self):
        self.assertEqual(db_probes._coerce_batch([{"batch": {"a": [1]}}]), {"a": [1]})
        self.assertEqual(db_probes._coerce_batch([{"batch": '{"a": [1]}'}]), {"a": [1]})
        self.assertEqual(db_probes._coerce_batch([{"json_build_object": {"a": []}}]), {"a": []})
        with self.assertRaises(ValueError):
            db_probes._coerce_batch([])
        with self.assertRaises(ValueError):
            db_probes._coerce_batch([{"batch": "[1,2]"}])

    def test_non_batchable_probes(self):
        adv = next(p for p in db_probes.PROBES if p.get("advisor_kind"))
        self.assertFalse(db_probes._batchable(adv, "postgres"))
        gated = next(p for p in db_probes.PROBES if p.get("requires_fact"))
        self.assertFalse(db_probes._batchable(gated, "postgres"))
        bq = {"id": "x", "sql": {"bigquery": "select 1"}}
        self.assertFalse(db_probes._batchable(bq, "bigquery"))
        tmpl = {"id": "x", "sql": {"postgres": "select * from {project}"}}
        self.assertFalse(db_probes._batchable(tmpl, "postgres"))


class WavesAndSelectionTest(_NoNetwork):
    def test_fact_gated_probe_runs_after_fact_is_established(self):
        rows = {"schema_migrations_state": [{"n": 1}],
                "schema_migrations_latest": [{"n": 3, "latest": "20260912000000"}]}
        q = BatchQuery(rows)
        out = db_probes.run_all(SRC, query_fn=q, tiers=("cheap",), advisors_fn=lambda s, k: [],
                                capabilities={"advisors": True, "dialect": "postgres"}, parallel=2)
        ids = [r["probe_id"] for r in out["results"]]
        self.assertIn("schema_migrations_latest", ids)
        self.assertTrue(out["facts"].get("has_schema_migrations"))

    def test_skip_and_only_filters(self):
        q = BatchQuery({})
        out = db_probes.run_all(SRC, query_fn=q, tiers=("cheap",), advisors_fn=lambda s, k: [],
                                capabilities={"advisors": True, "dialect": "postgres"},
                                skip_probe_ids=["rls_disabled_tables"], parallel=1)
        self.assertNotIn("rls_disabled_tables", [r["probe_id"] for r in out["results"]])
        self.assertIn({"probe_id": "rls_disabled_tables", "reason": "not selected this cycle"}, out["skipped"])
        out = db_probes.run_all(SRC, query_fn=q, tiers=("cheap", "medium", "heavy"), advisors_fn=lambda s, k: [],
                                capabilities={"advisors": True, "dialect": "postgres"},
                                probe_ids=["tables_without_primary_key"], parallel=1)
        self.assertEqual([r["probe_id"] for r in out["results"]], ["tables_without_primary_key"])

    def test_depends_on_classification(self):
        by_id = {p["id"]: p for p in db_probes.PROBES}
        self.assertEqual(db_probes.probe_depends_on(by_id["slow_query_classes"]), "data")
        self.assertEqual(db_probes.probe_depends_on(by_id["rls_disabled_tables"]), "schema")
        self.assertEqual(db_probes.probe_depends_on({"id": "new", "depends_on": "data"}), "data")
        schema = [p["id"] for p in db_probes.PROBES if db_probes.probe_depends_on(p) == "schema"]
        self.assertGreater(len(schema), 10)

    def test_parallel_units_share_facts_safely(self):
        q = BatchQuery({"table_inventory_facts": [{"tables": 10, "views": 1, "functions": 2, "db_size_bytes": 1}]})
        out = db_probes.run_all(SRC, query_fn=q, tiers=("cheap", "medium", "heavy"), advisors_fn=lambda s, k: [],
                                capabilities={"advisors": True, "pg_stat_statements": True, "dialect": "postgres"},
                                batch=False, parallel=4)
        self.assertEqual(out["stats"]["failed"], 0, [r for r in out["results"] if not r["ok"]])
        self.assertGreater(out["stats"]["run"], 20)


class ConfigProbeHookTest(unittest.TestCase):
    def test_config_path_probe_receives_payload_per_path(self):
        seen = {}

        def parse(rows, source, facts=None):
            seen["rows"] = rows
            return []
        probe = {"id": "cfg_test", "config_path": ["/config/auth", "/functions"], "parse": parse,
                 "remediation": "x", "sql": {}, "dialects": ["postgres"]}
        calls = []

        def fake_cfg(source, path, timeout=None):
            calls.append(path)
            return {"path": path}
        from unittest.mock import patch
        with patch.object(db_probes.db_adapters, "supabase_config", fake_cfg, create=True):
            res = db_probes.run_probe(probe, SRC, query_fn=lambda *a, **k: [])
        self.assertTrue(res["ok"], res)
        self.assertEqual(calls, ["/config/auth", "/functions"])
        self.assertEqual(seen["rows"], [{"/config/auth": {"path": "/config/auth"}, "/functions": {"path": "/functions"}}])


class SchemaSignatureTest(unittest.TestCase):
    def test_signature_sql_is_read_only_and_excludes_statistics(self):
        sql = db_probes.SCHEMA_SIGNATURE_SQL["postgres"]
        assert_read_only(sql)
        self.assertIn("pg_class", sql)
        self.assertIn("pg_policy", sql)
        self.assertNotIn("n_live_tup", sql)
        self.assertNotIn("pg_stat", sql)

    def test_signature_value_and_failure_modes(self):
        self.assertEqual(db_probes.schema_signature(SRC, query_fn=lambda s, sql, timeout=None: [{"signature": "h", "parts": 3}]), "h:3")
        self.assertIsNone(db_probes.schema_signature(SRC, query_fn=lambda s, sql, timeout=None: []))

        def boom(s, sql, timeout=None):
            raise RuntimeError("down")
        self.assertIsNone(db_probes.schema_signature(SRC, query_fn=boom))
        self.assertIsNone(db_probes.schema_signature(dict(SRC, dialect="mysql", provider="mysql"), query_fn=boom))


if __name__ == "__main__":
    unittest.main()
