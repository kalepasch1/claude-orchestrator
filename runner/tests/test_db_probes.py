#!/usr/bin/env python3
"""db_probes: the deterministic, zero-model-cost probe catalog.

What must hold, and why each is tested rather than trusted:

* Every statement in the catalog is one read: passes assert_read_only, carries no ';',
  and every id/tier/category/dialect/evidence kind is contract vocabulary. A typo here
  would otherwise poison db_findings at 3 a.m.
* Parse functions are pure and tolerant: "t"/true/"true" agree, CLI strings and driver
  numbers agree, and the severity thresholds documented in each parse are exact.
* run_all is fail-soft: one probe raising does not lose the others; findings dedup by
  fingerprint keeping the most severe; probes skip cleanly on dialect, provider,
  capability and fact gates.
* Score arithmetic is 25/10/3/1 with supports ignored and a floor of 0.
* No model module is imported: probes are SQL plus pure Python, by contract.
"""
import ast
import inspect
import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import db_probes  # noqa: E402
from db_probes import PROBES, probe_by_id, probes_for  # noqa: E402
from db_steering_contract import (  # noqa: E402
    CATEGORIES, DIALECTS, EVIDENCE_KINDS, PROBE_TIERS, SEVERITIES, assert_read_only, fingerprint,
)

PG = {"provider": "postgres", "ref": "db.internal", "project": "proj"}
SUPA = {"provider": "supabase", "ref": "abcdefghijklmnop", "project": "proj"}
BQ = {"provider": "gcp_bigquery", "ref": "my-project", "config": {"project_id": "my-project", "dataset": "analytics"}}

SQL_TO_ID = {p["sql"][d]: (p["id"], d) for p in PROBES for d in p["sql"]}


def parse_of(pid):
    return probe_by_id(pid)["parse"]


def run_parse(pid, rows, source=PG, facts=None):
    return parse_of(pid)(rows, source, facts if facts is not None else {})


def only(findings):
    assert len(findings) == 1, findings
    return findings[0]


# ── catalog hygiene ────────────────────────────────────────────────────────────────────

class TestCatalog(unittest.TestCase):
    def test_thirty_probes_with_unique_ids(self):
        ids = [p["id"] for p in PROBES]
        self.assertEqual(len(ids), 30)
        self.assertEqual(len(set(ids)), len(ids))
        self.assertTrue(all(re.match(r"^[a-z][a-z0-9_]+$", i) for i in ids))

    def test_vocabulary(self):
        for p in PROBES:
            with self.subTest(probe=p["id"]):
                self.assertIn(p["tier"], PROBE_TIERS)
                self.assertIn(p["category"], CATEGORIES)
                self.assertTrue(p["evidence_kinds"])
                for k in p["evidence_kinds"]:
                    self.assertIn(k, EVIDENCE_KINDS)
                self.assertTrue(p["dialects"])
                for d in p["dialects"]:
                    self.assertIn(d, DIALECTS)
                self.assertTrue(set(p["sql"]) <= set(p["dialects"]))
                self.assertTrue(str(p.get("remediation") or "").strip())
                self.assertTrue(str(p.get("title") or "").strip())
                if p.get("advisor_kind"):
                    self.assertIn(p["advisor_kind"], ("security", "performance"))
                    self.assertEqual(p["providers"], ["supabase"])
                else:
                    self.assertTrue(callable(p["parse"]))
                    self.assertTrue(p["sql"], "a SQL probe needs at least one statement")

    def test_every_statement_is_one_read_without_semicolons(self):
        for p in PROBES:
            for dialect, sql in p["sql"].items():
                with self.subTest(probe=p["id"], dialect=dialect):
                    rendered = db_probes._render_sql(sql, BQ if dialect == "bigquery" else PG)
                    self.assertNotIn(";", rendered)
                    self.assertEqual(assert_read_only(rendered), rendered)
                    self.assertTrue(re.match(r"^\s*(select|with)\b", rendered, re.I), rendered[:60])
                    self.assertNotIn("{", rendered, "placeholders must all be rendered")

    def test_validate_catalog_is_clean(self):
        self.assertEqual(db_probes.validate_catalog(), [])

    def test_validate_catalog_catches_a_bad_probe(self):
        bad = [{"id": "x", "category": "nope", "tier": "cheap", "dialects": ["postgres", "oracle"],
                "evidence_kinds": ["not_a_kind"], "sql": {"postgres": "delete from t"}, "parse": None},
               {"id": "x", "category": "security", "tier": "weekly", "dialects": [], "evidence_kinds": [], "sql": {},
                "parse": lambda r, s, f: []}]
        with mock.patch.object(db_probes, "PROBES", bad):
            problems = db_probes.validate_catalog()
        joined = "\n".join(problems)
        for needle in ("duplicate probe id x", "bad category", "bad tier", "bad dialect 'oracle'",
                       "bad evidence kind", "parse is not callable", "x/postgres"):
            self.assertIn(needle, joined)

    def test_lookups(self):
        self.assertEqual(probe_by_id("rls_disabled_tables")["category"], "security")
        self.assertIsNone(probe_by_id("no_such_probe"))
        self.assertIsNone(probe_by_id(None))
        pg = probes_for("postgres")
        self.assertTrue(pg and all("postgres" in p["dialects"] for p in pg))
        self.assertEqual({p["tier"] for p in probes_for("mysql", tier="cheap")}, {"cheap"})
        self.assertEqual(probes_for("mongodb"), [])
        self.assertEqual([p["id"] for p in probes_for("bigquery")],
                         ["table_inventory_facts", "pii_columns_inventory", "partition_or_cluster_missing"])

    def test_gates_are_declared_where_expected(self):
        self.assertEqual(probe_by_id("slow_query_classes")["requires_capability"], "pg_stat_statements")
        self.assertEqual(probe_by_id("schema_migrations_latest")["requires_fact"], "has_schema_migrations")
        self.assertEqual(probe_by_id("pg_cron_jobs")["requires_fact"], "has_pg_cron")
        # facts are produced by probes that run EARLIER in catalog order
        order = [p["id"] for p in PROBES]
        self.assertLess(order.index("schema_migrations_state"), order.index("schema_migrations_latest"))
        self.assertLess(order.index("extensions_in_public"), order.index("pg_cron_jobs"))

    def test_render_sql_whitelists_identifiers(self):
        sql = probe_by_id("pii_columns_inventory")["sql"]["bigquery"]
        self.assertIn("`my-project.analytics`", db_probes._render_sql(sql, BQ))
        with self.assertRaises(ValueError):
            db_probes._render_sql(sql, {"config": {"project_id": "p", "dataset": "ds; drop table x"}})
        with self.assertRaises(ValueError):
            db_probes._render_sql(sql, {"config": {"project_id": "p"}})
        self.assertEqual(db_probes._render_sql("select 1", None), "select 1")


