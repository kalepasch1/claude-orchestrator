#!/usr/bin/env python3
"""Tests for db_steering: fingerprint reconciliation (new / updated / resolved), the
resolve-only-when-the-probe-ran rule, the coder brief, swarm remediation dedup and
budget, the repo-vs-live migration drift probe, and the run() budget loop.

Everything is in-memory: `db`, the adapters and the probe catalog are stubs, so no
statement reaches any database and no model is called.
"""
import io
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db_steering  # noqa: E402
import db_steering_contract as C  # noqa: E402


class FakeDB:
    def __init__(self):
        self.tables = {}
        self._ids = 0
        self.bulk_patches = []

    def _match(self, row, params):
        for k, v in params.items():
            if k in ("select", "order", "limit"):
                continue
            if isinstance(v, str) and v.startswith("eq."):
                if str(row.get(k)) != v[3:]:
                    return False
            elif isinstance(v, str) and v.startswith("in.("):
                if str(row.get(k)) not in v[4:-1].split(","):
                    return False
            elif v == "is.null":
                if row.get(k) is not None:
                    return False
        return True

    def select(self, table, params=None):
        params = params or {}
        rows = [dict(r) for r in self.tables.get(table, []) if self._match(r, params)]
        return rows[: int(params["limit"])] if params.get("limit") else rows

    def select_all(self, table, params=None, page_size=None, max_rows=None, order=None):
        return self.select(table, params)

    def insert(self, table, row, upsert=False):
        self._ids += 1
        rec = dict(row)
        rec.setdefault("id", "%s-%d" % (table, self._ids))
        self.tables.setdefault(table, []).append(rec)
        return [dict(rec)]

    def _req(self, method, path, body=None, headers=None, params=None):
        """The bulk paths: POST /rest/v1/<table> with an array body echoes the rows;
        PATCH with params id=in.(...) applies one patch to many rows."""
        assert method in ("POST", "PATCH") and path.startswith("/rest/v1/")
        table = path.split("/rest/v1/", 1)[1]
        if self.bulk_fails:
            raise RuntimeError("bulk refused")
        if method == "PATCH":
            self.bulk_patches.append((table, dict(params or {}), dict(body or {})))
            ids = set((params or {}).get("id", "in.()")[4:-1].split(","))
            for r in self.tables.get(table, []):
                if str(r.get("id")) in ids:
                    r.update(body or {})
            return []
        return [self.insert(table, r)[0] for r in (body or [])]

    bulk_fails = False
    bulk_patches = None

    def upsert(self, table, row):
        key = "project" if table == "db_steering_briefs" else "id"
        for r in self.tables.get(table, []):
            if r.get(key) == row.get(key):
                r.update(row)
                return [dict(r)]
        return self.insert(table, row)

    def update(self, table, match, patch):
        for r in self.tables.get(table, []):
            if all(str(r.get(k)) == str(v) for k, v in match.items()):
                r.update(patch)

    def delete(self, table, match):
        self.tables[table] = [r for r in self.tables.get(table, [])
                              if not all(str(r.get(k)) == str(v) for k, v in match.items())]


def F(probe, obj, sev="medium", cat="security", kinds=("access_control",), direction="undermines", **kw):
    return C.make_finding(probe, cat, sev, "%s on %s" % (probe, obj), object_schema="public", object_name=obj,
                          evidence_kinds=kinds, direction=direction, remediation="fix %s" % probe, **kw)


class FakeProbes:
    """A probe catalog stub whose findings the test sets per source id."""

    def __init__(self):
        self.findings = {}
        self.results = {}
        self.facts = {}
        self.calls = []

    def run_all(self, source, query_fn=None, tiers=(), advisors_fn=None, capabilities=None):
        self.calls.append((source["id"], tuple(tiers)))
        return {"findings": list(self.findings.get(source["id"], [])),
                "results": list(self.results.get(source["id"], [{"probe_id": "rls_disabled_tables", "ok": True, "duration_ms": 3},
                                                                {"probe_id": "missing_audit_columns", "ok": True, "duration_ms": 2}])),
                "facts": dict(self.facts.get(source["id"], {}))}

    def score(self, findings):
        return 100.0 - 10 * sum(1 for f in findings if f["severity"] == "high")

    def summarize(self, findings, limit=8):
        return "; ".join(f["title"] for f in findings[:limit])


class FakeAdapters:
    def capabilities(self, source):
        return {"dialect": "postgres", "pg_stat_statements": True, "advisors": True}

    def query(self, source, sql, timeout=None):
        raise AssertionError("no statement may reach a database in these tests")

    def supabase_advisors(self, source, kind):
        return []


