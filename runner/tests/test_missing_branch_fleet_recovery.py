#!/usr/bin/env python3
"""Missing-branch recovery, integrated into the fleet-wide workflow.

`deployment_terminal._route_absent_commits_to_recovery` is the ONE place missing-branch
recovery is wired into the delivery workflow, and it called
`auto_recover_missing_branches(dry_run=True, ...)` with the flag hardcoded. So the
recovery step could never recover anything: it printed RECOVERY-CANDIDATE lines forever
while the branches stayed missing, and because the return value was discarded, nothing
recorded that the step was a no-op — indistinguishable from "there was nothing to
recover".

A second defect made that invisible from the other side too: in dry-run,
`auto_recover_missing_branches` incremented the SAME `recovered` counter the real path
uses, so the dict it returned reported recovery work that had not happened. Since the
only fleet-wide caller ran it in dry-run permanently, every "recovered" count it could
have produced was for a task nobody created.

Proof: python3 -m pytest runner/tests/test_missing_branch_fleet_recovery.py -q
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import missing_branch_audit as mba  # noqa: E402


class _DB:
    def __init__(self, projects=(), done=(), existing=()):
        self.projects = list(projects)
        self.done = list(done)
        self.existing = list(existing)
        self.inserted = []

    def select(self, table, params=None):
        params = params or {}
        if table == "projects":
            return list(self.projects)
        if table == "tasks" and params.get("state") == "eq.DONE":
            return list(self.done)
        if table == "tasks" and str(params.get("slug", "")).startswith("eq.recover-"):
            return list(self.existing)
        return []

    def select_all(self, table, params=None, **kw):
        return self.select(table, params)

    def insert(self, table, row, **kw):
        self.inserted.append((table, row))
        return row

    @staticmethod
    def localize_repo_path(path):
        return path or "/tmp/repo"


def _task(slug, tid="t1"):
    return {"id": tid, "slug": slug, "project_id": "p1", "state": "DONE",
            "prompt": "do the thing", "kind": "build", "base_branch": "master"}


PROJECTS = [{"id": "p1", "name": "beethoven", "repo_path": "/tmp/repo"}]


class TestDryRunAccounting(unittest.TestCase):
    """A dry run must never report work as recovered."""

    def _run(self, dry_run, tasks=None, existing=()):
        db = _DB(projects=PROJECTS, done=tasks or [_task("a"), _task("b", "t2")],
                 existing=list(existing))
        with patch.object(mba, "db", db), \
             patch.object(mba, "_branch_exists", return_value=False):
            return mba.auto_recover_missing_branches(dry_run=dry_run), db

    def test_dry_run_recovers_nothing(self):
        result, db = self._run(dry_run=True)
        self.assertEqual(result["recovered"], 0)
        self.assertEqual(db.inserted, [])

    def test_dry_run_reports_what_it_would_have_done(self):
        result, _ = self._run(dry_run=True)
        self.assertEqual(result["would_recover"], 2)
        self.assertEqual(result["missing"], 2)

    def test_dry_run_is_labelled_as_such(self):
        self.assertTrue(self._run(dry_run=True)[0]["dry_run"])

    def test_a_real_run_actually_creates_recovery_tasks(self):
        result, db = self._run(dry_run=False)
        self.assertEqual(result["recovered"], 2)
        self.assertEqual(len(db.inserted), 2)
        self.assertFalse(result["dry_run"])

    def test_a_real_run_reports_no_would_recover(self):
        self.assertEqual(self._run(dry_run=False)[0]["would_recover"], 0)

    def test_an_existing_recovery_task_is_skipped_in_both_modes(self):
        for dry in (True, False):
            result, db = self._run(dry_run=dry, existing=[{"id": "already"}])
            self.assertEqual(result["recovered"], 0, dry)
            self.assertEqual(result["would_recover"], 0, dry)
            self.assertEqual(db.inserted, [])

    def test_max_recover_caps_the_work(self):
        db = _DB(projects=PROJECTS,
                 done=[_task(f"s{i}", f"t{i}") for i in range(10)])
        with patch.object(mba, "db", db), \
             patch.object(mba, "_branch_exists", return_value=False):
            result = mba.auto_recover_missing_branches(dry_run=False, max_recover=3)
        self.assertEqual(result["recovered"], 3)
        self.assertEqual(result["missing"], 10)

    def test_present_branches_are_not_recovered(self):
        db = _DB(projects=PROJECTS, done=[_task("a")])
        with patch.object(mba, "db", db), \
             patch.object(mba, "_branch_exists", return_value=True):
            result = mba.auto_recover_missing_branches(dry_run=False)
        self.assertEqual(result["missing"], 0)
        self.assertEqual(db.inserted, [])

    def test_every_return_path_carries_the_same_keys(self):
        """A caller reading result["dry_run"] must not KeyError on an early return."""
        class _Boom:
            @staticmethod
            def select(*a, **k):
                raise RuntimeError("db down")

            @staticmethod
            def select_all(*a, **k):
                raise RuntimeError("db down")

            @staticmethod
            def localize_repo_path(p):
                return p
        with patch.object(mba, "db", _Boom):
            result = mba.auto_recover_missing_branches(dry_run=True)
        for key in ("recovered", "missing", "would_recover", "dry_run"):
            self.assertIn(key, result)


class TestFleetWideIntegration(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.pop("ORCH_MISSING_BRANCH_AUTO_RECOVER", None)

    def tearDown(self):
        if self._saved is not None:
            os.environ["ORCH_MISSING_BRANCH_AUTO_RECOVER"] = self._saved
        else:
            os.environ.pop("ORCH_MISSING_BRANCH_AUTO_RECOVER", None)

    def _route(self, absent=({"slug": "a", "artifact_commit": "abc1234"},)):
        import deployment_terminal
        seen = {}

        def _fake(dry_run=True, max_recover=10):
            seen["dry_run"] = dry_run
            seen["max_recover"] = max_recover
            return {"recovered": 0, "missing": 1, "would_recover": 1, "dry_run": dry_run}

        fake_mod = type("_M", (), {"auto_recover_missing_branches": staticmethod(_fake)})
        with patch.dict(sys.modules, {"missing_branch_audit": fake_mod}):
            count = deployment_terminal._route_absent_commits_to_recovery(
                "beethoven", list(absent))
        return seen, count

    def test_default_preserves_todays_dry_run_behaviour(self):
        seen, _ = self._route()
        self.assertTrue(seen["dry_run"], "default must not start creating tasks silently")

    def test_the_switch_enables_real_recovery(self):
        os.environ["ORCH_MISSING_BRANCH_AUTO_RECOVER"] = "1"
        seen, _ = self._route()
        self.assertFalse(seen["dry_run"])

    def test_the_switch_accepts_the_usual_truthy_spellings(self):
        for value in ("1", "true", "YES", "on"):
            os.environ["ORCH_MISSING_BRANCH_AUTO_RECOVER"] = value
            self.assertFalse(self._route()[0]["dry_run"], value)

    def test_an_unrecognised_value_stays_dry(self):
        """Fails safe: anything that is not clearly ON does not create tasks."""
        os.environ["ORCH_MISSING_BRANCH_AUTO_RECOVER"] = "maybe"
        self.assertTrue(self._route()[0]["dry_run"])

    def test_the_absent_population_is_passed_as_the_cap(self):
        seen, _ = self._route(absent=[{"slug": "a"}, {"slug": "b"}, {"slug": "c"}])
        self.assertEqual(seen["max_recover"], 3)

    def test_the_return_contract_is_unchanged(self):
        _, count = self._route(absent=[{"slug": "a"}, {"slug": "b"}])
        self.assertEqual(count, 2)

    def test_no_absent_commits_does_no_work(self):
        import deployment_terminal
        self.assertEqual(
            deployment_terminal._route_absent_commits_to_recovery("beethoven", []), 0)

    def test_a_broken_recovery_module_does_not_stop_the_promotion_pass(self):
        import deployment_terminal
        broken = type("_M", (), {})   # no auto_recover_missing_branches attribute
        with patch.dict(sys.modules, {"missing_branch_audit": broken}):
            count = deployment_terminal._route_absent_commits_to_recovery(
                "beethoven", [{"slug": "a"}])
        self.assertEqual(count, 1)

    def test_a_raising_recovery_module_does_not_stop_the_promotion_pass(self):
        import deployment_terminal

        def _boom(**kw):
            raise RuntimeError("recovery exploded")

        mod = type("_M", (), {"auto_recover_missing_branches": staticmethod(_boom)})
        with patch.dict(sys.modules, {"missing_branch_audit": mod}):
            count = deployment_terminal._route_absent_commits_to_recovery(
                "beethoven", [{"slug": "a"}])
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
