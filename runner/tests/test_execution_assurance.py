import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import execution_assurance as assurance
import db


class TestExecutionAssurance(unittest.TestCase):
    def test_normalizes_independent_dependencies(self):
        self.assertEqual(assurance.normalize_deps(None), [])
        self.assertEqual(assurance.normalize_deps(["first", "", 2]), ["first", "2"])
        with self.assertRaises(ValueError):
            assurance.normalize_deps("not-an-array")

    def test_design_spec_requires_two_distinct_approvals(self):
        task = {"kind": "speculative", "prompt": "DESIGN-SPEC: counsel approval required"}
        self.assertFalse(assurance.counsel_gate_satisfied(task))
        self.assertFalse(assurance.counsel_gate_satisfied({**task,
            "operator_approved_at": "2026-07-20T00:00:00Z", "operator_approved_by": "operator"}))
        self.assertTrue(assurance.counsel_gate_satisfied({**task,
            "operator_approved_at": "2026-07-20T00:00:00Z", "operator_approved_by": "operator",
            "counsel_approved_at": "2026-07-20T00:00:00Z", "counsel_approved_by": "outside counsel"}))

    def test_non_design_spec_is_not_counsel_gated(self):
        self.assertTrue(assurance.counsel_gate_satisfied({"kind": "speculative", "prompt": "try alternatives"}))

    def test_flags_old_decomposed_task_without_run(self):
        now = dt.datetime(2026, 7, 19, 12, tzinfo=dt.timezone.utc)
        tasks = [
            {"id": "old", "state": "DECOMPOSED", "updated_at": "2026-07-19T11:45:00+00:00"},
            {"id": "new", "state": "DECOMPOSED", "updated_at": "2026-07-19T11:55:00+00:00"},
            {"id": "done", "state": "DONE", "updated_at": "2026-07-19T11:00:00+00:00"},
        ]
        breaches = assurance.dispatch_sla_breaches(tasks, [{"task_id": "new"}], now=now, minutes=10)
        self.assertEqual([task["id"] for task in breaches], ["old"])

    def test_decomposed_parent_and_dependency_hold_are_not_sla_breaches(self):
        now = dt.datetime(2026, 7, 19, 12, tzinfo=dt.timezone.utc)
        tasks = [
            {"id": "parent", "slug": "parent", "state": "DECOMPOSED", "deps": [], "updated_at": "2026-07-19T11:00:00+00:00"},
            {"id": "child", "slug": "child", "state": "QUEUED", "deps": ["parent"]},
            {"id": "blocked", "slug": "blocked", "state": "DECOMPOSED", "deps": ["upstream"], "updated_at": "2026-07-19T11:00:00+00:00"},
        ]
        self.assertEqual(assurance.dispatch_sla_breaches(tasks, [], now=now, minutes=10), [])

    def test_db_insert_normalizes_null_deps_before_posting(self):
        original_req = db._req
        posted = {}
        try:
            def request(method, path, body=None, headers=None, params=None):
                posted.update(body or {})
                return [body]
            db._req = request
            db.insert("tasks", {"slug": "independent", "project_id": "project", "prompt": "A sufficiently detailed task prompt."}, upsert=True)
        finally:
            db._req = original_req
        self.assertEqual(posted["deps"], [])

    def test_db_claim_holds_counsel_gated_design_spec_without_two_approvals(self):
        original_select, original_req = db.select, db._req
        attempted = []
        task = {
            "id": "spec", "slug": "tomorrow-design", "project_id": "project", "deps": [],
            "kind": "speculative", "prompt": "DESIGN-SPEC: counsel approval required", "created_at": "2026-07-19T00:00:00+00:00",
        }
        try:
            def select(table, params=None):
                params = params or {}
                if table == "projects":
                    return [{"id": "project", "name": "tomorrow", "priority": 5, "concurrency_weight": 1}]
                if table == "tasks" and params.get("state") == "eq.QUEUED":
                    return [dict(task)]
                return []
            def request(*args, **kwargs):
                attempted.append(args)
                return []
            db.select, db._req = select, request
            with unittest.mock.patch.dict(os.environ, {"ORCH_CLAIM_REQUIRE_LOCAL_REPO": "false"}, clear=False):
                self.assertIsNone(db.claim_task("runner"))
        finally:
            db.select, db._req = original_select, original_req
        self.assertEqual(attempted, [])
