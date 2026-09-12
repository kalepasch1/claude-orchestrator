#!/usr/bin/env python3
"""missing_branch_audit must scan ALL DONE tasks, not the first unordered 1,000.

THE BUG. Both readers spelled the query

    db.select("tasks", {"select": ..., "state": "eq.DONE", "limit": "2000"})

which cannot return 2,000 rows: PostgREST caps a single response at 1,000 regardless of
`limit`, and without an `order` the 1,000 it does return are not even reproducible
between calls. The module then printed

    DONE tasks checked: 1000

as though that were the complete set. So the audit whose entire purpose is to find DONE
tasks whose agent/<slug> branch is gone was structurally incapable of seeing most of
them, and auto_recover_missing_branches() could only ever recover from the same
arbitrary slice. A clean result from a silently-partial audit is worse than no audit,
because it is believed — this is the scan-window failure class documented in db.py and
enforced by tools/convention_lint.py's SCAN_WINDOW_NO_ORDER rule.

These tests pin the read SHAPE (select_all, deterministic order, no limit) rather than
any row count, so they survive changes to the filter or the column list.
"""
import os
import sys
import types
import unittest

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")


class _FakeDB(types.ModuleType):
    """Records how missing_branch_audit reads the tasks and projects tables."""

    def __init__(self, task_rows=None, project_rows=None):
        super().__init__("db")
        self.task_rows = task_rows or []
        self.project_rows = project_rows or []
        self.select_calls = []
        self.select_all_calls = []

    def _rows_for(self, table):
        return list(self.task_rows if table == "tasks" else self.project_rows)

    def select(self, table, params=None):
        self.select_calls.append((table, dict(params or {})))
        return self._rows_for(table)

    def select_all(self, table, params=None, page_size=1000, max_rows=None, order=None):
        self.select_all_calls.append((table, dict(params or {}), order))
        return self._rows_for(table)

    def localize_repo_path(self, path):
        return path or ""


class _Harness(unittest.TestCase):
    def _load(self, fake_db):
        import importlib
        if RUNNER not in sys.path:
            sys.path.insert(0, RUNNER)
        prev = sys.modules.get("db")
        sys.modules["db"] = fake_db
        try:
            module = importlib.reload(importlib.import_module("missing_branch_audit"))
            return module
        finally:
            if prev is None:
                sys.modules.pop("db", None)
            else:
                sys.modules["db"] = prev


class TestFullScan(_Harness):
    def _tasks(self):
        return [{"id": i, "slug": f"s{i}", "project_id": "p", "state": "DONE"}
                for i in range(3)]

    def test_main_reads_every_done_task_with_select_all(self):
        fake = _FakeDB(task_rows=self._tasks(),
                       project_rows=[{"id": "p", "name": "beethoven", "repo_path": ""}])
        module = self._load(fake)
        module.main()
        tables = [call[0] for call in fake.select_all_calls]
        self.assertIn("tasks", tables)
        self.assertEqual(fake.select_calls, [],
                         "a windowed db.select() here silently truncates at 1,000 rows")

    def test_the_task_scan_is_ordered_and_unlimited(self):
        fake = _FakeDB(task_rows=self._tasks(),
                       project_rows=[{"id": "p", "name": "beethoven", "repo_path": ""}])
        module = self._load(fake)
        module.main()
        table, params, order = next(c for c in fake.select_all_calls if c[0] == "tasks")
        self.assertTrue(order, "offset paging over an unordered relation may skip rows")
        self.assertNotIn("limit", params)
        self.assertEqual(params.get("state"), "eq.DONE")

    def test_auto_recover_uses_the_same_full_scan(self):
        fake = _FakeDB(task_rows=self._tasks(),
                       project_rows=[{"id": "p", "name": "beethoven", "repo_path": ""}])
        module = self._load(fake)
        module.auto_recover_missing_branches(dry_run=True)
        # Any db.select() that survives here must be a keyed lookup, never a state scan.
        for table, params in fake.select_calls:
            self.assertTrue("slug" in params,
                            f"unkeyed db.select on {table}: {params}")
        task_scans = [c for c in fake.select_all_calls if c[0] == "tasks"]
        self.assertTrue(task_scans)
        self.assertNotIn("limit", task_scans[0][1])

    def test_no_windowed_task_scan_remains_in_the_module_source(self):
        """The literal call shape is gone from executable code.

        Matched against the AST, not the raw text: the docstring in _all_done_tasks
        quotes the old query on purpose so the next reader knows why the helper exists,
        and a substring check over the file would fire on that explanation.
        """
        import ast
        fake = _FakeDB()
        module = self._load(fake)
        with open(module.__file__, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        offenders = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr != "select":
                continue
            table = node.args[0] if node.args else None
            if isinstance(table, ast.Constant) and table.value == "tasks":
                params = next((a for a in node.args if isinstance(a, ast.Dict)), None)
                keys = {k.value for k in (params.keys if params else [])
                        if isinstance(k, ast.Constant)}
                # A keyed lookup ("slug": "eq.X") is a legitimate bounded read; an
                # unkeyed state scan is the window bug.
                if "slug" not in keys:
                    offenders.append(node.lineno)
        self.assertEqual(offenders, [],
                         f"windowed db.select on tasks at line(s) {offenders}")


class TestFailSoft(_Harness):
    def test_branch_exists_never_raises_and_reports(self):
        module = self._load(_FakeDB())
        # Unresolvable repo path -> None ("could not check"), never an exception.
        self.assertIsNone(module._branch_exists("/nonexistent/repo", "agent/x"))
        self.assertIsNone(module._branch_exists(None, "agent/x"))
        self.assertIsNone(module._branch_exists("", ""))

    def test_git_timeout_is_an_orch_env_var(self):
        prev = os.environ.get("ORCH_MISSING_BRANCH_GIT_TIMEOUT")
        os.environ["ORCH_MISSING_BRANCH_GIT_TIMEOUT"] = "33"
        try:
            module = self._load(_FakeDB())
            self.assertEqual(module.GIT_TIMEOUT, 33)
        finally:
            if prev is None:
                os.environ.pop("ORCH_MISSING_BRANCH_GIT_TIMEOUT", None)
            else:
                os.environ["ORCH_MISSING_BRANCH_GIT_TIMEOUT"] = prev
            self._load(_FakeDB())


if __name__ == "__main__":
    unittest.main()