class TestNoModelModules(unittest.TestCase):
    def test_not_in_globals(self):
        for name in ("model_gateway", "model_policy"):
            self.assertNotIn(name, vars(db_probes))
        self.assertNotIn("model_gateway", sys.modules.get("db_probes").__dict__)

    def test_not_in_source_outside_the_docstring(self):
        src = inspect.getsource(db_probes)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [a.name for a in node.names]
            else:
                continue
            for n in names:
                self.assertNotRegex(n, r"model_(gateway|policy)", f"db_probes imports {n}")
        # The module docstring names them only to say this test exists; the code may not.
        first = tree.body[0]
        code_only = "\n".join(src.splitlines()[first.end_lineno:]) if isinstance(first, ast.Expr) else src
        self.assertNotIn("model_gateway", code_only)
        self.assertNotIn("model_policy", code_only)
        self.assertNotIn("import_module", code_only)


# ── row helpers ────────────────────────────────────────────────────────────────────────

class TestRowHelpers(unittest.TestCase):
    def test_v_is_case_tolerant(self):
        self.assertEqual(db_probes._v({"TABLENAME": "t"}, "tablename"), "t")
        self.assertEqual(db_probes._v({"tablename": None, "table_name": "u"}, "tablename", "table_name"), "u")
        self.assertEqual(db_probes._v("not a row", "x", default=7), 7)

    def test_bool_num_list(self):
        for truthy in (True, "t", "true", "TRUE", 1, "1", "yes", "on", 2.0):
            self.assertTrue(db_probes._bool(truthy), truthy)
        for falsy in (False, "f", "false", 0, "0", None, "", "no"):
            self.assertFalse(db_probes._bool(falsy), falsy)
        self.assertEqual(db_probes._num("12.5"), 12.5)
        self.assertEqual(db_probes._num(None), 0.0)
        self.assertEqual(db_probes._num("n/a", default=-1), -1)
        self.assertEqual(db_probes._num(True), 1.0)
        self.assertEqual(db_probes._list(["a", 1]), ["a", "1"])
        self.assertEqual(db_probes._list("{email,phone}"), ["email", "phone"])
        self.assertEqual(db_probes._list('["email", "phone"]'), ["email", "phone"])
        self.assertEqual(db_probes._list('{"a b",c}'), ["a b", "c"])
        self.assertEqual(db_probes._list("email,phone"), ["email", "phone"])
        self.assertEqual(db_probes._list(None), [])


# ── parse functions ────────────────────────────────────────────────────────────────────

class TestParseRls(unittest.TestCase):
    def test_off_tables_with_pii_bump_and_facts(self):
        rows = [{"schemaname": "public", "tablename": "users", "rowsecurity": False},
                {"schemaname": "public", "tablename": "countries", "rowsecurity": "f"},
                {"schemaname": "public", "tablename": "posts", "rowsecurity": "t"},
                {"SCHEMANAME": "public", "TABLENAME": "invoices", "ROWSECURITY": "false"}]
        facts = {}
        out = run_parse("rls_disabled_tables", rows, facts=facts)
        self.assertEqual(facts, {"public_tables": 4, "rls_off_tables": 3})
        by = {f["object_name"]: f for f in out}
        self.assertEqual(set(by), {"users", "countries", "invoices"})
        self.assertEqual(by["users"]["severity"], "high")
        self.assertTrue(by["users"]["metrics"]["pii_name"])
        self.assertIn("personal data", by["users"]["detail"])
        self.assertEqual(by["countries"]["severity"], "medium")
        self.assertFalse(by["countries"]["metrics"]["pii_name"])
        self.assertEqual(by["invoices"]["severity"], "high", "invoice matches the PII table pattern")
        for f in out:
            self.assertEqual(f["direction"], "undermines")
            self.assertEqual(f["evidence_kinds"], ["access_control"])
            self.assertEqual(f["category"], "security")
            self.assertEqual(f["fingerprint"], fingerprint("rls_disabled_tables", "public", f["object_name"]))

    def test_positive_finding_when_every_table_enforces_rls(self):
        rows = [{"schemaname": "public", "tablename": "a", "rowsecurity": True},
                {"schemaname": "public", "tablename": "b", "rowsecurity": "t"}]
        f = only(run_parse("rls_disabled_tables", rows))
        self.assertEqual((f["direction"], f["severity"]), ("supports", "info"))
        self.assertEqual(f["title"], "All 2 public tables enforce RLS")
        self.assertEqual(f["metrics"], {"tables": 2})
        self.assertEqual(f["fingerprint"], fingerprint("rls_disabled_tables", extra="all_rls"))
        self.assertEqual(run_parse("rls_disabled_tables", []), [], "no tables: nothing to praise or blame")

    def test_rls_no_policy(self):
        f = only(run_parse("rls_enabled_no_policy", [{"schemaname": "public", "tablename": "matters"}]))
        self.assertEqual(f["severity"], "medium")
        self.assertEqual(f["title"], "RLS enabled but no policies on public.matters")


