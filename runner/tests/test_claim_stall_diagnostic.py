#!/usr/bin/env python3
"""A blocked queue must not be reportable as an empty one.

THE INCIDENT. A scheduled executor run on 2026-08-25 found 317 tasks in QUEUED,
claimed none of them, and reported a clean run — as sixteen executors had been
doing since 2026-07-15. Nothing was broken in the claim scan: every queued task
was excluded by the dependency gate, because its blocker sits in a state
(DECOMPOSED, SUPERSEDED, QUARANTINED, CLOSED) that can never become DONE or
MERGED. Verified against the live database: 317 queued, 0 with an empty deps
array, 322 dependency edges, 3 satisfied.

claim_task() returned None, which is also what it returns for an empty queue,
and every caller reads None as "no work — we are done". A dependency-starved
queue and a finished queue produced the identical signal for six weeks.

These tests pin the difference. They do not fix the deadlock — that needs
decisions about which tasks are still wanted — they make it impossible for the
next one to be invisible.
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402


PROJECTS = [{"id": "p1", "name": "app", "priority": 5, "concurrency_weight": 1}]


class _Base(unittest.TestCase):
    def setUp(self):
        # Captured BEFORE anything is replaced. Registering the cleanup after the
        # assignment would restore the fake, which is how this file briefly
        # leaked a stubbed select_all into test_ev_scheduler.
        self.orig = (db.select, db._req, db.select_all)
        self.claimed = []
        db._LAST_CLAIM_DIAGNOSTIC.update(
            {"considered": 0, "claimed": None, "reasons": {}})

    def tearDown(self):
        db.select, db._req, db.select_all = self.orig
        db.invalidate_done_cache()

    def _install(self, queued, done=()):
        done_rows = [{"slug": s, "project_id": "p1"} for s in done]

        def select(table, params=None):
            params = params or {}
            if table == "projects":
                return list(PROJECTS)
            if table == "controls":
                return []
            if table == "tasks":
                state = params.get("state")
                if state in ("eq.QUEUED", "in.(QUEUED,TESTING)"):
                    return [dict(t) for t in queued]
                if state and "DONE" in state:
                    return list(done_rows)
                return []
            return []

        def select_all(table, params=None, **kw):
            return select(table, params)

        def req(method, path, body=None, headers=None, params=None):
            tid = params.get("id", "").replace("eq.", "")
            self.claimed.append(tid)
            return [next(t for t in queued if t["id"] == tid)]

        db.select = select
        db.select_all = select_all
        db._req = req
        db.invalidate_done_cache()

    def _claim(self):
        buf = io.StringIO()
        with redirect_stdout(buf), patch.dict(
                os.environ, {"ORCH_PRIORITY_APP_FLOOR": "0"}, clear=False):
            task = db.claim_task("runner-1")
        return task, buf.getvalue()

    @staticmethod
    def _task(tid, slug, deps=()):
        return {"id": tid, "project_id": "p1", "slug": slug, "deps": list(deps),
                "created_at": "2026-01-01", "kind": "bugfix"}


class TestEmptyIsNotBlocked(_Base):
    def test_an_empty_queue_reports_nothing_considered(self):
        self._install([])
        task, out = self._claim()
        self.assertIsNone(task)
        diag = db.why_no_claim()
        self.assertEqual(diag["considered"], 0)
        self.assertIsNone(diag["claimed"])
        self.assertNotIn("STALLED", out, "an empty queue is not a stall")

    def test_a_dependency_blocked_queue_reports_a_stall(self):
        """The 2026-08-25 shape: work is present and none of it is claimable."""
        self._install([self._task("t%d" % i, "blocked-%d" % i,
                                  deps=["never-finishes"]) for i in range(5)])
        task, out = self._claim()
        self.assertIsNone(task)
        diag = db.why_no_claim()
        self.assertEqual(diag["considered"], 5)
        self.assertIsNone(diag["claimed"])
        self.assertEqual(diag["reasons"].get("deps_unmet"), 5)
        self.assertIn("STALLED", out)
        self.assertIn("0 claimable", out)

    def test_the_two_outcomes_are_distinguishable_without_reading_the_log(self):
        """A caller must be able to branch on this, not just grep stdout."""
        self._install([])
        self._claim()
        empty = db.why_no_claim()

        self._install([self._task("t1", "blocked", deps=["never-finishes"])])
        self._claim()
        blocked = db.why_no_claim()

        self.assertNotEqual(empty, blocked)
        self.assertEqual(empty["considered"], 0)
        self.assertGreater(blocked["considered"], 0)


class TestSuccessfulClaim(_Base):
    def test_a_claim_records_the_task_id(self):
        self._install([self._task("t1", "ready")])
        task, out = self._claim()
        self.assertIsNotNone(task)
        diag = db.why_no_claim()
        self.assertEqual(diag["claimed"], "t1")
        self.assertNotIn("STALLED", out)

    def test_a_satisfied_dependency_does_not_block(self):
        self._install([self._task("t1", "ready", deps=["finished"])],
                      done=["finished"])
        task, _ = self._claim()
        self.assertIsNotNone(task)
        self.assertEqual(db.why_no_claim()["reasons"].get("deps_unmet", 0), 0)


class TestReasonBreakdown(_Base):
    def test_reasons_name_which_gate_excluded_the_work(self):
        """"Nothing claimable" is not actionable; "deps_unmet=5" is."""
        self._install([self._task("t1", "a", deps=["x"]),
                       self._task("t2", "b", deps=["y"])])
        self._claim()
        reasons = db.why_no_claim()["reasons"]
        self.assertEqual(reasons.get("deps_unmet"), 2)
        self.assertEqual(sum(v for v in reasons.values()), 2,
                         "every skipped row should be accounted for exactly once")

    def test_the_diagnostic_is_a_copy(self):
        """A caller mutating what it reads must not corrupt the next scan."""
        self._install([self._task("t1", "a", deps=["x"])])
        self._claim()
        got = db.why_no_claim()
        got["considered"] = 999
        got["reasons"]["deps_unmet"] = 999
        self.assertEqual(db.why_no_claim()["considered"], 1)
        self.assertEqual(db.why_no_claim()["reasons"]["deps_unmet"], 1)


class TestSatisfiedStates(unittest.TestCase):
    def test_deployed_and_verified_counts_as_a_finished_dependency(self):
        """Strictly stronger than DONE — shipped AND verified — and it used to be
        treated as a blocker, so a dependent of fully delivered work was held
        back by its own success.

        Asserted against the query _done_slugs() issues, because the effect is
        invisible in the current data: 0 of the live queue's 322 dependency edges
        point at a DEPLOYED_AND_VERIFIED task, so this is correctness and not a
        remedy for the deadlock.
        """
        # EVERY state filter, not just the last one. _done_slugs() now issues a
        # second and third select_all to close decompositions, so recording only
        # the most recent call captured "eq.DECOMPOSED" and the assertion below
        # failed on a change that was not a regression.
        seen = []

        def select_all(table, params=None, **kw):
            seen.append((params or {}).get("state") or "")
            return []

        orig_all, orig_sel = db.select_all, db.select
        db.select_all = select_all
        db.select = lambda table, params=None: []
        try:
            db.invalidate_done_cache()
            db._done_slugs()
        finally:
            db.select_all, db.select = orig_all, orig_sel
            db.invalidate_done_cache()

        satisfying = next((s for s in seen if "DONE" in s), "")
        self.assertIn("DEPLOYED_AND_VERIFIED", satisfying)
        self.assertIn("DONE", satisfying)
        self.assertIn("MERGED", satisfying)
        # ...and the decomposition closure really is part of the same refresh.
        self.assertTrue(any("DECOMPOSED" in s for s in seen),
                        "_done_slugs must also look for closable decompositions")


if __name__ == "__main__":
    unittest.main()
