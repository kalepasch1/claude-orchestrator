#!/usr/bin/env python3
"""branch_gc.run() must read the terminal-slug set as a FULL SCAN, not a 1,000-row page.

THE BUG. `run()` built `terminal` with a bare `db.select("tasks", {...})`. PostgREST caps
a single response at 1,000 rows regardless of any `limit`, and this fleet has far more
than 1,000 tasks in DONE/MERGED/QUARANTINED. `terminal` is consumed as a MEMBERSHIP SET:

    if slug not in terminal_slugs:
        skipped += 1
        continue

so a truncated read does not merely collect less — every branch whose task fell outside
the arbitrary, unordered page is skipped on every run, forever. The symptom is silent
branch accumulation with a healthy-looking "N deleted, M skipped" line, which is exactly
the scan-window failure class db.py's module note and tools/convention_lint.py's
SCAN_WINDOW_NO_ORDER rule were written for.

These tests pin the read shape (select_all, deterministic order, no limit) rather than
any particular row count, so they survive changes to the filter.
"""
import os
import sys
import types
import unittest

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
sys.path.insert(0, RUNNER)


class _FakeDB(types.ModuleType):
    """Stand-in for runner/db.py that records how the tasks table was read."""

    def __init__(self, rows=None, raises=False):
        super().__init__("db")
        self.rows = rows if rows is not None else []
        self.raises = raises
        self.select_calls = []
        self.select_all_calls = []

    def select(self, table, params=None):
        self.select_calls.append((table, dict(params or {})))
        return list(self.rows)

    def select_all(self, table, params=None, page_size=1000, max_rows=None, order=None):
        if self.raises:
            raise RuntimeError("control plane unavailable")
        self.select_all_calls.append((table, dict(params or {}), order))
        return list(self.rows)


class _BranchGCHarness(unittest.TestCase):
    def _run_with(self, fake_db, repo="/nonexistent/repo"):
        import importlib
        prev_db = sys.modules.get("db")
        prev_repo = os.environ.get("ORCH_REPO_PATH")
        sys.modules["db"] = fake_db
        os.environ["ORCH_REPO_PATH"] = repo
        try:
            branch_gc = importlib.import_module("branch_gc")
            importlib.reload(branch_gc)
            return branch_gc, branch_gc.run()
        finally:
            if prev_db is None:
                sys.modules.pop("db", None)
            else:
                sys.modules["db"] = prev_db
            if prev_repo is None:
                os.environ.pop("ORCH_REPO_PATH", None)
            else:
                os.environ["ORCH_REPO_PATH"] = prev_repo


class TestTerminalSlugScan(_BranchGCHarness):
    def test_run_uses_select_all_not_a_windowed_select(self):
        fake = _FakeDB(rows=[{"slug": f"s{i}"} for i in range(5)])
        self._run_with(fake)
        self.assertEqual(len(fake.select_all_calls), 1,
                         "terminal slugs must be read with db.select_all (full scan)")
        self.assertEqual(fake.select_calls, [],
                         "a bare db.select() here silently truncates at 1,000 rows")

    def test_the_scan_carries_a_deterministic_order_and_no_limit(self):
        fake = _FakeDB(rows=[{"slug": "a"}])
        self._run_with(fake)
        table, params, order = fake.select_all_calls[0]
        self.assertEqual(table, "tasks")
        self.assertTrue(order, "offset paging over an unordered relation may skip rows")
        self.assertNotIn("limit", params)
        self.assertIn("state", params)

    def test_db_failure_is_fail_soft_and_reported(self):
        fake = _FakeDB(raises=True)
        _, result = self._run_with(fake)
        # Never raises, and never deletes on a failed read.
        self.assertEqual(result["deleted"], 0)


class TestDocumentedDefaultsMatchTheCode(_BranchGCHarness):
    """The env-var block drifted from the constants; both defaults were wrong."""

    def test_docstring_defaults_agree_with_the_constants(self):
        import importlib
        branch_gc = importlib.reload(importlib.import_module("branch_gc"))
        doc = branch_gc.__doc__ or ""
        self.assertIn('ORCH_BRANCH_GC_DRY_RUN     "true" for dry-run (default "false")', doc)
        self.assertIn("ORCH_BRANCH_GC_BATCH       max branches per run (default 100)", doc)
        self.assertIs(branch_gc.DRY_RUN, False)
        self.assertEqual(branch_gc.BATCH_SIZE, 100)

    def test_git_timeout_is_an_orch_env_var(self):
        import importlib
        prev = os.environ.get("ORCH_BRANCH_GC_GIT_TIMEOUT")
        os.environ["ORCH_BRANCH_GC_GIT_TIMEOUT"] = "42"
        try:
            branch_gc = importlib.reload(importlib.import_module("branch_gc"))
            self.assertEqual(branch_gc.TIMEOUT, 42)
        finally:
            if prev is None:
                os.environ.pop("ORCH_BRANCH_GC_GIT_TIMEOUT", None)
            else:
                os.environ["ORCH_BRANCH_GC_GIT_TIMEOUT"] = prev
            importlib.reload(importlib.import_module("branch_gc"))


if __name__ == "__main__":
    unittest.main()