SRC = {"id": "src-1", "project": "apparently-law", "label": "apparently-law", "provider": "supabase",
       "dialect": "postgres", "ref": "cwmeqq", "config": {}, "capabilities": {}, "enabled": True, "status": "active"}


class Base(unittest.TestCase):
    def setUp(self):
        self.fake = FakeDB()
        self.fake.tables["projects"] = [{"id": "p1", "name": "apparently-law", "repo_path": "/nonexistent/apparently-law"}]
        for name in ("select", "select_all", "insert", "upsert", "update", "delete", "_req"):
            p = patch.object(db_steering.db, name, getattr(self.fake, name))
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(db_steering.db_registry, "record_scan", lambda *a, **k: None)
        p.start()
        self.addCleanup(p.stop)
        # Most tests want every re-sighting written so they can observe it; the throttle
        # has its own test below.
        p = patch.object(db_steering, "FINDING_TOUCH_S", 0)
        p.start()
        self.addCleanup(p.stop)
        self.probes = FakeProbes()
        self.adapters = FakeAdapters()
        db_steering._brief_cache.clear()

    def scan(self, source=SRC, **kw):
        return db_steering.scan_source(dict(source), adapters=self.adapters, probes=self.probes, **kw)


class ReconcileTest(Base):
    def test_new_then_repeat_then_resolve(self):
        self.probes.findings["src-1"] = [F("rls_disabled_tables", "matters", "high"), F("missing_audit_columns", "notes", "medium", "audit", ("audit_trail",))]
        r1 = self.scan()
        self.assertTrue(r1["ok"])
        self.assertEqual(len(r1["delta"]["new"]), 2)
        self.assertEqual(len(self.fake.tables["db_findings"]), 2)
        # same findings again: no new rows; the touch is ONE batched PATCH, occurrences
        # only counts content changes
        r2 = self.scan()
        self.assertEqual(r2["delta"]["new"], [])
        self.assertEqual(r2["delta"]["updated"], 2)
        self.assertEqual(len(self.fake.bulk_patches), 1, "two stale rows -> one PATCH id=in.(...)")
        self.assertEqual({r["occurrences"] for r in self.fake.tables["db_findings"]}, {1})
        self.assertTrue(all(r["last_seen_at"] for r in self.fake.tables["db_findings"]))
        # one disappears while its probe ran OK -> resolved; the other stays open
        self.probes.findings["src-1"] = [F("rls_disabled_tables", "matters", "high")]
        r3 = self.scan()
        self.assertEqual([r["object_name"] for r in r3["delta"]["resolved"]], ["notes"])
        by_obj = {r["object_name"]: r for r in self.fake.tables["db_findings"]}
        self.assertEqual(by_obj["notes"]["status"], "resolved")
        self.assertIsNotNone(by_obj["notes"]["resolved_at"])
        self.assertEqual(by_obj["matters"]["status"], "open")

    def test_finding_is_not_resolved_when_its_probe_failed(self):
        self.probes.findings["src-1"] = [F("missing_audit_columns", "notes", "medium", "audit", ("audit_trail",))]
        self.scan()
        self.probes.findings["src-1"] = []
        self.probes.results["src-1"] = [{"probe_id": "missing_audit_columns", "ok": False, "error": "timeout", "duration_ms": 20000},
                                        {"probe_id": "rls_disabled_tables", "ok": True, "duration_ms": 1}]
        r = self.scan()
        self.assertEqual(r["delta"]["resolved"], [], "a probe that errored says nothing about its findings")
        self.assertEqual(self.fake.tables["db_findings"][0]["status"], "open")

    def test_severity_change_updates_the_same_row(self):
        self.probes.findings["src-1"] = [F("sequence_headroom", "orders_id_seq", "medium", "availability", ("availability",))]
        self.scan()
        self.probes.findings["src-1"] = [F("sequence_headroom", "orders_id_seq", "critical", "availability", ("availability",))]
        r = self.scan()
        self.assertEqual(r["delta"]["new"], [])
        self.assertEqual(len(self.fake.tables["db_findings"]), 1)
        self.assertEqual(self.fake.tables["db_findings"][0]["severity"], "critical")

    def test_snapshot_written_with_counts_and_score(self):
        self.probes.findings["src-1"] = [F("rls_disabled_tables", "a", "high"), F("audit_trail_presence", "b", "info", "audit", ("audit_trail",), direction="supports")]
        self.scan()
        snap = self.fake.tables["db_posture_snapshots"][0]
        self.assertEqual(snap["counts"]["by_severity"], {"high": 1})
        self.assertEqual(snap["counts"]["supports"], 1)
        self.assertEqual(snap["score"], 90.0)
        self.assertEqual(snap["probe_stats"]["probes_ok"], 2)

    def test_dry_run_writes_nothing(self):
        self.probes.findings["src-1"] = [F("rls_disabled_tables", "a", "high")]
        r = self.scan(dry_run=True)
        self.assertEqual(len(r["findings"]), 1)
        self.assertNotIn("db_findings", self.fake.tables)
        self.assertNotIn("db_posture_snapshots", self.fake.tables)

    def test_unchanged_findings_are_not_rewritten_every_cycle(self):
        self.probes.findings["src-1"] = [F("rls_disabled_tables", "matters", "high")]
        self.scan()
        with patch.object(db_steering, "FINDING_TOUCH_S", 3600):
            r = self.scan()
            self.assertEqual(r["delta"]["updated"], 0, "an identical finding seen a minute later costs no write")
            self.assertEqual(self.fake.tables["db_findings"][0]["occurrences"], 1)
            # a real change still lands immediately
            self.probes.findings["src-1"] = [F("rls_disabled_tables", "matters", "critical")]
            r = self.scan()
            self.assertEqual(r["delta"]["updated"], 1)
            self.assertEqual(self.fake.tables["db_findings"][0]["occurrences"], 2, "a content change counts")
            self.assertEqual(self.fake.bulk_patches, [], "content changes are per-row, not batched")

            self.assertEqual(self.fake.tables["db_findings"][0]["severity"], "critical")
            # and a stale last_seen is refreshed even without a change
            self.fake.tables["db_findings"][0]["last_seen_at"] = "2026-01-01T00:00:00+00:00"
            r = self.scan()
            self.assertEqual(r["delta"]["updated"], 1)

    def test_resolved_finding_that_recurs_is_reopened_not_reinserted(self):
        """(source_id, fingerprint) is unique: a recurrence must reopen the resolved row."""
        self.probes.findings["src-1"] = [F("rls_disabled_tables", "matters", "high")]
        self.scan()
        self.probes.findings["src-1"] = []
        r = self.scan()
        self.assertEqual(len(r["delta"]["resolved"]), 1)
        self.fake.tables["db_findings"][0]["task_slug"] = "swarm-db-old"
        self.probes.findings["src-1"] = [F("rls_disabled_tables", "matters", "critical")]
        r = self.scan()
        rows = self.fake.tables["db_findings"]
        self.assertEqual(len(rows), 1, "no second row for the same fingerprint")
        self.assertEqual(rows[0]["status"], "open")
        self.assertIsNone(rows[0]["resolved_at"])
        self.assertIsNone(rows[0]["task_slug"], "a recurrence is re-filed")
        self.assertEqual(rows[0]["severity"], "critical")
        self.assertEqual(rows[0]["occurrences"], 2)
        self.assertEqual([x["id"] for x in r["delta"]["reopened"]], [rows[0]["id"]])
        self.assertEqual([x["id"] for x in r["delta"]["new"]], [rows[0]["id"]], "steered like a new gap")
        # and it is not resolved again in the same cycle
        self.assertEqual(r["delta"]["resolved"], [])

    def test_bulk_touch_falls_back_per_row(self):
        self.probes.findings["src-1"] = [F("rls_disabled_tables", "matters", "high")]
        self.scan()
        self.fake.bulk_fails = True
        updates = []
        with patch.object(db_steering.db, "update", lambda t, m, p: updates.append((t, m, p))):
            r = self.scan()
        self.assertEqual(r["delta"]["updated"], 1)
        self.assertEqual(len(updates), 1)

    def test_bulk_insert_falls_back_per_row(self):
        self.fake.bulk_fails = True
        self.probes.findings["src-1"] = [F("rls_disabled_tables", "a", "high"), F("rls_disabled_tables", "b", "high")]
        r = self.scan()
        self.assertEqual(len(r["delta"]["new"]), 2)
        self.assertEqual(len(self.fake.tables["db_findings"]), 2)
        self.assertTrue(all(row.get("id") for row in r["delta"]["new"]))

    def test_probe_catalog_crash_is_contained(self):
        class Boom(FakeProbes):
            def run_all(self, *a, **k):
                raise RuntimeError("catalog exploded")
        r = db_steering.scan_source(dict(SRC), adapters=self.adapters, probes=Boom())
        self.assertFalse(r["ok"])
        self.assertIn("catalog exploded", r["error"])