class TestParseAnonGrants(unittest.TestCase):
    def _row(self, table, grantee, priv, rls):
        return {"grantee": grantee, "schemaname": "public", "tablename": table, "privilege_type": priv, "rowsecurity": rls}

    def test_severities(self):
        rows = [self._row("customers", "anon", "SELECT", False),
                self._row("countries", "anon", "SELECT", False),
                self._row("notes", "anon", "INSERT", True),
                self._row("customers", "PUBLIC", "SELECT", True),
                self._row("countries", "PUBLIC", "select", "f"),
                self._row("countries", "PUBLIC", "UPDATE", "f")]
        out = run_parse("anon_or_public_grants", rows)
        by = {(f["object_name"], f["metrics"]["privileges"] and f["title"].split(" holds")[0]): f for f in out}
        self.assertEqual(len(out), 5, "rows group by (schema, table, grantee)")
        self.assertEqual(by[("customers", "anon")]["severity"], "high", "SELECT on a PII table with RLS off")
        self.assertEqual(by[("countries", "anon")]["severity"], "low", "SELECT on reference data")
        self.assertEqual(by[("notes", "anon")]["severity"], "medium", "write grant, but RLS gates it")
        self.assertEqual(by[("customers", "PUBLIC")]["severity"], "medium", "PII SELECT but RLS gates it")
        self.assertEqual(by[("countries", "PUBLIC")]["severity"], "high", "unconditional write grant")
        self.assertEqual(by[("countries", "PUBLIC")]["metrics"]["privileges"], ["SELECT", "UPDATE"])
        self.assertEqual(by[("countries", "PUBLIC")]["title"], "PUBLIC holds SELECT, UPDATE on public.countries")
        self.assertIn("OFF", by[("countries", "PUBLIC")]["detail"])
        self.assertIn("policies decide", by[("notes", "anon")]["detail"])

    def test_evidence_kinds_and_identity(self):
        rows = [self._row("customers", "anon", "SELECT", False), self._row("notes", "anon", "INSERT", True),
                self._row("countries", "anon", "SELECT", False)]
        by = {f["object_name"]: f for f in run_parse("anon_or_public_grants", rows)}
        self.assertEqual(by["customers"]["evidence_kinds"], ["access_control", "data_minimization"])
        self.assertEqual(by["countries"]["evidence_kinds"], ["access_control", "data_minimization"], "any SELECT")
        self.assertEqual(by["notes"]["evidence_kinds"], ["access_control"], "write-only, non-PII")
        self.assertTrue(by["customers"]["metrics"]["pii_name"])
        self.assertFalse(by["customers"]["metrics"]["rowsecurity"])
        # the grantee is part of identity: anon and PUBLIC on one table are two findings
        two = run_parse("anon_or_public_grants", [self._row("t", "anon", "SELECT", True), self._row("t", "PUBLIC", "SELECT", True)])
        self.assertEqual(len({f["fingerprint"] for f in two}), 2)
        self.assertEqual(two[0]["fingerprint"], fingerprint("anon_or_public_grants", "public", "t", extra="PUBLIC"))

    def test_missing_rowsecurity_column_defaults_to_gated(self):
        f = only(run_parse("anon_or_public_grants", [{"grantee": "anon", "schemaname": "public", "tablename": "users",
                                                      "privilege_type": "DELETE"}]))
        self.assertEqual(f["severity"], "medium")


class TestParseIntegrity(unittest.TestCase):
    def test_no_pk_size_threshold(self):
        rows = [{"schemaname": "public", "tablename": "big", "est_rows": 10001},
                {"schemaname": "public", "tablename": "edge", "est_rows": 10000},
                {"schemaname": "public", "tablename": "cli", "est_rows": "5"},
                {"schemaname": "public", "tablename": "fresh", "est_rows": -1}]
        by = {f["object_name"]: f for f in run_parse("tables_without_primary_key", rows)}
        self.assertEqual(by["big"]["severity"], "high")
        self.assertEqual(by["edge"]["severity"], "medium")
        self.assertEqual(by["cli"]["severity"], "medium")
        self.assertEqual(by["cli"]["metrics"], {"est_rows": 5})
        self.assertEqual(by["fresh"]["metrics"], {"est_rows": 0}, "reltuples -1 means never analysed")
        self.assertEqual(by["big"]["category"], "integrity")
        self.assertEqual(by["big"]["evidence_kinds"], ["integrity"])

    def test_unindexed_fk(self):
        rows = [{"schemaname": "public", "tablename": "orders", "conname": "orders_user_fk", "referenced_table": "users",
                 "referenced_rows": 100001, "est_rows": 50},
                {"schemaname": "public", "tablename": "orders", "conname": "orders_shop_fk", "referenced_table": "shops",
                 "referenced_rows": "100000", "est_rows": None}]
        out = run_parse("unindexed_foreign_keys", rows)
        by = {f["metrics"]["constraint"]: f for f in out}
        self.assertEqual(by["orders_user_fk"]["severity"], "high")
        self.assertEqual(by["orders_shop_fk"]["severity"], "medium")
        self.assertEqual(by["orders_user_fk"]["metrics"],
                         {"constraint": "orders_user_fk", "referenced_table": "users", "referenced_rows": 100001, "est_rows": 50})
        self.assertEqual(by["orders_shop_fk"]["metrics"]["est_rows"], 0)
        self.assertEqual(out[0]["category"], "performance")
        self.assertEqual(out[0]["evidence_kinds"], ["availability", "integrity"])
        self.assertEqual(len({f["fingerprint"] for f in out}), 2, "two FKs on one table are two findings")
        self.assertIn("orders_user_fk on public.orders", by["orders_user_fk"]["title"])

    def test_unvalidated_constraints_and_text_keys(self):
        f = only(run_parse("unvalidated_constraints", [{"schemaname": "public", "tablename": "t", "conname": "t_fk", "contype": "f"}]))
        self.assertEqual((f["severity"], f["metrics"]), ("medium", {"contype": "f"}))
        f = only(run_parse("uuid_text_keys", [{"schemaname": "public", "tablename": "t", "column_name": "id"}]))
        self.assertEqual(f["severity"], "low")
        self.assertEqual(f["fingerprint"], fingerprint("uuid_text_keys", "public", "t", extra="id"))


