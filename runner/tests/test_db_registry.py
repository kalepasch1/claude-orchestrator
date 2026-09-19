#!/usr/bin/env python3
"""Tests for db_registry: discovery through the Management API, the credential-reference
door, operator choices surviving re-discovery, and the security_posture backfill.

No network, no real control plane: `db` is replaced by an in-memory fake and the
Management API by a canned project list.
"""
import io
import json
import os
import sys
import unittest
import urllib.error
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db_registry  # noqa: E402


class FakeDB:
    """Just enough PostgREST semantics for the registry: eq. filters, insert, update, delete."""

    def __init__(self):
        self.tables = {"db_sources": [], "projects": [], "security_posture": []}
        self._ids = 0

    def _match(self, row, params):
        for k, v in params.items():
            if k in ("select", "order", "limit"):
                continue
            if isinstance(v, str) and v.startswith("eq."):
                # PostgREST spells booleans `true`/`false`; Python str() gives `True`.
                if str(row.get(k)).lower() != v[3:].lower():
                    return False
            elif isinstance(v, str) and v.startswith("in.("):
                if str(row.get(k)) not in v[4:-1].split(","):
                    return False
        return True

    def select(self, table, params=None):
        params = params or {}
        rows = [dict(r) for r in self.tables.get(table, []) if self._match(r, params)]
        return rows[: int(params["limit"])] if params.get("limit") else rows

    def insert(self, table, row, upsert=False):
        self._ids += 1
        rec = dict(row)
        rec.setdefault("id", "id-%d" % self._ids)
        self.tables.setdefault(table, []).append(rec)
        return [dict(rec)]

    def update(self, table, match, patch):
        n = 0
        for r in self.tables.get(table, []):
            if all(str(r.get(k)) == str(v) for k, v in match.items()):
                r.update(patch)
                n += 1
        return n

    def delete(self, table, match):
        before = len(self.tables.get(table, []))
        self.tables[table] = [r for r in self.tables.get(table, [])
                              if not all(str(r.get(k)) == str(v) for k, v in match.items())]
        return before - len(self.tables[table])


PROJECTS = [
    {"id": "cwmeqqtvmjbapjsefbfq", "name": "apparently-law", "region": "us-east-1", "status": "ACTIVE_HEALTHY", "organization_id": "org1"},
    {"id": "oosolxvlfyifkhjohdzq", "name": "apparently", "region": "us-east-1", "status": "ACTIVE_HEALTHY", "organization_id": "org1"},
    {"id": "eatfwdzfurujcuwlhdgj", "name": "claude-orchestrator", "region": "us-east-1", "status": "ACTIVE_HEALTHY", "organization_id": "org1"},
    {"id": "hxldrekyerhmfplfxdic", "name": "tankShark", "region": "us-west-2", "status": "INACTIVE", "organization_id": "org2"},
]


class Base(unittest.TestCase):
    def setUp(self):
        self.fake = FakeDB()
        self.fake.tables["projects"] = [
            {"id": "p1", "name": "apparently-law", "repo_path": "/x/apparently-law"},
            {"id": "p2", "name": "apparently-archived", "repo_path": "/x/_ARCHIVED"},
            {"id": "p3", "name": "beethoven", "repo_path": "/x/orch"},
        ]
        for name in ("select", "insert", "update", "delete"):
            p = patch.object(db_registry.db, name, getattr(self.fake, name))
            p.start()
            self.addCleanup(p.stop)
        db_registry._last_discovery["at"] = 0.0
        self.env = patch.dict(os.environ, {"SUPABASE_ACCESS_TOKEN": "sbp_test_token"})
        self.env.start()
        self.addCleanup(self.env.stop)
        p = patch.object(db_registry, "_sleep", lambda s: None)
        p.start()
        self.addCleanup(p.stop)

    def _mgmt(self, payload=PROJECTS):
        return patch.object(db_registry.urllib.request, "urlopen",
                            lambda req, timeout=None: io.BytesIO(json.dumps(payload).encode()))