class TierScheduleTest(unittest.TestCase):
    def test_due_tiers_follow_intervals(self):
        now = time.time()
        fresh = {"capabilities": {"tiers": {"medium": now - 60, "heavy": now - 60}}}
        self.assertEqual(db_steering._due_tiers(fresh, now), ("cheap",))
        stale_medium = {"capabilities": {"tiers": {"medium": now - 4000, "heavy": now - 60}}}
        self.assertEqual(db_steering._due_tiers(stale_medium, now), ("cheap", "medium"))
        self.assertEqual(db_steering._due_tiers({"capabilities": {}}, now), ("cheap", "medium", "heavy"))


class BriefTest(Base):
    def test_brief_lists_gaps_by_severity_with_objects_and_remediation(self):
        self.probes.findings["src-1"] = [
            F("rls_disabled_tables", "matters", "high"), F("rls_disabled_tables", "engagements", "high"),
            F("missing_audit_columns", "notes", "medium", "audit", ("audit_trail",)),
            F("uuid_text_keys", "tags", "low", "integrity", ("integrity",)),
            F("audit_trail_presence", "x", "info", "audit", ("audit_trail",), direction="supports"),
        ]
        self.scan()
        text = db_steering.refresh_brief("apparently-law", signals=["records_integrity: add created_at to notes"])
        self.assertIn("Database steering", text)
        self.assertIn("2 high, 1 medium, 1 low", text)
        self.assertIn("records_integrity: add created_at", text)
        self.assertIn("public.engagements, public.matters", text)
        self.assertIn("fix rls_disabled_tables", text)
        self.assertNotIn("tags", text, "low findings do not make the brief")
        self.assertNotIn("audit_trail_presence", text, "positives do not make the brief")
        self.assertLessEqual(len(text), db_steering.BRIEF_MAX_CHARS + 2)
        row = self.fake.tables["db_steering_briefs"][0]
        self.assertEqual(row["project"], "apparently-law")
        self.assertEqual(row["open_counts"]["high"], 2)
        # read side, cached
        self.assertEqual(db_steering.steering_brief("apparently-law"), text)

    def test_brief_removed_when_no_gaps_remain(self):
        self.probes.findings["src-1"] = [F("rls_disabled_tables", "matters", "high")]
        self.scan()
        db_steering.refresh_brief("apparently-law")
        self.assertEqual(len(self.fake.tables["db_steering_briefs"]), 1)
        self.probes.findings["src-1"] = []
        self.scan()
        self.assertEqual(db_steering.refresh_brief("apparently-law"), "")
        self.assertEqual(self.fake.tables["db_steering_briefs"], [])

    def test_brief_is_capped(self):
        self.probes.findings["src-1"] = [F("rls_disabled_tables", "table_%03d" % i, "high") for i in range(80)] + \
                                        [F("probe_%d" % i, "t", "medium") for i in range(60)]
        self.scan()
        text = db_steering.refresh_brief("apparently-law")
        self.assertLessEqual(len(text), db_steering.BRIEF_MAX_CHARS + 2)
        self.assertTrue(text.rstrip().endswith("…"))

    def test_steering_brief_read_is_fail_soft(self):
        with patch.object(db_steering.db, "select", side_effect=RuntimeError("down")):
            self.assertEqual(db_steering.steering_brief("nope"), "")
        self.assertEqual(db_steering.steering_brief(""), "")