class TestParseAvailability(unittest.TestCase):
    def test_sequence_headroom_thresholds(self):
        rows = [{"schemaname": "public", "sequencename": "low_id_seq", "used_ratio": 0.5},
                {"schemaname": "public", "sequencename": "edge_id_seq", "used_ratio": "0.6"},
                {"schemaname": "public", "sequencename": "warn_id_seq", "used_ratio": 0.61, "last_value": 5, "max_value": 8},
                {"schemaname": "public", "sequencename": "edge2_id_seq", "used_ratio": 0.85},
                {"schemaname": "public", "sequencename": "crit_id_seq", "used_ratio": "0.86"}]
        by = {f["object_name"]: f for f in run_parse("sequence_headroom", rows)}
        self.assertEqual(set(by), {"warn_id_seq", "edge2_id_seq", "crit_id_seq"}, "<= 0.6 is headroom, not a finding")
        self.assertEqual(by["warn_id_seq"]["severity"], "medium")
        self.assertEqual(by["edge2_id_seq"]["severity"], "medium")
        self.assertEqual(by["crit_id_seq"]["severity"], "critical")
        self.assertEqual(by["warn_id_seq"]["title"], "Sequence public.warn_id_seq is 61% consumed")
        self.assertEqual(by["warn_id_seq"]["metrics"], {"used_ratio": 0.61, "last_value": "5", "max_value": "8"})

    def test_slow_query_classes(self):
        rows = [{"queryid": "111", "calls": 10, "total_exec_time": 30000.0, "mean_exec_time": 2000.1, "query": "select …"},
                {"queryid": 222, "calls": "500000", "total_exec_time": "1000", "mean_exec_time": "2000", "query": "x" * 500}]
        by = {f["metrics"]["queryid"]: f for f in run_parse("slow_query_classes", rows)}
        self.assertEqual(by["111"]["severity"], "high")
        self.assertEqual(by["222"]["severity"], "medium")
        self.assertEqual(by["222"]["metrics"], {"queryid": "222", "calls": 500000, "mean_exec_ms": 2000.0, "total_exec_ms": 1000.0})
        self.assertLessEqual(len(by["222"]["detail"]), 200)
        self.assertEqual(by["111"]["title"], "Query class 111: mean 2000 ms over 10 calls")
        self.assertEqual(by["111"]["fingerprint"], fingerprint("slow_query_classes", extra="111"))
        self.assertEqual(by["111"]["category"], "performance")

    def test_dead_tuples_vacuum_and_long_txns(self):
        rows = [{"schemaname": "public", "tablename": "hot", "n_live_tup": 100, "n_dead_tup": 51},
                {"schemaname": "public", "tablename": "warm", "n_live_tup": "100", "n_dead_tup": "50", "last_autovacuum": "2026-09-01"}]
        by = {f["object_name"]: f for f in run_parse("dead_tuple_bloat", rows)}
        self.assertEqual((by["hot"]["severity"], by["warm"]["severity"]), ("high", "medium"))
        self.assertEqual(by["hot"]["metrics"]["ratio"], 0.51)
        rows = [{"schemaname": "public", "tablename": "never", "n_live_tup": 200000, "last_autovacuum": None},
                {"schemaname": "public", "tablename": "stale", "n_live_tup": 200000, "last_autovacuum": "2026-08-01"}]
        by = {f["object_name"]: f for f in run_parse("vacuum_stale", rows)}
        self.assertEqual((by["never"]["severity"], by["stale"]["severity"]), ("medium", "low"))
        self.assertIn("never ran", by["never"]["title"])
        self.assertIn("stale", by["stale"]["title"])
        f = only(run_parse("long_running_transactions", [{"pid": 42, "usename": "app", "state": "active",
                                                          "xact_age_s": "725.5", "verb": "SELECT"}]))
        self.assertEqual(f["title"], "Transaction open 12 min (pid 42, app)")
        self.assertEqual(f["metrics"]["age_s"], 725)

    def test_unused_and_duplicate_indexes(self):
        rows = [{"schemaname": "public", "tablename": "t", "indexname": "big_idx", "index_bytes": 100 * 1024 * 1024 + 1, "idx_scan": 0},
                {"schemaname": "public", "tablename": "t", "indexname": "small_idx", "index_bytes": "9000000", "idx_scan": "0"}]
        by = {f["metrics"]["index"]: f for f in run_parse("unused_indexes", rows)}
        self.assertEqual((by["big_idx"]["severity"], by["small_idx"]["severity"]), ("medium", "low"))
        self.assertEqual(by["big_idx"]["category"], "cost")
        f = only(run_parse("duplicate_indexes", [{"schemaname": "public", "tablename": "t", "indexes": "{b_idx,a_idx}", "n": 2}]))
        self.assertEqual(f["metrics"]["indexes"], ["b_idx", "a_idx"])
        self.assertEqual(f["fingerprint"], fingerprint("duplicate_indexes", "public", "t", extra="a_idx,b_idx"))


class TestParseAudit(unittest.TestCase):
    def test_missing_audit_columns(self):
        rows = [{"schemaname": "public", "tablename": "invoices", "has_created": False, "has_updated": False, "has_update_grants": True},
                {"schemaname": "public", "tablename": "notes", "has_created": "t", "has_updated": "f", "has_update_grants": "t"},
                {"schemaname": "public", "tablename": "logs", "has_created": "true", "has_updated": "false", "has_update_grants": "false"},
                {"schemaname": "public", "tablename": "full", "has_created": 1, "has_updated": 1, "has_update_grants": 1}]
        facts = {}
        out = run_parse("missing_audit_columns", rows, facts=facts)
        by = {f["object_name"]: f for f in out}
        self.assertEqual(set(by), {"invoices", "notes"}, "an append-only table without updated_at is not a gap")
        self.assertEqual(by["invoices"]["severity"], "medium")
        self.assertEqual(by["invoices"]["title"], "No created_at/inserted_at on public.invoices")
        self.assertEqual(by["notes"]["severity"], "low")
        self.assertIn("no updated_at", by["notes"]["title"])
        self.assertEqual(facts, {"tables_missing_created_at": 1})
        self.assertTrue(all(f["evidence_kinds"] == ["audit_trail"] and f["category"] == "audit" for f in out))

    def test_missing_audit_positive_when_all_stamped(self):
        rows = [{"schemaname": "public", "tablename": "a", "has_created": True, "has_updated": True, "has_update_grants": False},
                {"schemaname": "public", "tablename": "b", "has_created": "t", "has_updated": "f", "has_update_grants": "f"}]
        f = only(run_parse("missing_audit_columns", rows))
        self.assertEqual((f["direction"], f["severity"]), ("supports", "info"))
        self.assertEqual(f["title"], "All 2 public tables carry a creation timestamp")
        self.assertEqual(f["fingerprint"], fingerprint("missing_audit_columns", extra="all_created"))
        self.assertEqual(run_parse("missing_audit_columns", []), [])

    def test_audit_trail_presence_positive_and_negative(self):
        facts = {}
        f = only(run_parse("audit_trail_presence", [{"schemaname": "public", "tablename": "matter_events"},
                                                    {"schemaname": "public", "tablename": "audit_log"}], facts=facts))
        self.assertEqual((f["direction"], f["severity"]), ("supports", "info"))
        self.assertEqual(f["title"], "2 audit/event tables present")
        self.assertEqual(f["metrics"], {"count": 2, "tables": ["public.matter_events", "public.audit_log"]})
        self.assertEqual(facts["audit_tables"], ["public.matter_events", "public.audit_log"])
        self.assertIn("public.matter_events, public.audit_log", f["detail"])
        facts = {}
        g = only(run_parse("audit_trail_presence", [], facts=facts))
        self.assertEqual((g["direction"], g["severity"]), ("undermines", "medium"))
        self.assertEqual(g["title"], "No audit/event/log tables found in public")
        self.assertEqual(facts["audit_tables"], [])
        self.assertEqual(f["fingerprint"], g["fingerprint"], "presence and absence are the same fact, so one flips the other")

    def test_ai_logging_presence(self):
        f = only(run_parse("ai_call_logging_presence", [{"schemaname": "public", "tablename": "model_calls"}]))
        self.assertEqual((f["direction"], f["severity"]), ("supports", "info"))
        self.assertEqual(f["evidence_kinds"], ["ai_logging", "audit_trail"])
        g = only(run_parse("ai_call_logging_presence", []))
        self.assertEqual((g["direction"], g["severity"], g["category"]), ("undermines", "medium", "ai_governance"))
        self.assertEqual(g["evidence_kinds"], ["ai_logging"])


