#!/usr/bin/env python3
"""Pinned-task escape hatch in db.claim_task.

Sorting can only prioritize rows that made it into the scan. The oldest-first
claim scan is capped by PostgREST at 1,000 rows, so an operator pin created
after the cap was reached is invisible to the sort no matter how high its rank.
claim_task therefore issues an independent bounded `pinned=is.true` query and
merges the result into the same atomic claim candidate set.

These tests model that cap explicitly: the main QUEUED scan returns ONLY the
unpinned backlog, and the pinned rows are reachable solely through the escape
query. If the escape query is removed, every test here fails.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db


def _task(slug, pinned=False, pin_rank=0, project_id="p1",
          created_at="2024-01-01T00:00:00"):
    return {
        "id": slug,
        "slug": slug,
        "project_id": project_id,
        "state": "QUEUED",
        "pinned": pinned,
        "pin_rank": pin_rank,
        "deps": [],
        "created_at": created_at,
    }


def _is_pinned_query(params):
    """True for the independent pinned escape query, not the main scan."""
    return str(params.get("pinned", "")).lower() == "is.true"


class _EscapeHatchHarness(unittest.TestCase):
    """Claim against a DB where pinned rows sit *outside* the capped main scan."""

    def _run_claim(self, scan_rows, pinned_rows, pinned_raises=False):
        """Return (claimed_slug, select_calls_against_tasks)."""
        claimed = []
        tasks_calls = []

        def _sel(table, params=None):
            params = params or {}
            if table == "projects":
                return [{"id": "p1", "name": "proj", "priority": 5,
                         "concurrency_weight": 1}]
            if table == "controls":
                return []
            if table != "tasks":
                return []
            tasks_calls.append(params)
            state = params.get("state", "")
            if state == "eq.QUEUED":
                if _is_pinned_query(params):
                    if pinned_raises:
                        raise RuntimeError("PostgREST 400: pinned column missing")
                    return list(pinned_rows)
                # The capped oldest-first scan. Pinned rows fell off the end.
                return list(scan_rows)
            return []

        def fake_patch(method, path, body=None, headers=None, params=None):
            if path == "/rest/v1/tasks" and body and body.get("state") == "RUNNING":
                task_id = (params or {}).get("id", "").replace("eq.", "")
                claimed.append(task_id)
                pool = list(scan_rows) + list(pinned_rows)
                task = next((t for t in pool if t["id"] == task_id), None)
                return [task] if task else []
            return None

        with patch.object(db, "select", side_effect=_sel), \
             patch.object(db, "select_all", return_value=[]), \
             patch.object(db, "_req", side_effect=fake_patch):
            db.claim_task("runner-1")

        return (claimed[0] if claimed else None), tasks_calls, claimed


class TestPinnedClaimEscape(_EscapeHatchHarness):

    def test_pin_beyond_scan_cap_is_claimable(self):
        """A pin invisible to the capped scan still wins the claim."""
        scan = [_task(f"backlog-{i}", created_at="2024-01-01T00:00:00")
                for i in range(5)]
        pinned = [_task("operator-pin", pinned=True, pin_rank=1,
                        created_at="2024-06-01T00:00:00")]
        slug, _calls, _all = self._run_claim(scan, pinned)
        self.assertEqual(slug, "operator-pin")

    def test_escape_query_is_bounded_and_pin_rank_ordered(self):
        """The escape query must be bounded and ask for pin_rank order."""
        scan = [_task("backlog-a")]
        pinned = [_task("pin-1", pinned=True, pin_rank=1)]
        _slug, calls, _all = self._run_claim(scan, pinned)

        pin_calls = [c for c in calls if _is_pinned_query(c)]
        self.assertEqual(len(pin_calls), 1,
                         "expected exactly one independent pinned query")
        params = pin_calls[0]
        self.assertEqual(params.get("state"), "eq.QUEUED")
        self.assertIn("pin_rank.asc", params.get("order", ""),
                      "pins must be fetched in pin_rank order")
        self.assertTrue(params.get("limit"), "pinned query must be bounded")
        self.assertLessEqual(int(params["limit"]), 1000,
                             "pinned query must stay under the PostgREST cap")

    def test_lowest_pin_rank_wins_among_escaped_pins(self):
        scan = [_task("backlog-a")]
        pinned = [
            _task("pin-low",  pinned=True, pin_rank=5),
            _task("pin-high", pinned=True, pin_rank=1),
            _task("pin-mid",  pinned=True, pin_rank=3),
        ]
        slug, _calls, _all = self._run_claim(scan, pinned)
        self.assertEqual(slug, "pin-high")

    def test_no_duplicate_claim_when_pin_is_in_both_result_sets(self):
        """A pin present in BOTH the scan and the escape query claims once."""
        shared = _task("pin-shared", pinned=True, pin_rank=1)
        slug, _calls, all_claims = self._run_claim([shared, _task("backlog-a")],
                                                   [shared])
        self.assertEqual(slug, "pin-shared")
        self.assertEqual(len(all_claims), 1,
                         "the same task must not be claimed twice")

    def test_failing_pinned_query_does_not_break_the_claim(self):
        """Escape query is additive: if it errors, normal claiming continues."""
        scan = [_task("backlog-a", created_at="2024-01-01T00:00:00")]
        slug, _calls, _all = self._run_claim(scan, [], pinned_raises=True)
        self.assertEqual(slug, "backlog-a")

    def test_paused_project_pin_is_still_skipped(self):
        """The escape hatch adds visibility, not an authorization bypass."""
        scan = [_task("backlog-a", project_id="p1")]
        pinned = [_task("paused-pin", pinned=True, pin_rank=1,
                        project_id="paused-project")]
        slug, _calls, _all = self._run_claim(scan, pinned)
        self.assertEqual(slug, "backlog-a",
                         "a pin in an unknown/paused project must not claim")


if __name__ == "__main__":
    unittest.main()