class RemediationTest(Base):
    def setUp(self):
        super().setUp()
        self.filed = []

        class FakeSwarm:
            def enqueue(inner, record):
                self.filed.append(record)
                return "filed"
        self.swarm = FakeSwarm()
        sys.modules["swarm_enqueue"] = self.swarm
        self.addCleanup(lambda: sys.modules.pop("swarm_enqueue", None))

    def test_one_task_per_probe_for_material_new_gaps(self):
        new = [dict(F("rls_disabled_tables", "matters", "high"), id="f1"),
               dict(F("rls_disabled_tables", "engagements", "critical"), id="f2"),
               dict(F("missing_audit_columns", "notes", "medium", "audit", ("audit_trail",)), id="f3"),
               dict(F("pii_exposed_tables", "clients", "high", "privacy", ("data_minimization",)), id="f4"),
               dict(F("audit_trail_presence", "x", "critical", "audit", ("audit_trail",), direction="supports"), id="f5")]
        self.fake.tables["db_findings"] = [dict(r) for r in new]
        slugs = db_steering.file_remediation(dict(SRC), new)
        self.assertEqual(sorted(slugs), ["swarm-db-pii-exposed-tables-apparently-law", "swarm-db-rls-disabled-tables-apparently-law"])
        rec = next(r for r in self.filed if "rls" in r["slug"])
        self.assertEqual(rec["kind"], "bugfix")
        self.assertEqual(rec["project_id"], "p1")
        self.assertIn("public.engagements", rec["prompt"])
        self.assertIn("Never enable RLS without policies", rec["prompt"])
        self.assertTrue(all(r["slug"].startswith("swarm-") for r in self.filed), "slugs must keep the swarm prefix or leave the self-work tier")
        by_id = {r["id"]: r for r in self.fake.tables["db_findings"]}
        self.assertEqual(by_id["f1"]["task_slug"], "swarm-db-rls-disabled-tables-apparently-law")
        self.assertNotIn("task_slug", by_id["f3"])

    def test_unfiled_open_findings_are_re_offered_until_filed(self):
        """A finding first written by a manual scan (or refused by backpressure) has no
        task_slug; the loop must keep offering it, and stop once a slug is recorded."""
        self.fake.tables["db_findings"] = [
            dict(F("rls_disabled_tables", "matters", "high"), id="f1", project="apparently-law", status="open"),
            dict(F("rls_disabled_tables", "old", "high"), id="f2", project="apparently-law", status="open",
                 task_slug="swarm-db-rls-disabled-tables-apparently-law"),
            dict(F("missing_audit_columns", "notes", "medium", "audit", ("audit_trail",)), id="f3",
                 project="apparently-law", status="open"),
            dict(F("pii_exposed_tables", "clients", "high", "privacy", ("data_minimization",)), id="f4",
                 project="apparently-law", status="resolved"),
        ]
        rows = db_steering._unfiled_open("apparently-law")
        self.assertEqual([r["id"] for r in rows], ["f1"], "unfiled + open + material only")
        self.assertEqual(db_steering._unfiled_open(""), [])
        with patch.object(db_steering.db, "select", side_effect=RuntimeError("down")):
            self.assertEqual(db_steering._unfiled_open("apparently-law"), [])
        slugs = db_steering.file_remediation(dict(SRC), rows)
        self.assertEqual(slugs, ["swarm-db-rls-disabled-tables-apparently-law"])
        self.assertEqual(db_steering._unfiled_open("apparently-law"), [], "filed once; not offered again")

    def test_budget_and_self_and_unknown_project(self):
        new = [dict(F("p%d" % i, "t", "high"), id="f%d" % i) for i in range(5)]
        self.assertEqual(len(db_steering.file_remediation(dict(SRC), new, budget=2)), 2)
        self.filed.clear()
        self.assertEqual(db_steering.file_remediation(dict(SRC, config={"self": True}), new), [])
        self.assertEqual(db_steering.file_remediation(dict(SRC, project="not-a-fleet-project"), new), [])
        self.assertEqual(self.filed, [])

    def test_kill_switch(self):
        with patch.object(db_steering, "REMEDIATION_ENABLED", False):
            self.assertEqual(db_steering.file_remediation(dict(SRC), [dict(F("p", "t", "critical"), id="f")]), [])