class TestParsePrivacyRetention(unittest.TestCase):
    def test_pii_exposed_tables(self):
        rows = [{"schemaname": "public", "tablename": "clients", "rowsecurity": False, "columns": ["email", "phone"]},
                {"schemaname": "public", "tablename": "leads", "rowsecurity": "f", "columns": "{email,ip_address}"},
                {"schemaname": "public", "tablename": "kyc", "rowsecurity": "f", "columns": '["passport", "dob"]'}]
        by = {f["object_name"]: f for f in run_parse("pii_exposed_tables", rows)}
        for name in ("clients", "leads", "kyc"):
            self.assertEqual(by[name]["severity"], "high")
            self.assertEqual(by[name]["category"], "privacy")
            self.assertEqual(by[name]["evidence_kinds"], ["data_minimization", "access_control"])
            self.assertEqual(by[name]["direction"], "undermines")
        self.assertEqual(by["leads"]["metrics"], {"columns": ["email", "ip_address"]})
        self.assertEqual(by["kyc"]["metrics"], {"columns": ["passport", "dob"]})
        self.assertEqual(by["clients"]["title"], "Personal data in public.clients with RLS off (email, phone)")

    def test_pii_inventory_is_positive_and_counts(self):
        facts = {}
        out = run_parse("pii_columns_inventory", [{"schemaname": "public", "tablename": "users", "columns": "{email}"},
                                                  {"schemaname": "public", "tablename": "kyc", "columns": ["dob"]}], facts=facts)
        self.assertEqual(facts, {"pii_tables": 2})
        self.assertTrue(all(f["direction"] == "supports" and f["severity"] == "info" for f in out))
        self.assertEqual(out[0]["metrics"], {"columns": ["email"]})

    def test_soft_delete_and_cron(self):
        f = only(run_parse("soft_delete_without_purge", [{"schemaname": "public", "tablename": "matters"}]))
        self.assertEqual((f["severity"], f["category"]), ("low", "retention"))
        facts = {}
        g = only(run_parse("pg_cron_jobs", [], facts=facts))
        self.assertEqual((g["direction"], g["severity"]), ("undermines", "low"))
        self.assertEqual(facts["cron_jobs"], [])
        h = only(run_parse("pg_cron_jobs", [{"jobid": 1, "jobname": "purge", "schedule": "0 3 * * *"}, {"jobid": 2}], facts=facts))
        self.assertEqual((h["direction"], h["severity"]), ("supports", "info"))
        self.assertEqual(h["metrics"]["jobs"], ["purge", "job 2"])
        self.assertIn("purge [0 3 * * *]", h["detail"])
        self.assertEqual(g["fingerprint"], h["fingerprint"])


class TestParseFactsAndSchema(unittest.TestCase):
    def test_table_inventory_facts(self):
        row = {"tables": 12, "views": "3", "matviews": 0, "functions": 7, "db_size_bytes": 5 * 1048576, "db_size": "5120 kB", "dbname": "postgres"}
        facts = {}
        f = only(run_parse("table_inventory_facts", [row], facts=facts))
        self.assertEqual(facts, {"tables": 12, "views": 3, "matviews": 0, "functions": 7, "db_size_bytes": 5 * 1048576, "database": "postgres"})
        self.assertEqual((f["direction"], f["severity"], f["category"]), ("supports", "info", "availability"))
        self.assertEqual(f["title"], "12 tables, 3 views, 0 materialized views, 7 functions, 5120 kB")
        self.assertEqual(f["metrics"], {"tables": 12, "views": 3, "matviews": 0, "functions": 7, "db_size_bytes": 5 * 1048576})
        self.assertEqual(f["fingerprint"], fingerprint("table_inventory_facts", extra="inventory"))
        facts = {}
        g = only(run_parse("table_inventory_facts", [], facts=facts))
        self.assertEqual(g["title"], "0 tables, 0 views, 0 materialized views, 0 functions, 0 MB")
        self.assertEqual(facts["db_size_bytes"], 0)

    def test_extensions(self):
        rows = [{"extname": "pg_cron", "extversion": "1.6", "schemaname": "pg_catalog"},
                {"extname": "pg_stat_statements", "extversion": "1.10", "schemaname": "extensions"},
                {"extname": "postgis", "extversion": "3.4", "schemaname": "public"},
                {"extname": "plpgsql", "extversion": "1.0", "schemaname": "public"}]
        facts = {}
        f = only(run_parse("extensions_in_public", rows, facts=facts))
        self.assertEqual(f["object_name"], "postgis")
        self.assertEqual((f["severity"], f["category"], f["metrics"]), ("low", "schema_drift", {"version": "3.4"}))
        self.assertEqual(facts, {"extensions": ["pg_cron", "pg_stat_statements", "plpgsql", "postgis"],
                                 "has_pg_cron": True, "has_pg_stat_statements": True})

    def test_migrations_state_and_latest(self):
        facts = {}
        f = only(run_parse("schema_migrations_state", [{"n": 0}], source=SUPA, facts=facts))
        self.assertEqual(facts, {"has_schema_migrations": False})
        self.assertEqual((f["severity"], f["direction"]), ("low", "undermines"))
        self.assertEqual(f["fingerprint"], fingerprint("schema_migrations_state", extra="absent"))
        facts = {}
        self.assertEqual(run_parse("schema_migrations_state", [{"n": "1"}], source=SUPA, facts=facts), [])
        self.assertTrue(facts["has_schema_migrations"])
        self.assertEqual(run_parse("schema_migrations_state", [], source=PG), [], "only Supabase is expected to have the table")
        facts = {}
        g = only(run_parse("schema_migrations_latest", [{"n": 12, "latest": "20260901120000"}], source=SUPA, facts=facts))
        self.assertEqual(facts, {"migrations_applied": 12, "latest_migration": "20260901120000"})
        self.assertEqual((g["direction"], g["severity"]), ("supports", "info"))
        self.assertEqual(g["title"], "12 migrations applied, latest 20260901120000")
        h = only(run_parse("schema_migrations_latest", [], source=SUPA))
        self.assertEqual(h["title"], "0 migrations applied, latest (none)")

    def test_secdef_timestamps_partition(self):
        rows = [{"schemaname": "public", "funcname": "admin_reset", "signature": "admin_reset(uuid)"},
                {"schemaname": "public", "funcname": "slugify", "signature": ""}]
        by = {f["object_name"]: f for f in run_parse("security_definer_functions", rows)}
        self.assertEqual((by["admin_reset"]["severity"], by["slugify"]["severity"]), ("medium", "low"))
        self.assertEqual(by["admin_reset"]["title"], "Definer-rights function public.admin_reset(uuid)")
        self.assertEqual(by["slugify"]["title"], "Definer-rights function public.slugify")
        f = only(run_parse("timestamp_without_timezone", [{"schemaname": "public", "tablename": "t", "columns": "{a,b}"}]))
        self.assertEqual(f["metrics"], {"columns": ["a", "b"]})
        f = only(run_parse("partition_or_cluster_missing", [{"schemaname": "ds", "tablename": "events", "size_bytes": 2 * 1073741824, "row_count": "9"}], source=BQ))
        self.assertEqual(f["title"], "ds.events (2.0 GB) is neither partitioned nor clustered")
        self.assertEqual(f["metrics"], {"size_bytes": 2 * 1073741824, "row_count": 9})