class DiscoveryTest(Base):
    def test_registers_every_project_and_matches_fleet_names(self):
        with self._mgmt():
            out = db_registry.discover(force=True)
        self.assertEqual(out["discovered"], 4)
        self.assertEqual(out["active"], 3)
        self.assertEqual(out["inactive"], 1)
        rows = {r["ref"]: r for r in self.fake.tables["db_sources"]}
        self.assertEqual(rows["cwmeqqtvmjbapjsefbfq"]["project"], "apparently-law")
        # The archived REPO row does not stop the live DATABASE from mapping to its product name.
        self.assertEqual(rows["oosolxvlfyifkhjohdzq"]["project"], "apparently")
        self.assertFalse(rows["hxldrekyerhmfplfxdic"]["enabled"])
        self.assertEqual(rows["hxldrekyerhmfplfxdic"]["status"], "inactive")
        self.assertTrue(rows["eatfwdzfurujcuwlhdgj"]["config"]["self"])
        for r in rows.values():
            self.assertIsNone(r["credential_ref"], "discovery must never store a credential")
            self.assertEqual(r["discovered_via"], "supabase_management_api")

    def test_rediscovery_is_idempotent(self):
        with self._mgmt():
            db_registry.discover(force=True)
            db_registry.discover(force=True)
        self.assertEqual(len(self.fake.tables["db_sources"]), 4)

    def test_throttled_without_force(self):
        with self._mgmt():
            first = db_registry.discover(force=True)
            second = db_registry.discover()
        self.assertEqual(first["discovered"], 4)
        self.assertEqual(second["skipped"], "throttled")

    def test_no_token_skips_cleanly(self):
        with patch.dict(os.environ, {"SUPABASE_ACCESS_TOKEN": ""}):
            out = db_registry.discover(force=True)
        self.assertIn("unset", out["skipped"])
        self.assertEqual(self.fake.tables["db_sources"], [])

    def test_management_api_error_leaves_registry_untouched(self):
        def boom(req, timeout=None):
            raise urllib.error.HTTPError("https://api.supabase.com", 401, "nope", {}, None)
        with patch.object(db_registry.urllib.request, "urlopen", boom):
            out = db_registry.discover(force=True)
        self.assertEqual(out["skipped"], "management api error")
        self.assertEqual(self.fake.tables["db_sources"], [])

    def test_operator_pause_survives_rediscovery(self):
        with self._mgmt():
            db_registry.discover(force=True)
            row = next(r for r in self.fake.tables["db_sources"] if r["ref"] == "cwmeqqtvmjbapjsefbfq")
            db_registry.set_enabled(row["id"], False)
            db_registry.discover(force=True)
        row = next(r for r in self.fake.tables["db_sources"] if r["ref"] == "cwmeqqtvmjbapjsefbfq")
        self.assertFalse(row["enabled"])
        self.assertEqual(row["status"], "paused")


class AddTest(Base):
    def test_add_accepts_only_credential_references(self):
        row, err = db_registry.add("aws_rds", "prod.abc.us-east-1.rds.amazonaws.com", project="tomorrow",
                                   credential_ref="keychain:RDS_PROD_PW", region="us-east-1",
                                   config={"database": "app", "username": "ro", "engine": "postgres"})
        self.assertIsNone(err)
        self.assertEqual(row["dialect"], "postgres")
        self.assertEqual(row["credential_ref"], "keychain:RDS_PROD_PW")
        for bad in ("postgresql://u:p@h/db", "hunter2", "sk-live-abc", "env:X postgres://u:p@h/db"):
            row, err = db_registry.add("postgres", "h", credential_ref=bad)
            self.assertIsNone(row, bad)
            self.assertIn("reference", err)

    def test_add_refuses_unknown_provider_and_empty_ref(self):
        self.assertIn("unknown provider", db_registry.add("oracle", "h")[1])
        self.assertIn("ref is required", db_registry.add("postgres", "  ")[1])

    def test_config_never_carries_a_secret(self):
        row, err = db_registry.add("gcp_cloudsql", "p:r:i", credential_ref="env:PW",
                                   config={"host": "10.0.0.1", "password": "x", "dsn": "postgresql://u:p@h/db",
                                           "service_account_json": "{}", "engine": "mysql", "url": "https://u:p@x"})
        self.assertIsNone(err)
        self.assertEqual(set(row["config"]), {"host", "engine"})
        self.assertEqual(row["dialect"], "mysql")

    def test_add_is_an_upsert_on_provider_ref(self):
        db_registry.add("postgres", "h1", label="a", credential_ref="env:A")
        db_registry.add("postgres", "h1", label="b", credential_ref="env:B")
        rows = [r for r in self.fake.tables["db_sources"] if r["ref"] == "h1"]
        self.assertEqual(len(rows), 1)


class ScanBookkeepingTest(Base):
    def test_three_failures_mark_unreachable_and_one_success_clears(self):
        row, _ = db_registry.add("postgres", "h2", credential_ref="env:A")
        for _ in range(3):
            db_registry.record_scan(row["id"], ok=False, error="timeout")
        cur = db_registry.get_source(row["id"])
        self.assertEqual(cur["status"], "unreachable")
        self.assertEqual(cur["consecutive_failures"], 3)
        self.assertTrue(cur["enabled"], "unreachable sources stay enabled so they are retried")
        db_registry.record_scan(row["id"], ok=True, capabilities={"dialect": "postgres"})
        cur = db_registry.get_source(row["id"])
        self.assertEqual(cur["status"], "active")
        self.assertEqual(cur["consecutive_failures"], 0)
        self.assertIsNone(cur["last_error"])
        self.assertEqual(cur["capabilities"]["dialect"], "postgres")


class PostureBackfillTest(Base):
    def test_backfills_only_missing_active_supabase_refs(self):
        self.fake.tables["security_posture"] = [{"app": "apparently", "project_ref": "oosolxvlfyifkhjohdzq"}]
        with self._mgmt():
            db_registry.discover(force=True)
        added = db_registry.sync_security_posture()
        refs = {r["project_ref"] for r in self.fake.tables["security_posture"]}
        self.assertEqual(added, 2)  # apparently-law + claude-orchestrator; inactive tankShark excluded
        self.assertIn("cwmeqqtvmjbapjsefbfq", refs)
        self.assertNotIn("hxldrekyerhmfplfxdic", refs)
        self.assertEqual(db_registry.sync_security_posture(), 0, "second pass adds nothing")

    def test_backfill_never_logs_a_token(self):
        buf = io.StringIO()
        with self._mgmt(), redirect_stdout(buf):
            db_registry.discover(force=True)
            db_registry.sync_security_posture()
        self.assertNotIn("sbp_test_token", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