class DriftProbeTest(Base):
    def _repo_with(self, versions):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "supabase", "migrations"))
        for v in versions:
            open(os.path.join(d, "supabase", "migrations", "%s_x.sql" % v), "w").close()
        self.fake.tables["projects"] = [{"id": "p1", "name": "apparently-law", "repo_path": d}]
        return d

    def test_repo_ahead_live_ahead_and_match(self):
        self._repo_with(["20260901000000", "20260910000000", "20260912000000"])
        out = db_steering._repo_migration_drift(dict(SRC), {"schema_migrations_latest": "20260901000000", "schema_migrations_count": 1})
        self.assertEqual(out[0]["probe_id"], "schema_drift_repo_ahead")
        self.assertEqual(out[0]["metrics"]["pending"], 2)
        out = db_steering._repo_migration_drift(dict(SRC), {"schema_migrations_latest": "20260915000000"})
        self.assertEqual(out[0]["probe_id"], "schema_drift_live_ahead")
        self.assertEqual(out[0]["severity"], "high")
        out = db_steering._repo_migration_drift(dict(SRC), {"schema_migrations_latest": "20260912000000", "schema_migrations_count": 3})
        self.assertEqual(out[0]["probe_id"], "schema_matches_repo")
        self.assertEqual(out[0]["direction"], "supports")

    def test_no_repo_or_no_facts_means_no_finding(self):
        self.assertEqual(db_steering._repo_migration_drift(dict(SRC), {}), [])
        self.assertEqual(db_steering._repo_migration_drift(dict(SRC), {"schema_migrations_latest": "1"}), [])
        self.assertEqual(db_steering._repo_migration_drift(dict(SRC, project=None), {"schema_migrations_latest": "1"}), [])