# ── advisors ───────────────────────────────────────────────────────────────────────────

class TestAdvisorsToFindings(unittest.TestCase):
    def _lint(self, name, level, schema="public", obj="users", **kw):
        return {"name": name, "level": level, "title": kw.pop("title", name.replace("_", " ")),
                "detail": "d", "remediation": kw.pop("remediation", "https://supabase.com/docs/x"),
                "metadata": {"schema": schema, "name": obj, "type": "table"}, "cache_key": f"{name}_{obj}", **kw}

    def test_level_mapping(self):
        lints = [self._lint("rls_disabled_in_public", "ERROR"), self._lint("policy_exists_rls_disabled", "WARN"),
                 self._lint("auth_users_exposed", "warning"), self._lint("function_search_path_mutable", "INFO"),
                 self._lint("something_new", "verbose"), self._lint("no_level", None)]
        out = db_probes.advisors_to_findings(lints, "security", SUPA)
        self.assertEqual([f["severity"] for f in out], ["high", "medium", "medium", "low", "low", "low"])
        self.assertTrue(all(f["probe_id"] == "supabase_advisor_security" and f["category"] == "security" for f in out))
        self.assertTrue(all(f["direction"] == "undermines" for f in out))
        self.assertTrue(all(f["evidence_kinds"] == ["access_control"] for f in out[:4]))

    def test_object_identity_and_title(self):
        a, b = db_probes.advisors_to_findings([self._lint("rls_disabled_in_public", "ERROR", obj="users"),
                                               self._lint("rls_disabled_in_public", "ERROR", obj="posts")], "security", SUPA)
        self.assertEqual((a["object_schema"], a["object_name"]), ("public", "users"))
        self.assertEqual(a["title"], "rls disabled in public: public.users")
        self.assertEqual(a["fingerprint"], fingerprint("supabase_advisor_security", "public", "users", extra="rls_disabled_in_public"))
        self.assertNotEqual(a["fingerprint"], b["fingerprint"])
        same = db_probes.advisors_to_findings([self._lint("rls_disabled_in_public", "WARN", obj="users")], "security", SUPA)[0]
        self.assertEqual(same["fingerprint"], a["fingerprint"], "level is a metric, not identity")
        other = db_probes.advisors_to_findings([self._lint("auth_users_exposed", "ERROR", obj="users")], "security", SUPA)[0]
        self.assertNotEqual(other["fingerprint"], a["fingerprint"], "two lints on one object are two findings")
        self.assertEqual(a["remediation"], "https://supabase.com/docs/x")
        self.assertEqual(a["metrics"]["lint"], "rls_disabled_in_public")
        self.assertEqual(a["metrics"]["level"], "ERROR")
        self.assertEqual(a["metrics"]["type"], "table")

    def test_performance_kind_category_overrides(self):
        lints = [self._lint("unindexed_foreign_keys", "INFO", obj="orders"), self._lint("unused_index", "INFO"),
                 self._lint("extension_in_public", "WARN", obj="postgis"), self._lint("no_primary_key", "INFO"),
                 self._lint("multiple_permissive_policies", "WARN"), self._lint("auth_rls_initplan", "WARN")]
        by = {f["metrics"]["lint"]: f for f in db_probes.advisors_to_findings(lints, "performance", SUPA)}
        self.assertEqual(by["unindexed_foreign_keys"]["category"], "performance")
        self.assertEqual(by["unindexed_foreign_keys"]["evidence_kinds"], ["availability", "integrity"])
        self.assertEqual(by["unused_index"]["evidence_kinds"], ["availability"])
        self.assertEqual(by["extension_in_public"]["category"], "schema_drift")
        self.assertEqual(by["extension_in_public"]["evidence_kinds"], ["change_control"])
        self.assertEqual(by["no_primary_key"]["evidence_kinds"], ["integrity"])
        self.assertEqual(by["multiple_permissive_policies"]["evidence_kinds"], ["availability"])
        self.assertEqual(by["auth_rls_initplan"]["evidence_kinds"], ["access_control"], "auth_* is an access matter")
        self.assertTrue(all(f["probe_id"] == "supabase_advisor_performance" for f in by.values()))

    def test_never_raises_on_junk(self):
        lints = ["text", None, 42, {}, {"name": None, "metadata": None, "level": []},
                {"name": "x", "title": "t", "metadata": {"schema": None, "name": None}}]
        out = db_probes.advisors_to_findings(lints, "security", SUPA)
        self.assertEqual(len(out), 3)
        self.assertEqual(out[0]["title"], "advisor_lint")
        self.assertEqual(out[2]["title"], "t")
        self.assertEqual(db_probes.advisors_to_findings(None, "security", SUPA), [])


# ── execution ──────────────────────────────────────────────────────────────────────────

def make_query_fn(answers=None, raise_for=(), seen=None):
    """query_fn keyed by probe id via the exact SQL text; raises for `raise_for` probe ids."""
    answers = answers or {}

    def query_fn(source, sql):
        pid, dialect = SQL_TO_ID.get(sql, (None, None))
        if seen is not None:
            seen.append((pid, dialect, sql))
        if pid is None:
            raise AssertionError(f"unexpected SQL: {sql[:80]}")
        if pid in raise_for:
            raise RuntimeError(f"connection reset on {pid}")
        val = answers.get(pid, [])
        return val(source) if callable(val) else val
    return query_fn


