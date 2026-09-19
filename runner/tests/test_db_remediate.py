"""db_remediate: findings -> deterministic migration SQL -> draft PRs (mocked HTTP)."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import db_remediate as R  # noqa: E402


def finding(probe, table="orders", schema="public", sev="medium", metrics=None, fp="f" * 40, status="open"):
    return {"probe_id": probe, "severity": sev, "status": status, "fingerprint": fp,
            "object_schema": schema, "object_name": table, "metrics": metrics or {}, "title": "t"}


class SqlGenerationTest(unittest.TestCase):
    def test_revoke_grants_idempotent_writes_only(self):
        sql = R._sql_revoke_grants(finding("anon_or_public_grants"))
        self.assertIn('revoke insert, update, delete, truncate, references, trigger on "public"."orders" from anon;', sql)
        self.assertIn("from public;", sql)
        self.assertNotIn("select", sql.lower().replace("references", ""), "SELECT must stay (RLS decides)")

    def test_public_write_surface_gets_a_caution_comment(self):
        sql = R._sql_revoke_grants(finding("anon_or_public_grants", table="intake_requests"))
        self.assertIn("NOTE:", sql) and sql.index("NOTE") < sql.index("revoke")
        sql_plain = R._sql_revoke_grants(finding("anon_or_public_grants", table="orders"))
        self.assertNotIn("NOTE", sql_plain)

    def test_fk_index_needs_columns_metric(self):
        self.assertEqual(R._sql_fk_index(finding("unindexed_foreign_keys")), "",
                         "metrics predate the columns enrichment -> skip, never guess")
        f = finding("unindexed_foreign_keys", metrics={"columns": ["team_id"]})
        sql = R._sql_fk_index(f)
        self.assertIn("create index concurrently if not exists", sql)
        self.assertIn('"public"."orders" ("team_id")', sql)

    def test_audit_columns_target_only_the_missing_ones(self):
        f = finding("missing_audit_columns", metrics={"missing": ["updated_at"]})
        sql = R._sql_audit_columns(f)
        self.assertNotIn("created_at", sql)
        self.assertIn("add column if not exists updated_at", sql)
        self.assertIn("extensions.moddatetime", sql)

    def test_bad_identifiers_never_interpolate(self):
        f = finding("anon_or_public_grants", table='x"; drop table users; --')
        self.assertEqual(R._sql_revoke_grants(f), "")
        f2 = finding("unindexed_foreign_keys", metrics={"columns": ["a", "b' ; drop"]})
        self.assertEqual(R._sql_fk_index(f2), "")

    def test_plan_groups_and_orders(self):
        fs = [finding("anon_or_public_grants", table="b_t", fp="b" * 40),
              finding("anon_or_public_grants", table="a_t", fp="a" * 40),
              finding("updated_at_without_trigger", table="a_t", fp="c" * 40),
              finding("slow_query_classes", fp="d" * 40)]  # unsupported -> ignored
        plans = R.plan_migration("proj", fs)
        by_group = {g: (sql, fps) for g, sql, fps, _sk in plans if sql}
        self.assertIn("access-grants", by_group)
        self.assertIn("audit-columns", by_group)
        sql, fps = by_group["access-grants"]
        self.assertTrue(sql.index('"public"."a_t"') < sql.index('"public"."b_t"'), "deterministic object order")
        self.assertIn("begin;", sql) and sql.rstrip().endswith("commit;")
        self.assertEqual(set(fps), {"a" * 40, "b" * 40})


class FakeGh:
    def __init__(self, prs=None, repo_meta=None, closed_prs=None):
        self.calls = []
        self.prs = prs if prs is not None else []
        self.closed_prs = closed_prs if closed_prs is not None else []
        self.repo_meta = repo_meta or {"default_branch": "main"}
        self.ref_sha = "b" * 40

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path.startswith("/repos/") and "/pulls" in path and method == "GET":
            return list(self.closed_prs) if "state=closed" in path else list(self.prs)
        if path.endswith("/git/ref/heads/main"):
            return {"object": {"sha": self.ref_sha}}
        if method == "GET" and path.count("/") == 2:
            return dict(self.repo_meta)
        if method == "POST" and path.endswith("/git/refs"):
            return {"ref": body["ref"]}
        if method == "PUT" and "/contents/" in path:
            return {"content": {"path": body and path}}
        if method == "POST" and path.endswith("/pulls"):
            return {"html_url": "https://example.test/pr/1", "number": 1}
        return {}


class PrLifecycleTest(unittest.TestCase):
    def test_existing_open_pr_skips(self):
        gh = FakeGh(prs=[{"html_url": "https://example.test/pr/9"}])
        with patch.object(R, "_gh", gh), patch.object(R, "_gh_token", lambda: "t"):
            res = R.ensure_draft_pr("proj", "org/repo", "access-grants", "sql", ["fp"])
        self.assertTrue(res["ok"]) and self.assertIn("open PR exists", res["skipped"])
        self.assertFalse(any(m == "POST" and p.endswith("/pulls") for m, p, _ in gh.calls))

    def test_creates_branch_file_and_draft_pr(self):
        gh = FakeGh()
        with patch.object(R, "_gh", gh), patch.object(R, "_gh_token", lambda: "t"):
            res = R.ensure_draft_pr("proj", "org/repo", "access-grants", "select 1;", ["fp1"])
        self.assertTrue(res["ok"]) and res.get("pr")
        methods = [m for m, _p, _b in gh.calls]
        self.assertEqual(methods, ["GET", "GET", "GET", "GET", "POST", "PUT", "POST"])
        pr_body = gh.calls[-1][2]
        self.assertTrue(pr_body["draft"]) and self.assertEqual(pr_body["base"], "main")
        self.assertIn("fp:fp1", pr_body["body"])

    CLOSED_UNMERGED = {"number": 342, "html_url": "https://example.test/pr/342", "merged_at": None,
                       "head": {"ref": "fix/db-steer-audit-columns"}}
    CLOSED_MERGED = {"number": 300, "html_url": "https://example.test/pr/300",
                     "merged_at": "2026-09-18T10:00:00Z", "head": {"ref": "fix/db-steer-audit-columns"}}

    @staticmethod
    def _writes(gh):
        return [(m, p) for m, p, _b in gh.calls if m in ("POST", "PUT")]

    def test_declined_group_is_not_refiled(self):
        # Two closed-unmerged PRs on the head branch: the reviewer said no twice, so the
        # group returns a skip and nothing is created (no branch, no file, no PR).
        gh = FakeGh(closed_prs=[dict(self.CLOSED_UNMERGED), dict(self.CLOSED_UNMERGED, number=406)])
        with patch.object(R, "_gh", gh), patch.object(R, "_gh_token", lambda: "t"), \
             patch.dict(os.environ, {"ORCH_DB_REMEDIATE_DECLINE_AFTER": "2"}):
            res = R.ensure_draft_pr("proj", "org/repo", "audit-columns", "select 1;", ["fp1"])
        self.assertTrue(res["ok"])
        self.assertEqual(res["skip"], "declined on the repo: 2 unmerged closures of fix/db-steer-audit-columns")
        self.assertEqual(res["skipped"], res["skip"])
        self.assertEqual(self._writes(gh), [])
        closed_calls = [p for m, p, _b in gh.calls if "state=closed" in p]
        self.assertEqual(closed_calls,
                         ["/repos/org/repo/pulls?state=closed&head=org:fix/db-steer-audit-columns&per_page=10"])

    def test_one_unmerged_and_one_merged_closure_still_files(self):
        # A merged closure is a success, not a decline: only unmerged ones count.
        gh = FakeGh(closed_prs=[dict(self.CLOSED_UNMERGED), dict(self.CLOSED_MERGED)])
        with patch.object(R, "_gh", gh), patch.object(R, "_gh_token", lambda: "t"), \
             patch.dict(os.environ, {"ORCH_DB_REMEDIATE_DECLINE_AFTER": "2"}):
            res = R.ensure_draft_pr("proj", "org/repo", "audit-columns", "select 1;", ["fp1"])
        self.assertTrue(res["ok"])
        self.assertNotIn("skip", res)
        self.assertEqual(res["pr"], "https://example.test/pr/1")
        self.assertEqual([m for m, _p in self._writes(gh)], ["POST", "PUT", "POST"])

    def test_decline_check_disabled_with_zero(self):
        # Knob "0" disables the check: five declines and it still files, and the closed
        # listing is never even requested.
        gh = FakeGh(closed_prs=[dict(self.CLOSED_UNMERGED, number=n) for n in (342, 406, 412, 413, 77)])
        with patch.object(R, "_gh", gh), patch.object(R, "_gh_token", lambda: "t"), \
             patch.dict(os.environ, {"ORCH_DB_REMEDIATE_DECLINE_AFTER": "0"}):
            res = R.ensure_draft_pr("proj", "org/repo", "audit-columns", "select 1;", ["fp1"])
        self.assertTrue(res["ok"])
        self.assertNotIn("skip", res)
        self.assertEqual(res["pr"], "https://example.test/pr/1")
        self.assertFalse(any("state=closed" in p for _m, p, _b in gh.calls))

    def test_closed_listing_failure_fails_open(self):
        # A GitHub error on the closed listing must not block filing (fail-soft, like the
        # rest of the module): it counts as zero closures.
        gh = FakeGh()
        real = gh.__call__

        def flaky(method, path, body=None):
            if "state=closed" in path:
                gh.calls.append((method, path, body))
                return {"_http_error": 502, "_message": "Bad Gateway"}
            return real(method, path, body)
        with patch.object(R, "_gh", flaky), patch.object(R, "_gh_token", lambda: "t"):
            res = R.ensure_draft_pr("proj", "org/repo", "audit-columns", "select 1;", ["fp1"])
        self.assertTrue(res["ok"]) and self.assertEqual(res["pr"], "https://example.test/pr/1")

    def test_gh_failure_is_a_reason_not_an_exception(self):
        def bad(method, path, body=None):
            return {"_http_error": 404, "_message": "Not Found"}
        with patch.object(R, "_gh", bad):
            res = R.ensure_draft_pr("proj", "org/nope", "access-grants", "sql", ["fp"])
        self.assertFalse(res["ok"]) and "repo lookup failed" in res["reason"]


class CloseoutTest(unittest.TestCase):
    FP = "a" * 40
    PR_OPEN = {"number": 1, "title": "db-steering: cover unindexed foreign keys",
               "body": "### Findings covered\n\n- [fp:%s]" % FP[:12],
               "head": {"ref": "fix/db-steer-fk-indexes", "sha": "h" * 40}, "merged_at": None}
    PR_MERGED = {**PR_OPEN, "number": 2, "merged_at": "2026-09-14T00:00:00Z"}

    def _gh(self, statuses_by_fp, comments=None):
        comments = comments if comments is not None else []

        def gh(method, path, body=None):
            if "/comments" in path and method == "GET":
                return list(comments)
            if method == "POST" and "/comments" in path:
                return {"id": 9}
            if method == "PATCH":
                return {"id": 9}
            return {}
        return gh

    def test_open_pr_reports_pending(self):
        with patch.object(R, "_gh", self._gh({})):
            st = R.closeout_pr("me/x", self.PR_OPEN,
                               [{"fingerprint": self.FP, "status": "open"}])
        self.assertEqual(st.split(" ")[0], "open-pending")

    def test_merged_all_resolved_is_verified(self):
        with patch.object(R, "_gh", self._gh({})):
            st = R.closeout_pr("me/x", self.PR_MERGED,
                               [{"fingerprint": self.FP, "status": "resolved"}])
        self.assertTrue(st.startswith("verified-resolved"), st)

    def test_merged_but_still_open_is_not_confirmed(self):
        with patch.object(R, "_gh", self._gh({})):
            st = R.closeout_pr("me/x", self.PR_MERGED,
                               [{"fingerprint": self.FP, "status": "open"}])
        self.assertTrue(st.startswith("merged-not-confirmed"), st)

    def test_unchanged_comment_is_not_rewrite(self):
        posted = {}

        def recorder(method, path, body=None):
            if "/comments" in path and method == "GET":
                return []
            if method == "POST" and "/comments" in path:
                posted["body"] = body["body"]; return {"id": 9}
            return {}

        with patch.object(R, "_gh", recorder):
            R.closeout_pr("me/x", self.PR_OPEN, [{"fingerprint": self.FP, "status": "open"}])
        self.assertIn("body", posted, "first sight of the PR posts a comment")

        def replayer(method, path, body=None):
            if "/comments" in path and method == "GET":
                return [{"id": 9, "body": posted["body"]}]
            if method == "PATCH":
                raise AssertionError("identical body must not PATCH")
            if method == "POST":
                raise AssertionError("an existing identical comment must not duplicate")
            return {}

        with patch.object(R, "_gh", replayer):
            st = R.closeout_pr("me/x", self.PR_OPEN, [{"fingerprint": self.FP, "status": "open"}])
        self.assertIn("unchanged", st)

    def test_foreign_prs_untouched(self):
        with patch.object(R, "_gh", self._gh({})):
            st = R.closeout_pr("me/x", {"number": 3, "title": "feat: whatever",
                                        "body": "", "head": {"ref": "feat/x", "sha": "z"}, "merged_at": None},
                               [])
        self.assertEqual(st, "not ours")


class FleetWiringTest(unittest.TestCase):
    ROW = {"name": "proj", "repo_path": "/x/proj", "vercel_project": None, "superseded_by": None}

    def test_exclusions(self):
        engines = {"name": "apparently-engines", "repo_path": "/x/apparently.cc-engines",
                   "vercel_project": None, "superseded_by": None}
        with patch.object(R.db, "select_all", lambda *a, **k: []):
            res = R.remediate_project(engines, budget=1)
        self.assertEqual(res["reason"], "excluded")

    def test_plan_only_mode_lists_groups_without_http(self):
        fs = [finding("anon_or_public_grants")]
        with patch.object(R.db, "select_all", lambda t, p, **k: fs), \
             patch.object(R, "ENABLED", False), \
             patch.object(R, "_gh", side_effect=AssertionError("no http in plan-only mode")):
            res = R.remediate_project(dict(self.ROW), budget=3)
        self.assertTrue(res["ok"])
        self.assertEqual(res["planned"][0]["group"], "access-grants")
        self.assertEqual(res["reason"], "plan-only (ORCH_DB_REMEDIATE=0)")

    def test_declined_skip_reason_reaches_project_result(self):
        fs = [finding("missing_audit_columns", metrics={"missing": ["created_at", "updated_at"]})]
        declined = "declined on the repo: 2 unmerged closures of fix/db-steer-audit-columns"
        with patch.object(R.db, "select_all", lambda t, p, **k: fs), \
             patch.object(R, "ENABLED", True), \
             patch.object(R, "repo_for_project", lambda row: "org/repo"), \
             patch.object(R, "ensure_draft_pr",
                          lambda *a, **k: {"ok": True, "skipped": declined, "skip": declined}):
            res = R.remediate_project(dict(self.ROW), budget=3)
        self.assertTrue(res["ok"])
        self.assertEqual(res["skips"], ["audit-columns: " + declined])
        self.assertEqual(res["reason"], "audit-columns: " + declined)
        self.assertEqual(res["pr_results"][0]["skipped"], declined)

    def test_nothing_mechanical(self):
        with patch.object(R.db, "select_all", lambda t, p, **k: []):
            res = R.remediate_project(dict(self.ROW), budget=3)
        self.assertEqual(res["reason"], "nothing mechanical open")

    def test_run_cycle_never_raises_and_bounds_budget(self):
        rows = [{"name": "a", "vercel_project": None, "superseded_by": None, "repo_path": ""},
                {"name": "b", "vercel_project": None, "superseded_by": None, "repo_path": ""}]
        with patch.object(R, "remediate_project", side_effect=RuntimeError("boom")):
            out = R.run_cycle(rows, budget=2)
        self.assertEqual(len(out["results"]), 2)
        self.assertFalse(out["results"][0]["ok"])
        self.assertIn("boom", out["results"][0]["reason"])

    def test_repo_resolution_from_vercel_link_and_override(self):
        with patch.dict(os.environ, {"ORCH_DB_REMEDIATE_REPOS": '{"proj": "me/repo"}'}):
            self.assertEqual(R.repo_for_project({"name": "proj", "vercel_project": None}), "me/repo")
        with patch.dict(os.environ, {"ORCH_DB_REMEDIATE_REPOS": ""}), \
             patch.object(R, "VERCEL_TOKEN", "vt"), \
             patch.object(R, "_http", lambda *a, **k: {"link": {"org": "me", "repo": "r2"}}):
            self.assertEqual(R.repo_for_project({"name": "p2", "vercel_project": "vp"}), "me/r2")


if __name__ == "__main__":
    unittest.main()
