"""db_policy_synth + db_content_probe + db_link demand — the judgment-side surfaces."""
import os
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import db_policy_synth as PS  # noqa: E402
import db_content_probe as CP  # noqa: E402


class PolicySynthTest(unittest.TestCase):
    def test_owner_hint_priority(self):
        self.assertEqual(PS.owner_hint(["id", "user_id", "email"]), "user_id")
        self.assertEqual(PS.owner_hint(["id", "tenant_ref_id"]), "tenant_ref_id")
        self.assertEqual(PS.owner_hint(["id", "payer_email"]), "payer_email")
        self.assertEqual(PS.owner_hint(["id", "created_at"]), "")

    def test_candidate_uses_hint_and_quotes_safely(self):
        sql, hint = PS.candidate_policy("proj", "matters", ["id", "matter_type", "account_id"])
        self.assertEqual(hint, "account_id")
        self.assertIn('alter table public."matters" enable row level security;', sql)
        self.assertIn('"account_id"::text = auth.uid()::text', sql)
        self.assertIn("DRAFT", sql)

    def test_no_hint_means_no_sql(self):
        sql, reason = PS.candidate_policy("proj", "log_sink", ["id", "kind", "payload"])
        self.assertEqual(sql, "") and self.assertIn("no tenancy key", reason)

    def test_generate_group_orders_and_skips(self):
        rows = [{"object_name": "users"}, {"object_name": "matters"}, {"object_name": "matters"}]

        def sel(t, p=None):
            return rows if t == PS.FINDINGS else []

        with patch.object(PS.db, "select", sel), \
             patch.object(PS, "_columns_for", lambda p, t: ["id", "user_id"] if t == "matters" else []):
            candidates, skipped = PS.generate_group("proj")
        self.assertEqual([t for t, _s, _h in candidates], ["matters"], "deduped, hinted tables only")
        self.assertTrue(any(s.startswith("users:") for s in skipped))


class ContentProbeTest(unittest.TestCase):
    def test_double_gate(self):
        with patch.object(CP, "ENABLED", False):
            self.assertFalse(CP.source_enabled({"config": {"content_probe": True}}))
        with patch.object(CP, "ENABLED", True):
            self.assertFalse(CP.source_enabled({"config": {}}))
            self.assertTrue(CP.source_enabled({"config": {"content_probe": True}}))
            self.assertTrue(CP.source_enabled({"config": '{"content_probe": true}'}))
            self.assertFalse(CP.source_enabled({"config": "oops"}))

    def test_counts_only_and_email_shape_finding(self):
        seen_sql = []

        def q(src, sql):
            seen_sql.append(sql)
            if "information_schema.columns" in sql:
                return [{"table_name": "applicants", "column_name": "email"}]
            return [{"n": 200, "bad": 10}]
        src = {"ref": "t", "config": {"content_probe": True}}
        with patch.object(CP, "ENABLED", True):
            out = CP.collect(src, q)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["probe_id"], "content_probe_email_shape")
        self.assertIn("5.0% of 200 rows", out[0]["title"])
        self.assertTrue(all("select" in s.lower() for s in seen_sql), "count/select only")
        self.assertFalse(any(" !~" in s and "count(" not in s for s in seen_sql))
        self.assertFalse(any("'someone@x.com'" in s for s in seen_sql), "no row values touch SQL")

    def test_secret_column_presence(self):
        def q(src, sql):
            if "information_schema.columns" in sql:
                return [{"table_name": "settings", "column_name": "api_token"}]
            return [{"n": 12}]
        with patch.object(CP, "ENABLED", True):
            out = CP.collect({"ref": "t", "config": {"content_probe": True}}, q)
        self.assertTrue(any(f["probe_id"] == "content_probe_secret_columns" for f in out))

    def test_disabled_source_collects_nothing(self):
        with patch.object(CP, "ENABLED", True):
            self.assertEqual(CP.collect({"ref": "t", "config": {}}, lambda *a: self.fail("must not query")), [])


class DemandTest(unittest.TestCase):
    def test_unassessed_arguments_listed(self):
        import db_link
        memos = [{"project": "proj", "memo_kind": "access_control_and_least_privilege",
                  "arguments": [{"key": "row_level_isolation", "strength": "supported"}]}]
        import db as _db
        with patch.object(_db, "select_all", lambda *a, **k: memos):
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = db_link.cmd_demand(types.SimpleNamespace(json=False))
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("proj", out)
        self.assertIn("anon_surface_minimal", out, "uncovered argument demands a probe")
        self.assertNotIn("row_level_isolation\n", out.split("access_control")[-1][1:] or "", )


if __name__ == "__main__":
    unittest.main()