class RunLoopTest(Base):
    def setUp(self):
        super().setUp()
        for name, val in (("discover", lambda force=False: {"discovered": 0}), ("sync_security_posture", lambda: 0)):
            p = patch.object(db_steering.db_registry, name, val)
            p.start()
            self.addCleanup(p.stop)
        self.memo_calls = []

        class FakeMemo:
            def attach_evidence(inner, project, rows):
                self.memo_calls.append(("attach", project, len(rows)))
                return {}

            def rebuild_if_changed(inner, project, max_memos=None):
                self.memo_calls.append(("rebuild", project))
                return {"drafted": 1, "deterministic": 0}

            def steering_signals(inner, project):
                return ["records_integrity: add created_at"]
        sys.modules["db_memo"] = FakeMemo()
        self.addCleanup(lambda: sys.modules.pop("db_memo", None))
        sys.modules["db_adapters"] = self.adapters
        sys.modules["db_probes"] = self.probes
        self.addCleanup(lambda: sys.modules.pop("db_adapters", None))
        self.addCleanup(lambda: sys.modules.pop("db_probes", None))

    def test_run_scans_stalest_first_within_budget_and_steers(self):
        s_old = dict(SRC, id="src-1", last_scan_at="2026-09-01T00:00:00+00:00")
        s_new = dict(SRC, id="src-2", ref="other", label="other", last_scan_at="2026-09-12T00:00:00+00:00")
        self.probes.findings["src-1"] = [F("rls_disabled_tables", "matters", "high")]
        buf = io.StringIO()
        with redirect_stdout(buf):
            out = db_steering.run(sources=[s_new, s_old], budget_s=999)
        self.assertEqual([c[0] for c in self.probes.calls], ["src-1", "src-2"], "stalest source scanned first")
        self.assertEqual(out["scanned"], 2)
        self.assertEqual(out["new"], 1)
        self.assertEqual(out["memos"], 1)
        self.assertIn(("rebuild", "apparently-law"), self.memo_calls)
        self.assertEqual(len(self.fake.tables["loops"]), 1, "ensures its loop row")
        self.assertEqual(self.fake.tables["loops"][0]["type"], "db_steering")
        brief = self.fake.tables["db_steering_briefs"][0]["brief"]
        self.assertIn("records_integrity: add created_at", brief)
        self.assertIn("public.matters", brief)

    def test_budget_exhaustion_skips_rather_than_wedges(self):
        srcs = [dict(SRC, id="src-%d" % i, ref="r%d" % i) for i in range(3)]
        with patch.object(db_steering.time, "time", side_effect=[1000.0] + [1000.0 + 500 * i for i in range(1, 60)]):
            out = db_steering.run(sources=srcs, budget_s=1)
        self.assertGreaterEqual(out["skipped_budget"], 1)
        self.assertEqual(out["scanned"] + out["skipped_budget"], 3)

    def test_memo_phase_budget_defers_drafting_but_never_the_brief(self):
        s_old = dict(SRC, id="src-1", last_scan_at="2026-09-01T00:00:00+00:00")
        self.probes.findings["src-1"] = [F("rls_disabled_tables", "matters", "high")]
        with patch.object(db_steering, "MEMO_BUDGET_S", -1.0):
            with redirect_stdout(io.StringIO()):
                out = db_steering.run(sources=[s_old], budget_s=999)
        self.assertEqual(out["memos"], 0)
        self.assertEqual(out.get("memos_deferred"), 1)
        self.assertNotIn(("rebuild", "apparently-law"), self.memo_calls)
        self.assertIn(("attach", "apparently-law", 1), self.memo_calls, "evidence still attached")
        brief = self.fake.tables["db_steering_briefs"][0]["brief"]
        self.assertIn("records_integrity: add created_at", brief, "signals and brief never wait on a model")

    def test_ensure_loop_row_is_idempotent(self):
        db_steering.ensure_loop_row()
        db_steering.ensure_loop_row()
        self.assertEqual(len(self.fake.tables["loops"]), 1)