class TestRunProbe(unittest.TestCase):
    def test_success_fills_probe_remediation(self):
        probe = probe_by_id("rls_disabled_tables")
        res = db_probes.run_probe(probe, PG, query_fn=make_query_fn({"rls_disabled_tables": [
            {"schemaname": "public", "tablename": "users", "rowsecurity": False}]}))
        self.assertTrue(res["ok"])
        self.assertIsNone(res["error"])
        self.assertEqual(res["rows"], 1)
        self.assertEqual(res["findings"][0]["remediation"], probe["remediation"])
        self.assertGreaterEqual(res["duration_ms"], 0)

    def test_query_error_is_captured_not_raised(self):
        res = db_probes.run_probe(probe_by_id("rls_disabled_tables"), PG, query_fn=make_query_fn(raise_for=("rls_disabled_tables",)))
        self.assertFalse(res["ok"])
        self.assertIn("RuntimeError", res["error"])
        self.assertEqual(res["findings"], [])

    def test_missing_dialect_statement_and_bad_render(self):
        res = db_probes.run_probe(probe_by_id("rls_disabled_tables"), {"provider": "mysql"}, query_fn=make_query_fn())
        self.assertFalse(res["ok"])
        self.assertIn("LookupError", res["error"])
        res = db_probes.run_probe(probe_by_id("pii_columns_inventory"), {"provider": "gcp_bigquery", "ref": "p"}, query_fn=make_query_fn())
        self.assertFalse(res["ok"])
        self.assertIn("ValueError", res["error"])
        self.assertIsNone(db_probes.run_probe(None, PG, query_fn=make_query_fn())["probe_id"])

    def test_parse_raising_is_captured(self):
        probe = {**probe_by_id("rls_disabled_tables"), "parse": lambda rows, source, facts: 1 / 0}
        res = db_probes.run_probe(probe, PG, query_fn=make_query_fn())
        self.assertFalse(res["ok"])
        self.assertIn("ZeroDivisionError", res["error"])

    def test_two_argument_parse_is_supported(self):
        probe = {**probe_by_id("rls_disabled_tables"), "parse": lambda rows, source: [{"title": "x", "fingerprint": "y"}]}
        res = db_probes.run_probe(probe, PG, query_fn=make_query_fn())
        self.assertTrue(res["ok"])
        self.assertEqual(res["findings"][0]["remediation"], probe["remediation"])

    def test_advisor_probe_uses_advisors_fn(self):
        advisors = mock.Mock(return_value=[{"name": "rls_disabled_in_public", "level": "ERROR",
                                            "metadata": {"schema": "public", "name": "users"}, "remediation": ""}])
        query_fn = mock.Mock(side_effect=AssertionError("advisor probes run no SQL"))
        res = db_probes.run_probe(probe_by_id("supabase_advisor_security"), SUPA, query_fn=query_fn, advisors_fn=advisors)
        advisors.assert_called_once_with(SUPA, "security")
        self.assertTrue(res["ok"])
        self.assertEqual(res["rows"], 1)
        self.assertEqual(res["findings"][0]["severity"], "high")
        self.assertEqual(res["findings"][0]["remediation"], probe_by_id("supabase_advisor_security")["remediation"])
        query_fn.assert_not_called()