class IncrementalScanTest(Base):
    """Schema-signature gating: an unchanged schema skips the structural probes, keeps
    their open findings as carried posture, and never resolves them by absence."""

    class SigProbes(FakeProbes):
        PROBES = [{"id": "rls_disabled_tables"}, {"id": "slow_query_classes"}]

        def __init__(self, sig="sig-1"):
            super().__init__()
            self.sig = sig
            self.kw = []

        def schema_signature(self, source, query_fn=None):
            return self.sig

        def probe_depends_on(self, probe):
            return "data" if probe["id"] == "slow_query_classes" else "schema"

        def run_all(self, source, query_fn=None, tiers=(), advisors_fn=None, capabilities=None, **kw):
            self.kw.append(kw)
            skip = set(kw.get("skip_probe_ids") or ())
            res = super().run_all(source, query_fn, tiers, advisors_fn, capabilities)
            res["results"] = [r for r in res["results"] if r["probe_id"] not in skip]
            res["findings"] = [f for f in res["findings"] if f["probe_id"] not in skip]
            res["stats"] = {"round_trips": 2}
            return res

    def setUp(self):
        super().setUp()
        self.registry_calls = []
        p = patch.object(db_steering.db_registry, "record_scan",
                         lambda *a, **k: self.registry_calls.append(("record_scan", k)))
        p.start()
        self.addCleanup(p.stop)

    def _source(self, caps=None):
        return dict(SRC, capabilities=dict(caps or {}))

    def test_first_scan_is_full_and_records_the_signature(self):
        probes = self.SigProbes()
        probes.findings["src-1"] = [F("rls_disabled_tables", "matters", "high")]
        with redirect_stdout(io.StringIO()):
            r = db_steering.scan_source(self._source(), adapters=self.adapters, probes=probes)
        self.assertEqual(r["mode"], "full")
        self.assertNotIn("skip_probe_ids", probes.kw[0])
        rec = [c for c in self.registry_calls if c[0] == "record_scan"][-1]
        self.assertEqual(rec[1]["capabilities"]["schema_signature"], "sig-1")
        self.assertIn("schema_full_ok_at", rec[1]["capabilities"])

    def test_unchanged_signature_skips_schema_probes_and_carries_findings(self):
        probes = self.SigProbes()
        probes.findings["src-1"] = [F("rls_disabled_tables", "matters", "high"),
                                    F("slow_query_classes", "q1", "high", "performance", ("availability",))]
        probes.results["src-1"] = [{"probe_id": "rls_disabled_tables", "ok": True, "duration_ms": 1},
                                   {"probe_id": "slow_query_classes", "ok": True, "duration_ms": 1}]
        with redirect_stdout(io.StringIO()):
            first = db_steering.scan_source(self._source(), adapters=self.adapters, probes=probes)
        self.assertEqual(len(first["delta"]["new"]), 2)
        caps = [c for c in self.registry_calls if c[0] == "record_scan"][-1][1]["capabilities"]
        # second cycle: same signature, the structural finding vanishes from the (skipped) probe
        probes.findings["src-1"] = [F("slow_query_classes", "q1", "high", "performance", ("availability",))]
        with redirect_stdout(io.StringIO()):
            second = db_steering.scan_source(self._source(caps), adapters=self.adapters, probes=probes)
        self.assertEqual(second["mode"], "incremental")
        self.assertEqual(probes.kw[-1]["skip_probe_ids"], ["rls_disabled_tables"])
        self.assertEqual(second["delta"]["resolved"], [], "a skipped probe resolves nothing")
        self.assertEqual([r["probe_id"] for r in second["delta"]["carried"]], ["rls_disabled_tables"])
        self.assertEqual(len(second["delta"]["all"]), 2, "posture = seen + carried")
        self.assertEqual(second["snapshot"]["counts"]["by_severity"].get("high"), 2)
        self.assertEqual(second["snapshot"]["probe_stats"]["mode"], "incremental")

    def test_changed_signature_or_stale_full_run_forces_full(self):
        probes = self.SigProbes()
        with redirect_stdout(io.StringIO()):
            db_steering.scan_source(self._source(), adapters=self.adapters, probes=probes)
        caps = [c for c in self.registry_calls if c[0] == "record_scan"][-1][1]["capabilities"]
        probes.sig = "sig-2"
        with redirect_stdout(io.StringIO()):
            r = db_steering.scan_source(self._source(caps), adapters=self.adapters, probes=probes)
        self.assertEqual(r["mode"], "full")
        probes.sig = "sig-1"
        stale = dict(caps, schema_full_ok_at=time.time() - db_steering.SCHEMA_FULL_MAX_AGE_S - 1)
        with redirect_stdout(io.StringIO()):
            r = db_steering.scan_source(self._source(stale), adapters=self.adapters, probes=probes)
        self.assertEqual(r["mode"], "full")
        with redirect_stdout(io.StringIO()):
            r = db_steering.scan_source(self._source(caps), adapters=self.adapters, probes=probes, force_full=True)
        self.assertEqual(r["mode"], "full")

    def test_probes_without_signature_support_stay_full(self):
        with redirect_stdout(io.StringIO()):
            r = db_steering.scan_source(self._source(), adapters=self.adapters, probes=self.probes)
        self.assertEqual(r["mode"], "full")

    def test_snapshot_written_on_change_else_hourly(self):
        caps = {}
        rows = [F("rls_disabled_tables", "matters", "high")]
        results = [{"probe_id": "rls_disabled_tables", "ok": True, "duration_ms": 1}]
        with redirect_stdout(io.StringIO()):
            a = db_steering.write_snapshot(dict(SRC), rows, results, {}, self.probes, caps=caps)
            b = db_steering.write_snapshot(dict(SRC), rows, results, {}, self.probes, caps=caps)
            c = db_steering.write_snapshot(dict(SRC), rows + [F("rls_disabled_tables", "notes", "high")], results, {}, self.probes, caps=caps)
            caps["snapshot"]["at"] = time.time() - db_steering.SNAPSHOT_MIN_INTERVAL_S - 1
            d = db_steering.write_snapshot(dict(SRC), rows + [F("rls_disabled_tables", "notes", "high")], results, {}, self.probes, caps=caps)
        self.assertEqual([a["written"], b["written"], c["written"], d["written"]], [True, False, True, True])
        self.assertEqual(len(self.fake.tables["db_posture_snapshots"]), 3)


class FocusBriefTest(Base):
    BRIEF = ("## Database steering (live findings for apparently-law)\n"
             "Open gaps: 2 high\n"
             "- records_integrity: add created_at\n"
             "- [HIGH] rls disabled tables (2 objects): public.matters, public.notes -> enable RLS\n"
             "- [HIGH] unindexed foreign keys (1 objects): public.engagements -> add index\n"
             "Rule: never enable RLS without policies.\n\n")

    def test_lines_naming_task_objects_come_first(self):
        out = db_steering.focus_brief(self.BRIEF, "Add a status column to the engagements table and backfill")
        lines = out.split("\n")
        self.assertEqual(lines[1], "Touched by this task (fix these in the same change):")
        self.assertIn("public.engagements", lines[2])
        self.assertIn("Project-wide:", lines)
        self.assertTrue(out.endswith("\n\n"))
        self.assertLessEqual(len(out), db_steering.BRIEF_MAX_CHARS + 2)

    def test_no_match_returns_brief_unchanged(self):
        self.assertEqual(db_steering.focus_brief(self.BRIEF, "fix the login page copy"), self.BRIEF)
        self.assertEqual(db_steering.focus_brief(self.BRIEF, ""), self.BRIEF)
        self.assertEqual(db_steering.focus_brief("", "matters"), "")

    def test_steering_brief_applies_focus_from_cache(self):
        self.fake.tables["db_steering_briefs"] = [{"project": "apparently-law", "brief": self.BRIEF}]
        plain = db_steering.steering_brief("apparently-law")
        focused = db_steering.steering_brief("apparently-law", context="touch public.matters")
        self.assertEqual(plain, self.BRIEF)
        self.assertIn("Touched by this task", focused)


class LoopPlumbingTest(Base):
    def test_loop_row_cadence_follows_the_knob(self):
        self.fake.tables["loops"] = [{"id": "L1", "type": "db_steering", "enabled": True, "cadence_seconds": 600}]
        with patch.object(db_steering, "LOOP_CADENCE_S", 120):
            row = db_steering.ensure_loop_row()
        self.assertEqual(row["cadence_seconds"], 120)
        self.assertEqual(self.fake.tables["loops"][0]["cadence_seconds"], 120)

    def test_scan_many_keeps_input_order_and_budget(self):
        srcs = [dict(SRC, id="src-%d" % i, ref="r%d" % i) for i in range(5)]
        out = {"skipped_budget": 0}
        with patch.object(db_steering, "SOURCE_PARALLEL", 2), \
                patch.object(db_steering, "scan_source", lambda s, dry_run=False: {"ok": True, "id": s["id"]}):
            got = list(db_steering._scan_many(srcs, time.time(), 999, out))
        self.assertEqual([r["id"] for _, r in got], ["src-0", "src-1", "src-2", "src-3", "src-4"])
        self.assertEqual(out["skipped_budget"], 0)
        out = {"skipped_budget": 0}
        with patch.object(db_steering, "SOURCE_PARALLEL", 2), \
                patch.object(db_steering, "scan_source", lambda s, dry_run=False: {"ok": True, "id": s["id"]}):
            got = list(db_steering._scan_many(srcs, time.time() - 1000, 1, out))
        self.assertEqual(got, [])
        self.assertEqual(out["skipped_budget"], 5)

    def test_remediation_records_bypass_backpressure(self):
        filed = []

        class FakeSwarm:
            def enqueue(inner, record):
                filed.append(record)
                return "filed"
        sys.modules["swarm_enqueue"] = FakeSwarm()
        self.addCleanup(lambda: sys.modules.pop("swarm_enqueue", None))
        new = [dict(F("rls_disabled_tables", "matters", "high"), id="f1")]
        self.fake.tables["db_findings"] = [dict(r) for r in new]
        db_steering.file_remediation(dict(SRC), new)
        self.assertTrue(filed and filed[0].get("bypass_backpressure") is True)



if __name__ == "__main__":
    unittest.main()