class TestRunAll(unittest.TestCase):
    def test_one_probe_raising_keeps_the_others(self):
        answers = {"audit_trail_presence": [], "table_inventory_facts": [{"tables": 3}]}
        out = db_probes.run_all(PG, query_fn=make_query_fn(answers, raise_for=("rls_disabled_tables",)), advisors_fn=mock.Mock())
        by = {r["probe_id"]: r for r in out["results"]}
        self.assertFalse(by["rls_disabled_tables"]["ok"])
        self.assertIn("RuntimeError", by["rls_disabled_tables"]["error"])
        self.assertTrue(by["audit_trail_presence"]["ok"])
        self.assertEqual(out["stats"]["failed"], 1)
        self.assertEqual(out["stats"]["ok"], out["stats"]["run"] - 1)
        titles = {f["title"] for f in out["findings"]}
        self.assertIn("No audit/event/log tables found in public", titles)
        self.assertIn("No model-call / token-usage log table found", titles)
        self.assertTrue(any(f["probe_id"] == "table_inventory_facts" for f in out["findings"]))
        self.assertEqual(out["facts"]["tables"], 3)
        self.assertEqual(out["score"], db_probes.score(out["findings"]))

    def test_dedup_by_fingerprint_keeps_most_severe(self):
        answers = {"tables_without_primary_key": [{"schemaname": "public", "tablename": "t", "est_rows": 5},
                                                  {"schemaname": "public", "tablename": "t", "est_rows": 50000}],
                   "rls_disabled_tables": [{"schemaname": "public", "tablename": "users", "rowsecurity": False},
                                           {"schemaname": "public", "tablename": "users", "rowsecurity": "f"}]}
        out = db_probes.run_all(PG, query_fn=make_query_fn(answers), tiers=("cheap",))
        nopk = [f for f in out["findings"] if f["probe_id"] == "tables_without_primary_key"]
        self.assertEqual(len(nopk), 1)
        self.assertEqual(nopk[0]["severity"], "high")
        rls = [f for f in out["findings"] if f["probe_id"] == "rls_disabled_tables"]
        self.assertEqual(len(rls), 1)
        self.assertEqual(len({f["fingerprint"] for f in out["findings"]}), len(out["findings"]))

    def test_skips_non_matching_dialects_and_uses_dialect_sql(self):
        seen = []
        out = db_probes.run_all({"provider": "planetscale", "ref": "h"}, query_fn=make_query_fn(seen=seen))
        self.assertEqual([r["probe_id"] for r in out["results"]], [p["id"] for p in probes_for("mysql")])
        self.assertTrue(seen and all(d == "mysql" for _, d, _ in seen))
        self.assertNotIn("rls_disabled_tables", [r["probe_id"] for r in out["results"]])
        self.assertEqual(out["stats"]["failed"], 0)
        mongo = db_probes.run_all({"provider": "mongodb"}, query_fn=mock.Mock(side_effect=AssertionError("no SQL for mongodb")))
        self.assertEqual((mongo["stats"]["run"], mongo["findings"]), (0, []))

    def test_pg_stat_statements_capability_gate(self):
        ran = lambda out: [r["probe_id"] for r in out["results"]]  # noqa: E731
        out = db_probes.run_all(PG, query_fn=make_query_fn(), capabilities={"pg_stat_statements": False})
        self.assertNotIn("slow_query_classes", ran(out))
        self.assertIn({"probe_id": "slow_query_classes", "reason": "capability pg_stat_statements absent"}, out["skipped"])
        self.assertIn("slow_query_classes", ran(db_probes.run_all(PG, query_fn=make_query_fn(), capabilities={"pg_stat_statements": True})))
        self.assertIn("slow_query_classes", ran(db_probes.run_all(PG, query_fn=make_query_fn(), capabilities={})),
                      "unknown capability: try, the probe fails soft on its own")
        src = {**PG, "capabilities": {"pg_stat_statements": False}}
        self.assertNotIn("slow_query_classes", ran(db_probes.run_all(src, query_fn=make_query_fn())))

    def test_requires_fact_gates(self):
        out = db_probes.run_all(SUPA, query_fn=make_query_fn({"schema_migrations_state": [{"n": 0}]}), advisors_fn=lambda s, k: [])
        ran = [r["probe_id"] for r in out["results"]]
        self.assertNotIn("schema_migrations_latest", ran)
        self.assertNotIn("pg_cron_jobs", ran)
        reasons = {s["probe_id"]: s["reason"] for s in out["skipped"]}
        self.assertEqual(reasons["schema_migrations_latest"], "fact has_schema_migrations not established")
        self.assertEqual(reasons["pg_cron_jobs"], "fact has_pg_cron not established")
        self.assertIn("No supabase_migrations.schema_migrations table", {f["title"] for f in out["findings"]})
        answers = {"schema_migrations_state": [{"n": 4}], "schema_migrations_latest": [{"n": 4, "latest": "20260901"}],
                   "extensions_in_public": [{"extname": "pg_cron", "extversion": "1.6", "schemaname": "pg_catalog"}],
                   "pg_cron_jobs": [{"jobid": 1, "jobname": "purge", "schedule": "@daily"}]}
        out = db_probes.run_all(SUPA, query_fn=make_query_fn(answers), advisors_fn=lambda s, k: [])
        ran = [r["probe_id"] for r in out["results"]]
        self.assertIn("schema_migrations_latest", ran)
        self.assertIn("pg_cron_jobs", ran)
        self.assertEqual(out["facts"]["migrations_applied"], 4)
        self.assertEqual(out["facts"]["cron_jobs"], ["purge"])
        self.assertEqual(out["facts"]["has_pg_cron"], True)

    def test_tiers_and_provider_gates(self):
        advisors = mock.Mock(return_value=[])
        out = db_probes.run_all(PG, query_fn=make_query_fn(), tiers=("cheap",), advisors_fn=advisors)
        self.assertTrue(all(probe_by_id(r["probe_id"])["tier"] == "cheap" for r in out["results"]))
        advisors.assert_not_called()
        lint = {"name": "rls_disabled_in_public", "level": "ERROR", "metadata": {"schema": "public", "name": "users"}}
        advisors = mock.Mock(side_effect=lambda s, k: [lint] if k == "security" else [])
        out = db_probes.run_all(SUPA, query_fn=make_query_fn(), tiers=("cheap",), advisors_fn=advisors)
        self.assertEqual(sorted(c.args[1] for c in advisors.call_args_list), ["performance", "security"])
        self.assertIn("supabase_advisor_security", {f["probe_id"] for f in out["findings"]})
        self.assertEqual(out["stats"]["skipped"], len(out["skipped"]))

    def test_never_raises_even_when_query_fn_is_broken(self):
        out = db_probes.run_all(PG, query_fn=lambda s, q: (_ for _ in ()).throw(ConnectionError("down")), advisors_fn=lambda s, k: [])
        self.assertEqual(out["stats"]["ok"], 0)
        self.assertEqual(out["findings"], [])
        self.assertEqual(out["score"], 100.0)


# ── scoring / summary ──────────────────────────────────────────────────────────────────

def _f(sev, direction="undermines", title=None, obj=""):
    return {"severity": sev, "direction": direction, "title": title or f"{sev} thing", "object_name": obj, "object_schema": "public" if obj else ""}


class TestScore(unittest.TestCase):
    def test_arithmetic(self):
        self.assertEqual(db_probes.score([]), 100.0)
        self.assertEqual(db_probes.score(None), 100.0)
        self.assertEqual(db_probes.score([_f("critical")]), 75.0)
        self.assertEqual(db_probes.score([_f("high")]), 90.0)
        self.assertEqual(db_probes.score([_f("medium")]), 97.0)
        self.assertEqual(db_probes.score([_f("low")]), 99.0)
        self.assertEqual(db_probes.score([_f("info")]), 100.0)
        self.assertEqual(db_probes.score([_f("critical"), _f("high"), _f("medium"), _f("low")]), 61.0)

    def test_supports_ignored_and_floor(self):
        self.assertEqual(db_probes.score([_f("critical", "supports"), _f("high", "supports")]), 100.0)
        self.assertEqual(db_probes.score([_f("critical")] * 5), 0.0)
        self.assertEqual(db_probes.score([_f("critical")] * 4 + [_f("low")]), 0.0)
        self.assertEqual(db_probes.score([_f("high")] * 3 + ["junk", None, {"severity": "unknown"}]), 70.0)
        self.assertIsInstance(db_probes.score([_f("low")]), float)

    def test_every_severity_has_a_defined_effect(self):
        for sev in SEVERITIES:
            self.assertLessEqual(db_probes.score([_f(sev)]), 100.0)


class TestSummarize(unittest.TestCase):
    def test_order_and_tags(self):
        text = db_probes.summarize([_f("low", title="l"), _f("critical", title="c", obj="users"),
                                    _f("info", "supports", title="all good"), _f("high", title="h")])
        lines = text.splitlines()
        self.assertEqual(lines[0], "[CRITICAL] - c (public.users)")
        self.assertEqual(lines[1], "[HIGH] - h")
        self.assertEqual(lines[2], "[LOW] - l")
        self.assertEqual(lines[3], "[INFO] + all good")
        more = db_probes.summarize([_f("low", title=f"t{i}") for i in range(10)], limit=3)
        self.assertEqual(len(more.splitlines()), 4)
        self.assertTrue(more.endswith("… and 7 more"))
        self.assertEqual(db_probes.summarize([]), "")


if __name__ == "__main__":
    unittest.main()
